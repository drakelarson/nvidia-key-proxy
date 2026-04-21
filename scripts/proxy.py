#!/usr/bin/env python3
"""
Nvidia API Key Rotation Proxy - HTTP/2 Streaming Support
Uses httpx for HTTP/2 support with proper streaming.
"""
import http.server
import socketserver
import json
import threading
import time
import sys
import httpx

# Unbuffered stdout for proper logging
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_URL = "https://integrate.api.nvidia.com"

# Add 2-5 API keys here. Keys are rotated circularly when a 429 is received.
API_KEYS = [
    "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",
    "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",
    # "nvapi-ThirdKeyHere",
]

PORT = 3090

# Shared HTTP/2 client (more efficient connection reuse)
http_client = None
client_lock = threading.Lock()

key_lock = threading.Lock()
key_index = [0]

total_requests = [0]
total_429s = [0]


def get_client():
    """Get or create HTTP/2 client"""
    global http_client
    with client_lock:
        if http_client is None:
            http_client = httpx.Client(http2=True, timeout=300.0, follow_redirects=True)
        return http_client


def get_key_index():
    with key_lock:
        return key_index[0]


def set_key_index(idx):
    with key_lock:
        key_index[0] = idx


def rotate_key():
    with key_lock:
        key_index[0] = (key_index[0] + 1) % len(API_KEYS)
        total_429s[0] += 1
        new_idx = key_index[0]
    print(f"[PROXY] 429 → rotating to key {new_idx + 1}/{len(API_KEYS)} (total 429s: {total_429s[0]})", flush=True)
    return new_idx


def build_upstream_headers(req_headers, key):
    headers = {}
    for k, v in req_headers.items():
        if k.lower() == "authorization":
            headers[k] = f"Bearer {key}"
        elif k.lower() not in ("host", "connection", "content-length"):
            headers[k] = v
    return headers


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(f"[PROXY] {fmt % args}", flush=True)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def handle_proxy(self, method):
        total_requests[0] += 1
        start_ms = int(time.time() * 1000)

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Parse body and fix max_tokens for z-ai/glm models
        if body:
            try:
                parsed_body = json.loads(body)
                if not parsed_body.get("max_tokens"):
                    parsed_body["max_tokens"] = 32768
                # Auto-disable thinking for moonshotai/kimi-k2.5 to prevent token budget truncation
                if parsed_body.get("model") == "moonshotai/kimi-k2.5" and not parsed_body.get("chat_template_kwargs"):
                    parsed_body["chat_template_kwargs"] = {"thinking": False}
                    print(f"[PROXY] Auto-disabled thinking for moonshotai/kimi-k2.5", flush=True)
                body = json.dumps(parsed_body).encode()
            except:
                pass

        url = f"{BASE_URL}{self.path}"

        tried_keys = set()
        current_idx = get_key_index()
        client = get_client()

        while True:
            key = API_KEYS[current_idx]
            tried_keys.add(current_idx)

            print(f"[PROXY] {method} {self.path} → key={current_idx + 1}/{len(API_KEYS)} (HTTP/2)", flush=True)

            headers = build_upstream_headers(dict(self.headers), key)

            try:
                # Use streaming request
                with client.stream(method, url, headers=headers, content=body) as resp:
                    # CHECK FOR 429 BEFORE STREAMING
                    if resp.status_code == 429:
                        print(f"[PROXY] 429 from key {current_idx + 1}", flush=True)
                        total_429s[0] += 1
                        
                        # Read error body for potential retry
                        resp.read()  # Consume the response
                        
                        next_idx = (current_idx + 1) % len(API_KEYS)
                        
                        if next_idx in tried_keys:
                            print(f"[PROXY] All {len(API_KEYS)} keys exhausted, returning 429", flush=True)
                            self.send_response(429)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                "error": "All API keys rate limited",
                                "keys_tried": len(tried_keys)
                            }).encode())
                            print(f"[PROXY] ← 429 (all keys exhausted, {int(time.time() * 1000) - start_ms}ms)", flush=True)
                            return
                        
                        # Rotate to next key and retry
                        current_idx = rotate_key()
                        continue
                    
                    # Send response headers
                    self.send_response(resp.status_code)
                    
                    # Forward response headers
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "connection", "keep-alive", "content-encoding"):
                            self.send_header(k, v)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    # Stream body in chunks
                    total_bytes = 0
                    chunk_count = 0
                    try:
                        for chunk in resp.iter_bytes(chunk_size=4096):  # 4KB chunks for more frequent flushes
                            if chunk:
                                self.wfile.write(chunk)
                                self.wfile.flush()
                                total_bytes += len(chunk)
                                chunk_count += 1
                    except (BrokenPipeError, ConnectionResetError) as e:
                        print(f"[PROXY] Client disconnected after {chunk_count} chunks ({total_bytes} bytes): {e}", flush=True)
                        return

                    # Update key index on success
                    set_key_index(current_idx)

                    duration = int(time.time() * 1000) - start_ms
                    print(f"[PROXY] ← {resp.status_code} ({duration}ms, {chunk_count} chunks, {total_bytes} bytes)", flush=True)
                    return

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors
                if e.response.status_code == 429:
                    print(f"[PROXY] 429 from key {current_idx + 1}", flush=True)
                    total_429s[0] += 1

                    next_idx = (current_idx + 1) % len(API_KEYS)

                    if next_idx in tried_keys:
                        print(f"[PROXY] All {len(API_KEYS)} keys exhausted, returning 429", flush=True)
                        self.send_response(429)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": "All API keys rate limited",
                            "keys_tried": len(tried_keys)
                        }).encode())
                        print(f"[PROXY] ← 429 (all keys exhausted, {int(time.time() * 1000) - start_ms}ms)", flush=True)
                        return

                    current_idx = rotate_key()
                    continue

                # Non-429 error
                resp_body = e.response.content
                self.send_response(e.response.status_code)
                for k, v in e.response.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "keep-alive"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp_body)
                print(f"[PROXY] ← {e.response.status_code} ({int(time.time() * 1000) - start_ms}ms)", flush=True)
                return

            except Exception as e:
                print(f"[PROXY] ERROR: {e}", flush=True)
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

    def do_GET(self):
        self.handle_proxy("GET")

    def do_POST(self):
        self.handle_proxy("POST")

    def do_PUT(self):
        self.handle_proxy("PUT")

    def do_PATCH(self):
        self.handle_proxy("PATCH")

    def do_DELETE(self):
        self.handle_proxy("DELETE")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"[PROXY] Listening on http://0.0.0.0:{PORT}", flush=True)
    print(f"[PROXY] {len(API_KEYS)} API key(s) loaded", flush=True)
    print(f"[PROXY] HTTP/2 + streaming enabled (httpx)", flush=True)
    with ThreadedHTTPServer(("0.0.0.0", PORT), ProxyHandler) as httpd:
        httpd.serve_forever()
