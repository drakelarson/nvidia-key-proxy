# Nvidia API Key Rotation Proxy

OpenAI-compatible proxy server for Nvidia's API with automatic key rotation on rate limits (429 errors). Supports both streaming and non-streaming requests across multiple hardcoded API keys.

## Features

- **Automatic Key Rotation** — Cycles through all keys when hitting 429 rate limits
- **Streaming Support** — Streams responses in 8KB chunks for real-time output
- **OpenAI-Compatible** — Works with any BYOK platform (OpenRouter, Vercel AI SDK, etc.)
- **Zero Dependencies** — Pure Python, uses only standard library
- **Model Passthrough** — Forward any Nvidia model, nothing hard-coded

## Quick Start

```bash
# Clone the repo
git clone https://github.com/drakelarson/nvidia-key-proxy.git
cd nvidia-key-proxy

# Add your API keys to proxy.py
nano scripts/proxy.py  # Edit API_KEYS list

# Run the proxy
python3 scripts/proxy.py
```

Proxy will be available at `http://localhost:3090/v1`

## Configuration

Edit `scripts/proxy.py` to add your Nvidia API keys:

```python
API_KEYS = [
    "nvapi-YourFirstKeyHere",
    "nvapi-YourSecondKeyHere",
    "nvapi-YourThirdKeyHere",
    # Add up to 5 keys
]
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3090` | Port to listen on |

## Usage

### With BYOK Platforms

Use these settings in any platform that supports custom OpenAI-compatible endpoints:

| Setting | Value |
|---------|-------|
| **Base URL** | `http://your-server:3090/v1` |
| **API Key** | Any string (e.g., `sk-test`) |
| **Model** | Any Nvidia model |

### Direct API Calls

**Non-streaming:**
```bash
curl -X POST http://localhost:3090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any-key" \
  -d '{
    "model": "stepfun-ai/step-3.5-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Streaming:**
```bash
curl -X POST http://localhost:3090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any-key" \
  -d '{
    "model": "stepfun-ai/step-3.5-flash",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### List Available Models

```bash
curl http://localhost:3090/v1/models \
  -H "Authorization: Bearer any-key"
```

## Supported Models

Model is **not hard-coded** — the proxy forwards whatever model you specify. Common Nvidia models:

| Model | Description |
|-------|-------------|
| `stepfun-ai/step-3.5-flash` | Fast, efficient |
| `meta/llama-3.1-8b-instruct` | Llama 3.1 8B |
| `meta/llama-3.1-70b-instruct` | Llama 3.1 70B |
| `meta/llama-3.1-405b-instruct` | Llama 3.1 405B |
| `deepseek-ai/deepseek-v3` | DeepSeek V3 |
| `mistralai/mistral-large` | Mistral Large |

## Key Rotation Logic

```
Request arrives
    ↓
Send with Key 1
    ↓
429 received? ──Yes──→ Rotate to Key 2 → Retry
    ↓No                         ↓
Return response            429 received? ──Yes──→ Rotate to Key 3 → Retry
                                   ↓No                         ↓
                              Return response            ...cycle through all keys...
                                                               ↓
                                                    All keys exhausted?
                                                               ↓
                                                         Return 429
```

The proxy cycles through all keys circularly (1→2→3→1→2→...) before returning a 429 error.

## Deployment

### Local / VPS

```bash
# Run in background
nohup python3 scripts/proxy.py > proxy.log 2>&1 &

# Or with systemd (recommended for production)
sudo cp nvidia-key-proxy.service /etc/systemd/system/
sudo systemctl enable nvidia-key-proxy
sudo systemctl start nvidia-key-proxy
```

### Zo Computer

If using Zo Computer, register as a user service for a permanent public URL:

```python
register_user_service(
    label="nvidia-key-proxy",
    mode="http",
    local_port=3090,
    entrypoint="python3 /home/workspace/Skills/nvidia-key-proxy/scripts/proxy.py",
    workdir="/home/workspace/Skills/nvidia-key-proxy/scripts"
)
```

This provides:
- **HTTP URL**: `https://nvidia-key-proxy-yourhandle.zocomputer.io`
- **TCP Addr**: `ts4.zocomputer.io:XXXXX`

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY scripts/proxy.py .
EXPOSE 3090
CMD ["python3", "proxy.py"]
```

```bash
docker build -t nvidia-key-proxy .
docker run -d -p 3090:3090 nvidia-key-proxy
```

### Cloudflare Tunnel

For exposing a local instance to the internet:

```bash
cloudflared tunnel --url http://localhost:3090
```

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completions (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/v1/models/{model}` | GET | Get model info |

### Request Format

Standard OpenAI format:

```json
{
  "model": "stepfun-ai/step-3.5-flash",
  "messages": [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1024
}
```

### Response Format

**Non-streaming:**
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "stepfun-ai/step-3.5-flash",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello! How can I help you?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 8,
    "total_tokens": 18
  }
}
```

**Streaming:**
```
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"Hello"}}]}
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"!"}}]}
data: {"id":"chatcmpl-xxx","choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

## Error Handling

| Status | Description |
|--------|-------------|
| `200` | Success |
| `400` | Bad request (invalid model, malformed JSON) |
| `401` | Invalid Nvidia API key |
| `429` | All keys rate limited |
| `502` | Proxy error (upstream unreachable) |

**429 Response (all keys exhausted):**
```json
{
  "error": "All API keys rate limited",
  "keys_tried": 3
}
```

## Monitoring

The proxy logs to stdout with structured messages:

```
[PROXY] Listening on http://0.0.0.0:3090
[PROXY] 2 API key(s) loaded
[PROXY] POST /v1/chat/completions → key=1/2
[PROXY] 429 from key 1
[PROXY] 429 → rotating to key 2/2 (total 429s: 1)
[PROXY] ← 200 (1234ms, 5 chunks, 4096 bytes)
[PROXY] Client disconnected after 3 chunks (24576 bytes): [Errno 32] Broken pipe
```

## Performance

- **Chunk Size**: 8KB for streaming
- **Timeout**: 120 seconds for upstream requests
- **Threading**: Multi-threaded (one thread per request)
- **Memory**: ~40MB base, +memory per concurrent request

## Troubleshooting

### BrokenPipeError in logs

Client disconnected before response completed. Normal for:
- Long streaming responses
- Client-side timeouts
- User cancellation

### 429 even with multiple keys

All keys hit rate limits. Wait a few seconds or add more keys.

### TLS/SLL errors

If running locally with self-signed certs, some HTTP clients may reject the connection. Use HTTP for local dev, HTTPS for production.

## License

MIT

## Contributing

1. Fork the repo
2. Create a feature branch
3. Submit a pull request

## Credits

Built for Nvidia's [API Catalog](https://build.nvidia.com/explore/discover/models).
