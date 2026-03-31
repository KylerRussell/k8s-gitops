import os
import torch
import torch.distributed as dist
import deepspeed
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
import ray
from huggingface_hub import login

import torch.nn as nn
import torch.nn.functional as F
import types
import warnings

# Suppress NNPACK warnings on unsupported CPU hardware
os.environ["NNPACK_DEBUG"] = "0"
warnings.filterwarnings("ignore", message="Could not initialize NNPACK")

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
        # hidden_states: [batch, seq, hidden] or [batch, hidden]
        orig_dim = hidden_states.dim()
        if orig_dim == 2:
            hidden_states = hidden_states.unsqueeze(1)
            
        # Perform convolution in Float32 to avoid NNPACK/BF16 CPU issues
        # Parameters (self.conv, self.proj) are kept in FP32
        x = hidden_states.to(torch.float32).transpose(1, 2)
        x = self.conv(x)
        x = x.transpose(1, 2)
        x = self.proj(x)
        
        # Cast back to model's native dtype (BFloat16) for residual add
        x = x.to(hidden_states.dtype)
        
        if orig_dim == 2:
            x = x.squeeze(1)
        return x

def inject_engram_modules(model, layers_to_patch=range(2, 7)):
    """
    Monkey-patches the EngramModule into specific layers of the Transformer.
    """
    for i in layers_to_patch:
        target_layer = model.model.layers[i]
        # Keep Engram in Float32 for CPU performance/compatibility
        engram = EngramModule(model.config).to(device=model.device)
        
        # Capture the original forward
        original_forward = target_layer.forward
        
        # Define the patched forward closure
        def make_patched_forward(orig_f, eng):
            def patched_forward(self, *args, **kwargs):
                outputs = orig_f(*args, **kwargs)
                if isinstance(outputs, tuple):
                    hidden_states = outputs[0]
                    # Residual injection from Engram module
                    new_hidden_states = hidden_states + eng(hidden_states)
                    return (new_hidden_states,) + outputs[1:]
                else:
                    # Fallback for when hidden_states is returned directly as a Tensor
                    return outputs + eng(outputs)
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

    # Resolve config relative to this script's directory (where Ray unpacks the working-dir)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.environ.get("DEEPSPEED_CONFIG", os.path.join(script_dir, "deepspeed_config.json"))
    print(f"[Trainer] Using DeepSpeed config: {config_path} (exists={os.path.exists(config_path)})")
        
    model_engine, optimizer, _, _ = deepspeed.initialize(
        model=model,
        model_parameters=model.parameters(),
        config=config_path
    )
    print("[Trainer] DeepSpeed active model initialized (ZeRO Stage 0).")

    # Dataset Streaming
    if os.environ.get("HF_TOKEN"):
        print("[Trainer] Authenticating with HF Hub...")
        login(token=os.environ["HF_TOKEN"])

    print(f"[Trainer] Loading NVIDIA SFT dataset in streaming mode (Rank {rank})...")
    dataset_name = "nvidia/Nemotron-Cascade-2-SFT-Data"
    # Select 'math' as the initial training domain; remove trust_remote_code as per library warning
    raw_dataset = load_dataset(dataset_name, "math", split="train", streaming=True)
    sharded_dataset = raw_dataset.shard(num_shards=world_size, index=rank)

    # Unified I/O
    shared_dir = "/workspace/shared/cascade_output"
    os.makedirs(shared_dir, exist_ok=True)
    verifier = Verifier.remote()

    # GRPO Training Loop
    print("[Trainer] Starting GRPO training loop...")
    model_engine.train()
    beta = 0.1 # KL penalty coefficient
    N = 4      
    scores = torch.tensor([0.0], device=model_engine.device)
    
    import time
    
    # Track the start of the data iteration
    it_dataset = iter(sharded_dataset)
    
    for i in range(3): # Verification limit: 3 steps
        t_start_step = time.time()
        
        if rank == 0:
            print(f"\n[Trainer] Step {i}: Fetching data...")
            
        try:
            batch_data = next(it_dataset)
        except StopIteration:
            break
            
        if rank == 0:
            print(f"[Trainer] Step {i}: Data fetched in {time.time() - t_start_step:.2f}s")
        
        t0 = time.time()

        # Handle potential key variations in different dataset subsets (math, chat, etc.)
        prompt = batch_data.get("instruction", batch_data.get("text", batch_data.get("question", "")))
        ground_truth = batch_data.get("output", batch_data.get("response", batch_data.get("answer", "")))
        
        # Handle 'messages' format specifically
        messages = batch_data.get("messages", [])
        if messages and isinstance(messages, list):
            user_content = [m["content"] for m in messages if m.get("role") == "user"]
            asst_content = [m["content"] for m in messages if m.get("role") == "assistant"]
            if user_content: prompt = user_content[-1]
            if asst_content: ground_truth = asst_content[-1]

        if not str(prompt).strip():
            if rank == 0:
                print(f"[Trainer] Step {i}: Skipping empty prompt.")
            continue
        
        # 1. Generation Phase: Produce N traces
        inputs = tokenizer(prompt, return_tensors="pt", padding=True).to(model_engine.device)
        prompt_len = inputs.input_ids.shape[1]
        
        if rank == 0:
            print(f"[Trainer] Step {i}: Generating {N} traces (prompt_len={prompt_len})...")

        with torch.no_grad():
            t_gen_start = time.time()
            outputs = model_engine.module.generate(
                **inputs,
                max_new_tokens=128,
                num_return_sequences=N,
                do_sample=True,
                pad_token_id=tokenizer.pad_token_id
            )
            if rank == 0:
                print(f"[Trainer] Step {i}: Generation complete in {time.time() - t_gen_start:.2f}s")
        
        # 2. Scoring Phase: Via Ray Verifier
        t_score_start = time.time()
        gen_texts = tokenizer.batch_decode(outputs[:, prompt_len:], skip_special_tokens=True)
        scores = ray.get([verifier.evaluate.remote(txt, ground_truth) for txt in gen_texts])
        scores = torch.tensor(scores, dtype=torch.float32, device=model_engine.device)
        if rank == 0:
            print(f"[Trainer] Step {i}: Scoring complete in {time.time() - t_score_start:.2f}s")
        
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
