import ray
from ray import serve
from transformers import AutoConfig, AutoTokenizer, AutoModelForCausalLM
import torch
import os
import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import json

# ============================================================================
# FIX: Patch torch.autocast to handle CPU-only inference with bfloat16
# ============================================================================
print("[PATCH] Applying torch.autocast CPU patch...")
original_autocast = torch.autocast

def patched_autocast(*args, device_type=None, **kwargs):
    """
    On CPU, torch.autocast doesn't properly support bfloat16.
    This patch returns a no-op context manager for CPU to avoid the 
    'unsupported scalarType' error while keeping all computations on CPU.
    """
    if device_type == 'cpu':
        from contextlib import nullcontext
        return nullcontext()
    return original_autocast(*args, device_type=device_type, **kwargs)

torch.autocast = patched_autocast
print("[PATCH] torch.autocast patched successfully ✓")
# ============================================================================

# --- Configuration ---
MODEL_PATH = "/models/Qwen3-235B-A22B-Thinking-2507"
MODEL_CONFIG = AutoConfig.from_pretrained(MODEL_PATH, trust_remote_code=True)
NUM_LAYERS = MODEL_CONFIG.num_hidden_layers
SHARD_1_LAYERS = 31
SHARD_2_LAYERS = 31
SHARD_3_LAYERS = NUM_LAYERS - SHARD_1_LAYERS - SHARD_2_LAYERS

# --- OpenAI API Models ---
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 100
    stream: Optional[bool] = False

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]

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

# --- OpenAI API HTTP Endpoint ---
@serve.deployment(ray_actor_options={"num_cpus": 1})
class OpenAIEndpoint:
    """OpenAI-compatible API endpoint for OpenWebUI integration."""
    
    def __init__(self, frontend: "Frontend"):
        self.frontend = frontend
        self.model_name = "qwen3-235b"
        print("[OpenAI] Endpoint initialized")
    
    async def __call__(self, request):
        """Handle HTTP requests."""
        if request.method == "GET":
            if request.url.path == "/v1/models":
                return self._list_models()
            elif request.url.path == "/health":
                return {"status": "ok"}
            else:
                return {"error": "Not found"}, 404
        
        elif request.method == "POST":
            if request.url.path == "/v1/chat/completions":
                return await self._chat_completions(request)
            elif request.url.path == "/v1/completions":
                return await self._completions(request)
            else:
                return {"error": "Not found"}, 404
        
        return {"error": "Method not allowed"}, 405
    
    def _list_models(self):
        """List available models (OpenAI API format)."""
        return {
            "object": "list",
            "data": [
                {
                    "id": self.model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local",
                }
            ]
        }
    
    async def _chat_completions(self, request):
        """Handle /v1/chat/completions requests."""
        try:
            body = await request.json()
            
            # Extract messages and convert to prompt
            messages = body.get("messages", [])
            prompt = self._format_chat_prompt(messages)
            max_tokens = body.get("max_tokens", 100)
            
            print(f"[OpenAI] Chat completion request: {prompt[:100]}...")
            
            # Call the model
            response_text = await self.frontend.generate(prompt, max_tokens)
            
            print(f"[OpenAI] Generated: {response_text[:100]}...")
            
            # Format response in OpenAI format
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": self.model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_text
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(response_text.split()),
                    "total_tokens": len(prompt.split()) + len(response_text.split())
                }
            }
        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            return {
                "error": {
                    "message": str(e),
                    "type": "internal_error",
                    "param": None,
                    "code": "internal_error"
                }
            }, 500
    
    async def _completions(self, request):
        """Handle /v1/completions requests."""
        try:
            body = await request.json()
            
            prompt = body.get("prompt", "")
            max_tokens = body.get("max_tokens", 100)
            
            print(f"[OpenAI] Completion request: {prompt[:100]}...")
            
            # Call the model
            response_text = await self.frontend.generate(prompt, max_tokens)
            
            print(f"[OpenAI] Generated: {response_text[:100]}...")
            
            # Format response
            return {
                "id": f"cmpl-{int(time.time())}",
                "object": "text_completion",
                "created": int(time.time()),
                "model": self.model_name,
                "choices": [
                    {
                        "text": response_text,
                        "index": 0,
                        "logprobs": None,
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(response_text.split()),
                    "total_tokens": len(prompt.split()) + len(response_text.split())
                }
            }
        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            return {
                "error": {
                    "message": str(e),
                    "type": "internal_error",
                    "param": None,
                    "code": "internal_error"
                }
            }, 500
    
    def _format_chat_prompt(self, messages: List[Dict]) -> str:
        """Convert chat messages to a prompt string."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"{role}: {content}")
        
        # Add assistant prefix for the model to complete
        prompt = "\n".join(prompt_parts) + "\nassistant:"
        return prompt

# --- Application Setup ---
print("Binding deployments...")
frontend_deployment = Frontend.bind(Shard1.bind(), Shard2.bind(), Shard3.bind())
openai_endpoint = OpenAIEndpoint.bind(frontend_deployment)

print("Running serve application with OpenAI endpoint...")
serve.run(openai_endpoint)

# Keep the job alive
while True:
    print("Ray Serve is running... (Job is alive)")
    time.sleep(60)