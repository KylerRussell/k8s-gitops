# Web UI Options for Qwen3-235B

Here are the best web interfaces to access your LLM:

## 🌟 Option 1: Open WebUI (Recommended)

**Best for:** Beautiful, modern interface with conversation history, user management

**Features:**
- ✅ Beautiful ChatGPT-like interface
- ✅ Conversation history
- ✅ User authentication
- ✅ Multiple models support
- ✅ Document upload (RAG)

**Access:** http://chat.homelab.com

See `../open-webui/` directory for deployment manifests.

---

## 🔧 Option 2: LibreChat

**Best for:** Multi-provider support, advanced features

**Features:**
- ✅ Support for multiple AI providers
- ✅ Preset prompts
- ✅ Conversation branching
- ✅ User system

---

## 💻 Option 3: Text Generation WebUI (oobabooga)

**Best for:** Advanced model tweaking, multiple inference backends

Run locally with Docker:
```bash
docker run -p 7860:7860 \
  -e OPENAI_API_BASE=http://llm.homelab.com/v1 \
  atinoda/text-generation-webui:latest
```

**Features:**
- ✅ Extensive parameter control
- ✅ Multiple chat modes
- ✅ Extensions support

---

## 📱 Option 4: Desktop/Mobile Apps

Use existing apps with custom endpoint:

**AnythingLLM (Desktop):**
- Download: https://anythingllm.com/
- Settings → LLM → OpenAI
- Custom Base URL: `http://llm.homelab.com/v1`

**Chatbox (Desktop/Mobile):**
- Download: https://chatboxai.app/
- Add custom OpenAI endpoint

---

## 🎯 My Recommendation

**Deploy Open WebUI** for the best experience. It's the most polished and feature-complete option.

Quick deploy:
```bash
kubectl apply -f apps/manifests/open-webui/
```

Then access at: http://chat.homelab.com
