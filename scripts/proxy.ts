/**
 * Nvidia API Key Rotation Proxy
 * Hardcoded API keys - edit KEYS array to add/remove keys.
 */
const KEYS = [
  "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",
  // Add more keys here
];

const BASE_URL = "https://integrate.api.nvidia.com/v1";
const PORT = 3090;

let keyIndex = 0;
let totalRequests = 0;
let total429s = 0;

function getKey() {
  return KEYS[keyIndex];
}

function rotateKey() {
  const old = keyIndex;
  keyIndex = (keyIndex + 1) % KEYS.length;
  total429s++;
  console.log(`[PROXY] Key ${old + 1} got 429, rotating to key ${keyIndex + 1}/${KEYS.length}`);
  return getKey();
}

async function proxyRequest(path, method, headers, body, stream) {
  let attempts = 0;
  const maxAttempts = KEYS.length * 2; // Allow retry per key

  while (attempts < maxAttempts) {
    const upstreamHeaders = { ...headers, "Authorization": `Bearer ${getKey()}` };
    delete upstreamHeaders["host"];
    delete upstreamHeaders["content-length"];

    try {
      const upstreamResp = await fetch(`${BASE_URL}${path}`, {
        method,
        headers: upstreamHeaders,
        body: body || undefined,
      });

      totalRequests++;

      if (upstreamResp.status === 429) {
        rotateKey();
        attempts++;
        if (attempts >= maxAttempts) {
          return { status: 429, headers: {}, body: null, error: "All keys rate limited" };
        }
        continue;
      }

      if (stream && upstreamResp.body) {
        const decoder = new TextDecoder();
        async function* streamGen() {
          const reader = upstreamResp.body.getReader();
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              yield decoder.decode(value, { stream: true });
            }
          } finally {
            reader.releaseLock();
          }
        }
        return {
          status: upstreamResp.status,
          headers: Object.fromEntries(upstreamResp.headers.entries()),
          body: streamGen(),
        };
      }

      const text = await upstreamResp.text();
      return {
        status: upstreamResp.status,
        headers: Object.fromEntries(upstreamResp.headers.entries()),
        body: text,
      };

    } catch (err) {
      return { status: 502, headers: {}, body: null, error: err.message };
    }
  }
}

async function handler(req) {
  const url = new URL(req.url);
  const path = url.pathname;

  if (!path.startsWith("/v1/")) {
    return new Response(JSON.stringify({ error: "Proxy only handles /v1/* routes" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const method = req.method;
  const headers = {};
  req.headers.forEach((v, k) => headers[k] = v);

  const bodyStr = req.body ? await req.text() : null;
  const isStreaming = 
    headers["accept"]?.includes("text/event-stream") || 
    (bodyStr && JSON.parse(bodyStr || "{}").stream === true);

  console.log(`[PROXY] ${method} ${path} stream=${isStreaming} key=${keyIndex + 1}/${KEYS.length}`);

  const result = await proxyRequest(path, method, headers, bodyStr, isStreaming);

  if (result.error && !result.body) {
    return new Response(JSON.stringify({ error: result.error }), {
      status: result.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (result.body && typeof result.body !== "string") {
    const stream = new ReadableStream({
      async start(controller) {
        const encoder = new TextEncoder();
        try {
          for await (const chunk of result.body) {
            controller.enqueue(encoder.encode(chunk));
          }
        } catch (e) {
          console.error("[PROXY] Stream error:", e);
        } finally {
          controller.close();
        }
      },
    });
    return new Response(stream, { status: result.status, headers: result.headers });
  }

  return new Response(result.body, { status: result.status, headers: result.headers });
}

const server = Bun.serve({ port: PORT, fetch: handler });
console.log(`[PROXY] Listening on http://0.0.0.0:${PORT}`);
console.log(`[PROXY] ${KEYS.length} API key(s) loaded`);
