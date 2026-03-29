import os
import torch
import torch.distributed as dist
import deepspeed
from transformers import AutoModelForCausalLM
import ray

@ray.remote
class Verifier:
    def evaluate(self, text):
        """
        Takes a generated text output, runs it through a verification logic
        (e.g., local python subprocess or math parser), and returns a scalar reward score.
        """
        # Dummy verification logic for the environment verification (Cascade RL)
        if "correct" in text.lower() or "1" in text:
            return 1.0
        return 0.0

def main():
    # Enforce using gloo backend for cpu-only distributed training
    os.environ["MASTER_ADDR"] = os.environ.get("MASTER_ADDR", "127.0.0.1")
    os.environ["MASTER_PORT"] = os.environ.get("MASTER_PORT", "29500")
    os.environ["WORLD_SIZE"] = os.environ.get("WORLD_SIZE", "1")
    os.environ["RANK"] = os.environ.get("RANK", "0")
    
    # Initialize the PyTorch distributed process group explicitly using the gloo backend
    dist.init_process_group(backend="gloo")

    print("[Trainer] Distributed group initialized with gloo.")

    # Hardcode the model architecture to load a tiny test model first
    model_name = "Qwen/Qwen2.5-0.5B"
    print(f"[Trainer] Loading dummy model target: {model_name}")
    model = AutoModelForCausalLM.from_pretrained(model_name)

    # Initialize Ray
    ray.init(ignore_reinit_error=True)
    print("[Trainer] Ray initialized.")

    # Wrap model in DeepSpeed using the configuration profile that disables nccl / uses cpu parameters
    config_path = os.environ.get("DEEPSPEED_CONFIG", "/workspace/shared/deepspeed_config.json")
    
    # If the file doesn't exist in shared workspace, fallback to baked-in
    if not os.path.exists(config_path):
        config_path = "/app/deepspeed_config.json"
        
    model_engine, optimizer, _, _ = deepspeed.initialize(
        model=model,
        model_parameters=model.parameters(),
        config=config_path
    )

    print("[Trainer] DeepSpeed initialized.")

    # Unified I/O Paths: Route all model checkpoint saving, Engram table initialization, and logging explicitly to the /workspace/shared/ directory
    shared_dir = "/workspace/shared/cascade_output"
    os.makedirs(shared_dir, exist_ok=True)
    
    checkpoint_dir = os.path.join(shared_dir, "checkpoints")
    model_engine.save_checkpoint(checkpoint_dir)
    print(f"[Trainer] Model checkpoint successfully saved to {checkpoint_dir}")

    # Validate Verifier Ray Actor
    verifier = Verifier.remote()
    sample_text = "This is a correct output with 1 step."
    score = ray.get(verifier.evaluate.remote(sample_text))
    print(f"[Trainer] Verifier scored the text '{sample_text}': {score}")
    
    # Logging
    with open(os.path.join(shared_dir, "training_log.txt"), "a") as f:
        f.write(f"Training run complete. Verifier test score: {score}\n")
    print(f"[Trainer] Logs updated in {shared_dir}/training_log.txt")

if __name__ == "__main__":
    main()
