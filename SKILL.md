---
name: nvidia-key-proxy
description: OpenAI-compatible proxy server for Nvidia API with automatic key rotation on 429 errors. Supports streaming and non-streaming requests across 2-5 hardcoded API keys.
compatibility: Created for Zo Computer
metadata:
  author: larsondrake.zo.computer
allowed-tools: ""
---

# Nvidia Key Proxy

OpenAI-compatible proxy that rotates through multiple Nvidia API keys when rate limits (429) are hit. Cycles through all keys before returning error.

## Quick Start

```bash
# Start the proxy locally
cd /home/workspace/Skills/nvidia-key-proxy/scripts
python3 proxy.py
```

## Expose to Internet (Zo User Service)

**The working method:** Register as a Zo User Service for a permanent public URL.

```bash
# In Zo chat, use the register_user_service tool:
register_user_service(
  label="nvidia-key-proxy",
  mode="http",
  local_port=3090
)
```

This gives you:
- **HTTP URL**: `https://nvidia-key-proxy-larsondrake.zocomputer.io`
- **TCP Addr**: `ts4.zocomputer.io:10786`

### Why Zo User Service?

| Method | Status |
|--------|--------|
| **Zo User Service** | ✅ Works - permanent URL, survives reboot |
| Cloudflare Tunnel | ❌ Errors - connection issues in sandbox |
| bore.pub | ⚠️ Works but random port, dies on restart |
| serveo.net | ❌ Requires SSH keepalive |

The Zo User Service is the recommended way - it provides a stable HTTPS URL managed by Zo's infrastructure.

## Usage

### With BYOK Platforms (OpenRouter, Vercel AI SDK, etc.)

| Setting | Value |
|---------|-------|
| **Base URL** | `https://nvidia-key-proxy-larsondrake.zocomputer.io/v1` |
| **API Key** | Any string (e.g., `sk-test`) |
| **Model** | Any Nvidia model (see below) |

### Non-streaming

```bash
curl -X POST https://nvidia-key-proxy-larsondrake.zocomputer.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any-key" \
  -d '{"model": "stepfun-ai/step-3.5-flash", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Streaming

```bash
curl -X POST https://nvidia-key-proxy-larsondrake.zocomputer.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any-key" \
  -d '{"model": "stepfun-ai/step-3.5-flash", "messages": [{"role": "user", "content": "Hello"}], "stream": true}'
```

## Supported Models

Model is **not hard coded** - proxy forwards whatever model you specify. Examples:

- `stepfun-ai/step-3.5-flash`
- `meta/llama-3.1-8b-instruct`
- `meta/llama-3.1-70b-instruct`
- `deepseek-ai/deepseek-v3`

Check available models:
```bash
curl https://nvidia-key-proxy-larsondrake.zocomputer.io/v1/models \
  -H "Authorization: Bearer any-key"
```

## Key Rotation Logic

1. Request sent with current key (starts at key 1)
2. If 429 received, rotate to next key and retry
3. Continue cycling through all keys (key 1 → key 2 → key 3 → key 1 → ...)
4. If all keys exhausted, return 429 with "all keys exhausted" message

## Streaming Implementation

**Response streaming is enabled** - proxy streams 8KB chunks back to client immediately:

| Feature | Value |
|---------|-------|
| Chunk size | 8KB |
| Timeout | 300 seconds |
| Disconnect handling | Graceful (logged, not crashed) |

This fixes issues with long responses (coding sessions, tool calls) where buffering caused timeouts. Chunks flow immediately instead of waiting for full response.

## Configuration

Edit `scripts/proxy.py` to add/remove API keys:

```python
API_KEYS = [
    "nvapi-FirstKeyHere",
    "nvapi-SecondKeyHere",
    # "nvapi-ThirdKeyHere",
]
```

After editing, restart the service:
```bash
pkill -f proxy.py
python3 /home/workspace/Skills/nvidia-key-proxy/scripts/proxy.py &
```

## Files

- `scripts/proxy.py` - Main proxy server (Python, no dependencies)
- `references/` - API documentation and notes
