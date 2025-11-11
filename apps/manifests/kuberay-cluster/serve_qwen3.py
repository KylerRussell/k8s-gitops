import ray
from ray import serve
from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM
import torch
import os
import time
from safetensors.torch import safe_open

# --- Configuration ---
MODEL_PATH = "/models/Qwen3-235B-A22B-Thinking-2507"
MODEL_CONFIG = AutoConfig.from_pretrained(MODEL_PATH, trust_remote_code=True)
NUM_LAYERS = MODEL_CONFIG.num_hidden_layers
SHARD_1_LAYERS = 31
SHARD_2_LAYERS = 31
SHARD_3_LAYERS = NUM_LAYERS - SHARD_1_LAYERS - SHARD_2_LAYERS

def find_checkpoint_format(model_path):
    """Find which checkpoint format is available."""
    # Check for safetensors (fastest)
    if os.path.exists(os.path.join(model_path, "model.safetensors")):
        return "safetensors"
    # Check for bin files
    elif os.path.exists(os.path.join(model_path, "pytorch_model.bin")):
        return "bin"
    else:
        raise ValueError(f"No recognized checkpoint format in {model_path}")

def load_shard_selective(model, checkpoint_path, start_layer, end_layer, is_last_shard):
    """
    Load ONLY the layers needed for this shard from checkpoint.
    This avoids loading the entire 470GB model.
    """
    checkpoint_format = find_checkpoint_format(checkpoint_path)
    state_dict = {}
    
    print(f"Using checkpoint format: {checkpoint_format}")
    print(f"Loading layers {start_layer}-{end_layer-1}...")
    
    if checkpoint_format == "safetensors":
        checkpoint_file = os.path.join(checkpoint_path, "model.safetensors")
        with safe_open(checkpoint_file, framework="pt", device="cpu") as f:
            keys = f.keys()
            
            # Load embedding layer (only on first shard)
            if start_layer == 0 and "model.embed_tokens.weight" in keys:
                print("  Loading embeddings...")
                state_dict["model.embed_tokens.weight"] = f.get_tensor("model.embed_tokens.weight")
            
            # Load only the layers for this shard
            for i in range(start_layer, end_layer):
                layer_prefix = f"model.layers.{i}."
                layer_keys = [k for k in keys if k.startswith(layer_prefix)]
                
                if layer_keys:
                    print(f"  Loading layer {i} ({len(layer_keys)} tensors)...")
                    for key in layer_keys:
                        state_dict[key] = f.get_tensor(key)
            
            # Load final components (only on last shard)
            if is_last_shard:
                if "model.norm.weight" in keys:
                    print("  Loading final norm...")
                    state_dict["model.norm.weight"] = f.get_tensor("model.norm.weight")
                if "lm_head.weight" in keys:
                    print("  Loading lm_head...")
                    state_dict["lm_head.weight"] = f.get_tensor("lm_head.weight")
    
    elif checkpoint_format == "bin":
        # For safetensors, selective loading is much faster
        # For .bin format, you may need to load the full state dict and filter
        # This is slower but works
        import torch
        checkpoint_file = os.path.join(checkpoint_path, "pytorch_model.bin")
        print(f"WARNING: Using .bin format is slow. Consider converting to safetensors.")
        full_state = torch.load(checkpoint_file, map_location="cpu")
        
        # Extract only layers we need
        for key in full_state.keys():
            # Check if this key belongs to our shard
            if start_layer == 0 and key == "model.embed_tokens.weight":
                state_dict[key] = full_state[key]
            elif key.startswith("model.layers."):
                layer_num = int(key.split(".")[2])
                if start_layer <= layer_num < end_layer:
                    state_dict[key] = full_state[key]
            elif key in ["model.norm.weight", "lm_head.weight"] and is_last_shard:
                state_dict[key] = full_state[key]
    
    # Load state dict into model
    print(f"Assigning {len(state_dict)} tensors to model...")
    model.load_state_dict(state_dict, strict=False)
    return model

