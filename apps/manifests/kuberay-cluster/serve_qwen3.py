import ray
from ray import serve
from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM
from transformers.utils import is_accelerate_available
import torch
import os
import time

# Make sure accelerate is installed
if not is_accelerate_available():
    raise ImportError("Please install accelerate: pip install accelerate")
from accelerate import init_empty_weights, load_checkpoint_and_dispatch

# --- Configuration ---
MODEL_PATH = "/models/Qwen3-235B-A22B-Thinking-2507"
# --- OPTIMIZATION ---
# Use the in-memory /dev/shm filesystem for offloading.
# This avoids read/write contention on the slow /models HDD.
OFFLOAD_PATH = "/dev/shm/ray-offload" # Use in-memory storage
MODEL_CONFIG = AutoConfig.from_pretrained(MODEL_PATH, trust_remote_code=True)
NUM_LAYERS = MODEL_CONFIG.num_hidden_layers
SHARD_1_LAYERS = 31
SHARD_2_LAYERS = 31
SHARD_3_LAYERS = NUM_LAYERS - SHARD_1_LAYERS - SHARD_2_LAYERS

# *** THIS IS THE KEY CHANGE ***
def create_device_map(start_layer, end_layer, is_last_shard):
    """
    Creates a device_map for accelerate.
    Layers for *this* shard are mapped to 'cpu'.
    All *other* layers are mapped to 'disk' to satisfy accelerate.
    """
    device_map = {}
    
    # Embeddings on the first shard
    if start_layer == 0:
        device_map["model.embed_tokens"] = "cpu"
    else:
        device_map["model.embed_tokens"] = "disk" # Offload to disk

    # Transformer layers
    for i in range(NUM_LAYERS):
        if start_layer <= i < end_layer:
            # This is our shard, load to CPU
            device_map[f"model.layers.{i}"] = "cpu"
        else:
            # This is not our shard, offload to disk
            device_map[f"model.layers.{i}"] = "disk"

    # Final norm and head on the last shard
    if is_last_shard:
        device_map["model.norm"] = "cpu"
        device_map["lm_head"] = "cpu"
    else:
        device_map["model.norm"] = "disk"
        device_map["lm_head"] = "disk"
        
    return device_map

class ModelShard:
    """Base class to load a partial model shard."""
    def __init__(self, start_layer, end_layer, is_last_shard):
        print(f"Initializing shard: layers {start_layer}-{end_layer-1}")
        
        with init_empty_weights():
            model = AutoModelForCausalLM.from_config(
                MODEL_CONFIG, 
                torch_dtype=torch.bfloat16, 
                trust_remote_code=True
            )
        
        device_map = create_device_map(start_layer, end_layer, is_last_shard)
        
        print(f"Loading weights for layers {start_layer}-{end_layer-1}...")
        
        # *** THIS IS THE SECOND KEY CHANGE ***
        load_checkpoint_and_dispatch(
            model,
            MODEL_PATH,
            device_map=device_map,
            no_split_module_classes=["Qwen2DecoderLayer"],
            dtype=torch.bfloat16,
            offload_folder=OFFLOAD_PATH, # <-- Use our persistent path
            offload_state_dict=True  # <-- Tell it to offload
        )
        print(f"Shard (layers {start_layer}-{end_layer-1}) loaded successfully.")
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

    # This is a simple endpoint, not OpenAI-compatible
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