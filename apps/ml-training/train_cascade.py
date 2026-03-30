import os
import torch
import torch.distributed as dist
import deepspeed
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
import ray

import torch.nn as nn
import torch.nn.functional as F
import types

class EngramModule(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.hidden_size = config.hidden_size
        self.n_gram = 3 
        
        # Simple 1D Conv to capture N-gram context over hidden states
        self.conv = nn.Conv1d(
            self.hidden_size, 
            self.hidden_size, 
            kernel_size=self.n_gram, 
            padding=self.n_gram // 2
        )
        
        # Final projection - MUST be zero-initialized for identity mapping
        self.proj = nn.Linear(self.hidden_size, self.hidden_size)
        nn.init.zeros_(self.proj.weight)
        nn.init.zeros_(self.proj.bias)

    def forward(self, hidden_states):
        # hidden_states: [batch, seq, hidden]
        x = hidden_states.transpose(1, 2) 
        x = self.conv(x)
        x = x.transpose(1, 2)
        x = self.proj(x)
        return x

def inject_engram_modules(model, layers_to_patch=range(2, 7)):
    """
    Monkey-patches the EngramModule into specific layers of the Transformer.
    """
    for i in layers_to_patch:
        target_layer = model.model.layers[i]
        engram = EngramModule(model.config).to(model.device)
        
        # Capture the original forward
        original_forward = target_layer.forward
        
        # Define the patched forward closure
        def make_patched_forward(orig_f, eng):
            def patched_forward(self, *args, **kwargs):
                outputs = orig_f(*args, **kwargs)
                hidden_states = outputs[0]
                # Residual injection from Engram module
                new_hidden_states = hidden_states + eng(hidden_states)
                return (new_hidden_states,) + outputs[1:]
            return patched_forward

        target_layer.forward = types.MethodType(make_patched_forward(original_forward, engram), target_layer)
        # Use add_module for strict PyTorch parameter registration
        target_layer.add_module("engram_block", engram)
    
    print(f"[Engram] Injected modules into layers: {list(layers_to_patch)}")

@ray.remote
class Verifier:
    def evaluate(self, generated_text, ground_truth):
        """
        Evaluates generated text against the expected ground truth.
        Supports basic mathematical equivalence and string matching.
        """
        gen = str(generated_text).strip().lower()
        ref = str(ground_truth).strip().lower()
        
        # Basic check for mathematical equivalence if numeric
        try:
            if float(gen) == float(ref):
                return 1.0
        except ValueError:
            pass

        # String matching / substring check
        if ref in gen or gen == ref:
            return 1.0
        
        return 0.0

def main():
    # Enforce using gloo backend for cpu-only distributed training
    os.environ["MASTER_ADDR"] = os.environ.get("MASTER_ADDR", "127.0.0.1")
    os.environ["MASTER_PORT"] = os.environ.get("MASTER_PORT", "29500")
    os.environ["WORLD_SIZE"] = os.environ.get("WORLD_SIZE", "1")
    os.environ["RANK"] = os.environ.get("RANK", "0")
    os.environ["LOCAL_RANK"] = os.environ.get("LOCAL_RANK", "0")
    
    # Initialize the PyTorch distributed process group explicitly using the gloo backend
    dist.init_process_group(backend="gloo")
    rank = dist.get_rank()
    world_size = dist.get_world_size()

    print(f"[Trainer] Rank {rank}/{world_size} initialized with gloo.")

    # Model and Tokenizer setup
    model_name = "Qwen/Qwen2.5-0.5B"
    print(f"[Trainer] Loading tokenizer and model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        
    model = AutoModelForCausalLM.from_pretrained(model_name)

    # Phase 6: Engram Architectural Injection
    inject_engram_modules(model)

    # Initialize Ray
    ray.init(ignore_reinit_error=True)
    print("[Trainer] Ray initialized.")

    # Phase 7: GRPO RL Pipeline - Reference Model
    print(f"[Trainer] Loading Reference Model (Frozen): {model_name}")
    # Use device_map="cpu" to safely offload the frozen ref model to system RAM for 35B scaling
    model_ref = AutoModelForCausalLM.from_pretrained(
        model_name, 
        device_map="cpu", 
        torch_dtype=torch.float32 
    )
    model_ref.eval()
    for param in model_ref.parameters():
        param.requires_grad = False

    # Wrap active model in DeepSpeed
    config_path = os.environ.get("DEEPSPEED_CONFIG", "/workspace/shared/deepspeed_config.json")
    if not os.path.exists(config_path):
        config_path = "/app/deepspeed_config.json"
        
    model_engine, optimizer, _, _ = deepspeed.initialize(
        model=model,
        model_parameters=model.parameters(),
        config=config_path
    )
    print("[Trainer] DeepSpeed active model initialized with DeepSpeed.")

    # Dataset Streaming
    print(f"[Trainer] Loading NVIDIA SFT dataset in streaming mode (Rank {rank})...")
    dataset_name = "nvidia/Nemotron-Cascade-2-SFT-Data"
    raw_dataset = load_dataset(dataset_name, split="train", streaming=True)
    sharded_dataset = raw_dataset.shard(num_shards=world_size, index=rank)

    # Unified I/O
    shared_dir = "/workspace/shared/cascade_output"
    os.makedirs(shared_dir, exist_ok=True)
    verifier = Verifier.remote()

    # GRPO Training Loop
    print("[Trainer] Starting GRPO training loop...")
    model_engine.train()
    beta = 0.1 # KL penalty coefficient
    N = 4      # Group size
    
    for i, batch_data in enumerate(sharded_dataset):
        if i >= 3: # Verification limit
            break
            
        prompt = batch_data.get("instruction", batch_data.get("text", ""))
        ground_truth = batch_data.get("output", batch_data.get("response", ""))
        
        # 1. Generation Phase: Produce N traces
        inputs = tokenizer(prompt, return_tensors="pt", padding=True).to(model_engine.device)
        prompt_len = inputs.input_ids.shape[1]
        
        with torch.no_grad():
            # ZeRO-3 Fix: Temporarily gather sharded parameters for auto-regressive generation
            with deepspeed.zero.GatheredParameters(model_engine.module.parameters()):
                outputs = model_engine.module.generate(
                    **inputs,
                    max_new_tokens=48,
                    num_return_sequences=N,
                    do_sample=True,
                    pad_token_id=tokenizer.pad_token_id
                )
        
        # 2. Scoring Phase: Via Ray Verifier
        gen_texts = tokenizer.batch_decode(outputs[:, prompt_len:], skip_special_tokens=True)
        scores = ray.get([verifier.evaluate.remote(txt, ground_truth) for txt in gen_texts])
        scores = torch.tensor(scores, dtype=torch.float32, device=model_engine.device)
        
        # 3. Advantage Calculation (Group Relative)
        advantages = (scores - scores.mean()) / (scores.std() + 1e-8)
        
        # 4. GRPO Loss Calculation
        # Create an attention mask so the model ignores pad tokens during the logprob calculation
        attn_mask = (outputs != tokenizer.pad_token_id).long()

        active_logits = model_engine(input_ids=outputs, attention_mask=attn_mask).logits[:, prompt_len-1:-1, :]
        with torch.no_grad():
            ref_logits = model_ref(input_ids=outputs, attention_mask=attn_mask).logits[:, prompt_len-1:-1, :]
            
        active_logprobs = F.log_softmax(active_logits, dim=-1)
        ref_logprobs = F.log_softmax(ref_logits, dim=-1)
        
        # Extract logprobs for the actual generated tokens
        gen_tokens = outputs[:, prompt_len:]
        active_token_logprobs = torch.gather(active_logprobs, dim=-1, index=gen_tokens.unsqueeze(-1)).squeeze(-1)
        ref_token_logprobs = torch.gather(ref_logprobs, dim=-1, index=gen_tokens.unsqueeze(-1)).squeeze(-1)
        
        # Importance weighting (here simplified for v1 as pure policy gradient on current policy)
        # Loss = - Adv * log_prob + beta * KL
        # KL Divergence: sum(exp(ref_logprob) * (ref_logprob - active_logprob))
        # Or more simply: active_logprob - ref_logprob 
        kl_div = active_token_logprobs - ref_token_logprobs
        
        # Aggregate per trace
        per_token_loss = -advantages.unsqueeze(-1) * active_token_logprobs + beta * kl_div
        loss = per_token_loss.mean()
        
        # 5. Optimization
        model_engine.backward(loss)
        model_engine.step()
        
        if rank == 0:
            print(f"[Trainer] GRPO Step {i} | Loss: {loss.item():.4f} | Avg Reward: {scores.mean():.2f}")

    # Unified I/O: Save
    checkpoint_dir = os.path.join(shared_dir, "checkpoints")
    if rank == 0:
        model_engine.module.save_pretrained(checkpoint_dir)
        print(f"[Trainer] Final model saved to {checkpoint_dir}")
        
        with open(os.path.join(shared_dir, "training_log.txt"), "a") as f:
            f.write(f"GRPO run complete. Final Avg Reward: {scores.mean():.2f}\n")
    
    print(f"[Trainer] Rank {rank} finished.")

if __name__ == "__main__":
    main()