class ModelShard:
    """Base class to load a partial model shard."""
    def __init__(self, start_layer, end_layer, is_last_shard):
        print(f"\n{'='*60}")
        print(f"Initializing shard: layers {start_layer}-{end_layer-1}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        # Initialize empty model (no weights yet)
        print("Creating empty model structure...")
        model = AutoModelForCausalLM.from_config(
            MODEL_CONFIG, 
            torch_dtype=torch.bfloat16,
            trust_remote_code=True
        )
        
        # Load only this shard's weights from checkpoint
        print("Loading selective weights from checkpoint...")
        model = load_shard_selective(model, MODEL_PATH, start_layer, end_layer, is_last_shard)
        
        elapsed = time.time() - start_time
        print(f"Shard loaded in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print(f"{'='*60}\n")
        
        self.model = model.eval()

# --- Shard Deployments ---
@serve.deployment(ray_actor_options={"num_cpus": 55, "memory": 200 * 1024 * 1024 * 1024})
class Shard1(ModelShard):
    def __init__(self):
        super().__init__(0, SHARD_1_LAYERS, is_last_shard=False)
    def forward(self, input_ids):
        return self.model(input_ids=input_ids, use_cache=False)[0]

@serve.deployment(ray_actor_options={"num_cpus": 55, "memory": 200 * 1024 * 1024 * 1024})
class Shard2(ModelShard):
    def __init__(self):
        super().__init__(SHARD_1_LAYERS, SHARD_1_LAYERS + SHARD_2_LAYERS, is_last_shard=False)
    def forward(self, hidden_states):
        return self.model(inputs_embeds=hidden_states, use_cache=False)[0]

@serve.deployment(ray_actor_options={"num_cpus": 55, "memory": 200 * 1024 * 1024 * 1024})
class Shard3(ModelShard):
    def __init__(self):
        super().__init__(SHARD_1_LAYERS + SHARD_2_LAYERS, NUM_LAYERS, is_last_shard=True)
    def forward(self, hidden_states):
        return self.model(inputs_embeds=hidden_states, use_cache=False).logits

# --- SIMPLE FRONTEND ---
@serve.deployment(ray_actor_options={"num_cpus": 1})
class Frontend:
    def __init__(self, shard1: "Shard1", shard2: "Shard2", shard3: "Shard3"):
        print("Initializing Frontend...")
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
        self.shard1 = shard1
        self.shard2 = shard2
        self.shard3 = shard3
        print("Frontend initialized.")

    async def generate(self, text: str, max_new_tokens: int = 100):
        print(f"Frontend: Received request: '{text}'")
        input_ids = self.tokenizer(text, return_tensors="pt").input_ids
        
        generated_ids = []
        for _ in range(max_new_tokens):
            print(f"Frontend: Generating token {_+1}...")
            
            hidden_states_ref = self.shard1.forward.remote(input_ids)
            hidden_states_ref = self.shard2.forward.remote(hidden_states_ref)
            logits_ref = self.shard3.forward.remote(hidden_states_ref)
            
            logits = await logits_ref
            
            next_token_id = torch.argmax(logits[0, -1, :]).item()
            generated_ids.append(next_token_id)

            if next_token_id == self.tokenizer.eos_token_id:
                break
                
            input_ids = torch.cat(
                [input_ids, torch.tensor([[next_token_id]])], dim=-1
            )

        print("Frontend: Generation complete.")
        return self.tokenizer.decode(generated_ids, skip_special_tokens=True)

# --- Application Setup ---
print("Binding deployments...")
app = Frontend.bind(Shard1.bind(), Shard2.bind(), Shard3.bind())

print("Running serve application...")
serve.run(app)

# Keep the job alive
while True:
    print("Ray Serve is running... (Job is alive)")
    time.sleep(60)