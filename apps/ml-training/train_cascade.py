import os
import torch
import torch.distributed as dist
import deepspeed
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
import ray

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

    # Initialize Ray
    ray.init(ignore_reinit_error=True)
    print("[Trainer] Ray initialized.")

    # Wrap model in DeepSpeed using the configuration profile
    config_path = os.environ.get("DEEPSPEED_CONFIG", "/workspace/shared/deepspeed_config.json")
    if not os.path.exists(config_path):
        config_path = "/app/deepspeed_config.json"
        
    model_engine, optimizer, _, _ = deepspeed.initialize(
        model=model,
        model_parameters=model.parameters(),
        config=config_path
    )
    print("[Trainer] DeepSpeed initialized.")

    # Dataset Streaming: Load NVIDIA SFT Data
    # Path 3: Use streaming=True to handle massive memory footprint
    print(f"[Trainer] Loading NVIDIA SFT dataset in streaming mode (Rank {rank})...")
    dataset_name = "nvidia/Nemotron-Cascade-2-SFT-Data"
    raw_dataset = load_dataset(dataset_name, split="train", streaming=True)
    
    # Distributed Data Sampler: Shard the stream so each server gets unique data
    sharded_dataset = raw_dataset.shard(num_shards=world_size, index=rank)

    # Unified I/O Paths
    shared_dir = "/workspace/shared/cascade_output"
    os.makedirs(shared_dir, exist_ok=True)
    
    # Simple Training Loop
    print("[Trainer] Starting training loop...")
    model_engine.train()
    
    last_loss = 0.0
    for i, batch_data in enumerate(sharded_dataset):
        if i >= 5: # Limit steps for verification run
            break
            
        # Tokenize input (from the dataset 'text' or 'instruction/output' fields)
        # Nemotron SFT data typically has 'instruction' and 'response' or just 'text'
        text_content = batch_data.get("text", batch_data.get("instruction", ""))
        inputs = tokenizer(text_content, return_tensors="pt", padding=True, truncation=True, max_length=512)
        inputs = {k: v.to(model_engine.device) for k, v in inputs.items()}
        
        # Forward pass
        outputs = model_engine(**inputs, labels=inputs["input_ids"])
        loss = outputs.loss
        last_loss = loss.item()
        
        # Backward pass
        model_engine.backward(loss)
        
        # Optimizer step
        model_engine.step()
        
        if rank == 0:
            print(f"[Trainer] Step {i} complete. Loss: {last_loss:.4f}")

    # Unified I/O: Route checkpoint saving to shared volume
    checkpoint_dir = os.path.join(shared_dir, "checkpoints")
    if rank == 0:
        model_engine.module.save_pretrained(checkpoint_dir)
        print(f"[Trainer] Model checkpoint successfully saved to {checkpoint_dir}")

    # Ray Actor Logic (The Verifier): RL Environment Evaluator
    if rank == 0:
        verifier = Verifier.remote()
        sample_gen = "The solution is 42."
        sample_ref = "42"
        score = ray.get(verifier.evaluate.remote(sample_gen, sample_ref))
        print(f"[Trainer] Verifier evaluation test score: {score}")
        
        # Log results to shared volume
        with open(os.path.join(shared_dir, "training_log.txt"), "a") as f:
            f.write(f"Run complete. Step 5 Loss: {last_loss:.4f}. RL Score: {score}\n")
    
    print(f"[Trainer] Rank {rank} finished.")

if __name__ == "__main__":
    main()
