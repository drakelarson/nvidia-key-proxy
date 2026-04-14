/**
 * Nvidia API Key Rotation Proxy
 * Hardcoded API keys - first key is primary, others are fallbacks on 429.
 */
const BASE_URL = "https://integrate.api.nvidia.com";
const PORT = 3090;

// ─── API KEYS ────────────────────────────────────────────────────────────────
// Add 2-5 keys here. Keys are rotated in order when a 429 is received.
const API_KEYS = [
  "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",
  // "nvapi-AddSecondKeyHere",
  // "nvapi-AddThirdKeyHere",
];

let keyIndex = 0;
let totalRequests = 0;
let total429s = 0;

function getKey() {
  return API_KEYS[keyIndex];
}

function rotateKey() {
  keyIndex = (keyIndex + 1) % API_KEYS.length;
  total429s++;
  console.log(`[PROXY] 429 on key ${keyIndex} → rotating to key index ${keyIndex}/${API_KEYS.length} (total 429s: ${total429s})`);
}

async function handleRequest(req, keyOverride = null) {
  const url = new URL(req.url);
  const upstreamPath = url.pathname;
  const isStreaming = url.searchParams.get("stream") === "true" || 
    req.headers.get("content-type")?.includes("text/event-stream");

  // Determine which key to use
  const key = keyOverride || getKey();

  // Build upstream headers — replace Authorization, keep everything else
  const upstreamHeaders = {};
  for (const [k, v] of req.headers.entries()) {
    if (k.toLowerCase() === "authorization") {
      upstreamHeaders[k] = `Bearer ${key}`;
    } else {
      upstreamHeaders[k] = v;
    }
  }

  // Read body
  let body = null;
  if (["POST", "PUT", "PATCH"].includes(req.method)) {
    body = await req.text();
  }

  const upstreamUrl = `${BASE_URL}${upstreamPath}`;

  const upstreamResponse = await fetch(upstreamUrl, {
    method: req.method,
    headers: upstreamHeaders,
    body,
  });

  // 429 → rotate to next key and retry once
  if (upstreamResponse.status === 429) {
    rotateKey();
    if (API_KEYS.length > 1) {
      const retryKey = getKey();
      console.log(`[PROXY] Retrying with key index ${keyIndex}`);
      const retryHeaders = { ...upstreamHeaders, "Authorization": `Bearer ${retryKey}` };
      const retryResponse = await fetch(upstreamUrl, {
        method: req.method,
        headers: retryHeaders,
        body,
      });

      if (retryResponse.status === 429) {
        rotateKey(); // Move to next for next request
      }

      // Stream back the successful response
      if (retryResponse.headers.get("content-type")?.includes("text/event-stream")) {
        return new Response(retryResponse.body, {
          status: retryResponse.status,
          headers: buildCorsHeaders(retryResponse.headers),
        });
      }

      const text = await retryResponse.text();
      return new Response(text, {
        status: retryResponse.status,
        headers: { ...buildCorsHeaders(retryResponse.headers), "Content-Type": retryResponse.headers.get("Content-Type") || "application/json" },
      });
    }
  }

  // Non-429 response — stream or return
  if (isStreaming) {
    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: buildCorsHeaders(upstreamResponse.headers),
    });
  }

  const text = await upstreamResponse.text();
  return new Response(text, {
    status: upstreamResponse.status,
    headers: { ...buildCorsHeaders(upstreamResponse.headers), "Content-Type": upstreamResponse.headers.get("Content-Type") || "application/json" },
  });
}

function buildCorsHeaders(upstreamHeaders) {
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "*",
  };
  // Pass through relevant upstream headers
  const passThrough = ["content-type", "x-request-id"];
  for (const k of passThrough) {
    const v = upstreamHeaders.get(k);
    if (v) headers[k] = v;
  }
  return headers;
}

// ─── SERVER ──────────────────────────────────────────────────────────────────
const server = Bun.serve({
  port: PORT,
  hostname: "0.0.0.0",

  async fetch(req) {
    totalRequests++;
    const start = Date.now();

    // Handle CORS preflight
    if (req.method === "OPTIONS") {
      return new Response(null, {
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    console.log(`[PROXY] ${req.method} ${new URL(req.url).pathname} → key=${keyIndex + 1}/${API_KEYS.length}`);

    try {
      const response = await handleRequest(req);
      console.log(`[PROXY] ← ${response.status} (${Date.now() - start}ms)`);
      return response;
    } catch (err) {
      console.error(`[PROXY] ERROR: ${err.message}`);
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
});

console.log(`[PROXY] Listening on http://0.0.0.0:${PORT}`);
console.log(`[PROXY] ${API_KEYS.length} API key(s) loaded`);
