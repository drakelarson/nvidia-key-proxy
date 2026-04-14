#!/usr/bin/env python3
"""
Nvidia API Key Rotation Proxy
Hardcoded API keys - cycles through all keys on 429 before giving up.
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import threading
import time
import sys

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

key_lock = threading.Lock()
key_index = [0]  # current key index

total_requests = [0]
total_429s = [0]


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
    print(f"[PROXY] 429 → rotating to key {new_idx + 1}/{len(API_KEYS)} (total 429s: {total_429s[0]})")
    return new_idx


def build_upstream_headers(req_headers, key):
    headers = {}
    for k, v in req_headers.items():
        if k.lower() == "authorization":
            headers[k] = f"Bearer {key}"
        elif k.lower() not in ("host", "connection"):
            headers[k] = v
    return headers


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(f"[PROXY] {fmt % args}")

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

        url = f"{BASE_URL}{self.path}"

        # Track which keys we've tried for this request
        tried_keys = set()
        current_idx = get_key_index()

        while True:
            key = API_KEYS[current_idx]
            tried_keys.add(current_idx)

            print(f"[PROXY] {method} {self.path} → key={current_idx + 1}/{len(API_KEYS)}")

            headers = build_upstream_headers(dict(self.headers), key)
            req = urllib.request.Request(url, data=body, headers=headers, method=method)

            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    # Get headers but don't read body yet
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    
                    # Update global key index on success
                    set_key_index(current_idx)

                    # Send response headers first
                    self.send_response(resp.status)
                    for k, v in resp_headers.items():
                        if k.lower() not in ("transfer-encoding", "connection", "keep-alive"):
                            self.send_header(k, v)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    # Stream response body in chunks
                    total_bytes = 0
                    chunk_count = 0
                    try:
                        while True:
                            chunk = resp.read(8192)  # 8KB chunks
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()  # Flush each chunk immediately
                            total_bytes += len(chunk)
                            chunk_count += 1
                    except (BrokenPipeError, ConnectionResetError) as e:
                        print(f"[PROXY] Client disconnected after {chunk_count} chunks ({total_bytes} bytes): {e}", flush=True)
                        return

                    duration = int(time.time() * 1000) - start_ms
                    print(f"[PROXY] ← {resp.status} ({duration}ms, {chunk_count} chunks, {total_bytes} bytes)")
                    return

            except urllib.error.HTTPError as e:
                resp_body = e.read() if e.fp else b""
                resp_headers = {k: v for k, v in e.headers.items()} if e.headers else {}

                # 429 → try next key (circular)
                if e.code == 429:
                    print(f"[PROXY] 429 from key {current_idx + 1}")
                    total_429s[0] += 1

                    # Move to next key (circular)
                    next_idx = (current_idx + 1) % len(API_KEYS)

                    # If we've tried all keys, give up
                    if next_idx in tried_keys:
                        print(f"[PROXY] All {len(API_KEYS)} keys exhausted, returning 429")
                        self.send_response(429)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": "All API keys rate limited",
                            "keys_tried": len(tried_keys)
                        }).encode())
                        print(f"[PROXY] ← 429 (all keys exhausted, {int(time.time() * 1000) - start_ms}ms)")
                        return

                    # Rotate to next key and retry
                    current_idx = rotate_key()
                    continue

                # Non-429 error → return as-is
                self.send_response(e.code)
                for k, v in resp_headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "keep-alive"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp_body)
                print(f"[PROXY] ← {e.code} ({int(time.time() * 1000) - start_ms}ms)")
                return

            except Exception as e:
                print(f"[PROXY] ERROR: {e}")
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
    print(f"[PROXY] Listening on http://0.0.0.0:{PORT}")
    print(f"[PROXY] {len(API_KEYS)} API key(s) loaded")
    print(f"[PROXY] Circular key rotation + streaming enabled")
    with ThreadedHTTPServer(("0.0.0.0", PORT), ProxyHandler) as httpd:
        httpd.serve_forever()
