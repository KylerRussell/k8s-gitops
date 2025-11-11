import ray
from ray import serve
from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM
import torch
import os
import time

# --- Configuration ---
MODEL_PATH = "/models/Qwen3-235B-A22B-Thinking-2507"
MODEL_CONFIG = AutoConfig.from_pretrained(MODEL_PATH, trust_remote_code=True)
NUM_LAYERS = MODEL_CONFIG.num_hidden_layers
SHARD_1_LAYERS = 31
SHARD_2_LAYERS = 31
SHARD_3_LAYERS = NUM_LAYERS - SHARD_1_LAYERS - SHARD_2_LAYERS

def find_checkpoint_format(model_path):
    """Find which checkpoint format is available."""
    # Check for sharded safetensors (most common for large models)
    if os.path.exists(os.path.join(model_path, "model.safetensors.index.json")):
        return "sharded_safetensors"
    # Check for single safetensors file
    elif os.path.exists(os.path.join(model_path, "model.safetensors")):
        return "safetensors"
    # Check for bin files
    elif os.path.exists(os.path.join(model_path, "pytorch_model.bin")):
        return "bin"
    else:
        raise ValueError(f"No recognized checkpoint format in {model_path}")

def load_shard_selective(model, checkpoint_path, start_layer, end_layer, is_last_shard):
    """
    Load ONLY the layers needed for this shard from sharded safetensors checkpoint.
    Model should be on meta device before calling this.
    """
    from safetensors.torch import safe_open
    import json
    
    checkpoint_format = find_checkpoint_format(checkpoint_path)
    
    print(f"Using checkpoint format: {checkpoint_format}")
    print(f"Loading layers {start_layer}-{end_layer-1}...")
    
    if checkpoint_format in ["safetensors", "sharded_safetensors"]:
        # Read the index.json to find which shards contain which tensors
        index_file = os.path.join(checkpoint_path, "model.safetensors.index.json")
        if os.path.exists(index_file):
            print("Reading sharded checkpoint index...")
            with open(index_file, 'r') as f:
                index_data = json.load(f)
            
            weight_map = index_data.get("weight_map", {})
            
            # Determine which tensors we need
            tensors_needed = set()
            
            # Embeddings (only on first shard)
            if start_layer == 0 and "model.embed_tokens.weight" in weight_map:
                tensors_needed.add("model.embed_tokens.weight")
            
            # Layers for this shard
            for i in range(start_layer, end_layer):
                for key in weight_map.keys():
                    if key.startswith(f"model.layers.{i}."):
                        tensors_needed.add(key)
            
            # Final components (only on last shard)
            if is_last_shard:
                if "model.norm.weight" in weight_map:
                    tensors_needed.add("model.norm.weight")
                if "lm_head.weight" in weight_map:
                    tensors_needed.add("lm_head.weight")
            
            # Load only the shards that contain our needed tensors
            shards_needed = set()
            for tensor_name in tensors_needed:
                if tensor_name in weight_map:
                    shard_file = weight_map[tensor_name]
                    shards_needed.add(shard_file)
            
            print(f"Need {len(tensors_needed)} tensors from {len(shards_needed)} shard files (~{len(shards_needed)*3.8:.0f}GB)")
            
            # Load tensors from needed shards only
            state_dict = {}
            for shard_idx, shard_file in enumerate(sorted(shards_needed), 1):
                shard_path = os.path.join(checkpoint_path, shard_file)
                print(f"  Shard {shard_idx}/{len(shards_needed)}: {shard_file}")
                
                with safe_open(shard_path, framework="pt", device="cpu") as f:
                    shard_keys = f.keys()
                    for key in shard_keys:
                        if key in tensors_needed:
                            state_dict[key] = f.get_tensor(key)
            
            # Load state dict - model will move from meta to CPU
            print(f"Loading {len(state_dict)} tensors into model...")
            model.load_state_dict(state_dict, strict=False)
        else:
            raise ValueError(f"No index.json found at {index_file}")
    
    return model

class ModelShard:
    """Base class to load a partial model shard."""
    def __init__(self, start_layer, end_layer, is_last_shard):
        print(f"\n{'='*60}")
        print(f"Initializing shard: layers {start_layer}-{end_layer-1}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        # Initialize model on meta device (no memory allocated)
        print("Creating model on meta device (no memory allocation)...")
        with torch.device("meta"):
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