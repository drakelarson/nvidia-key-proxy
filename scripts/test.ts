/**
 * Test script for Nvidia Key Proxy
 * Tests both streaming and non-streaming chat completion requests
 */

const PROXY_URL = "http://localhost:3090";
const MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"; // Default model, can override

interface TestResult {
  name: string;
  status: number;
  success: boolean;
  duration: number;
  error?: string;
  truncatedResponse?: string;
}

async function waitForProxy(maxRetries = 10): Promise<boolean> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const resp = await fetch(`${PROXY_URL}/v1/models`, {
        method: "GET",
        headers: { "Authorization": "Bearer dummy" },
      });
      if (resp.ok) return true;
    } catch {
      await new Promise(r => setTimeout(r, 500));
    }
  }
  return false;
}

async function testNonStreaming(): Promise<TestResult> {
  const start = Date.now();
  try {
    const resp = await fetch(`${PROXY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy",
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: "user", content: "Say 'hello world' in exactly 3 words" }],
        max_tokens: 50,
        temperature: 0.7,
      }),
    });

    const duration = Date.now() - start;
    const data = await resp.json();

    if (!resp.ok) {
      return { name: "Non-Streaming", status: resp.status, success: false, duration, error: JSON.stringify(data) };
    }

    const content = data.choices?.[0]?.message?.content || "";
    return {
      name: "Non-Streaming",
      status: resp.status,
      success: true,
      duration,
      truncatedResponse: content.slice(0, 100),
    };
  } catch (err: any) {
    return { name: "Non-Streaming", status: 0, success: false, duration: Date.now() - start, error: err.message };
  }
}

async function testStreaming(): Promise<TestResult> {
  const start = Date.now();
  try {
    const resp = await fetch(`${PROXY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy",
        "Accept": "text/event-stream",
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: "user", content: "Count from 1 to 5" }],
        max_tokens: 50,
        stream: true,
      }),
    });

    const duration = Date.now() - start;

    if (!resp.ok) {
      const data = await resp.json();
      return { name: "Streaming", status: resp.status, success: false, duration, error: JSON.stringify(data) };
    }

    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let fullContent = "";
    let chunkCount = 0;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        fullContent += text;
        chunkCount++;
      }
    } finally {
      reader.releaseLock();
    }

    return {
      name: "Streaming",
      status: resp.status,
      success: true,
      duration,
      truncatedResponse: `Received ${chunkCount} chunks, ~${fullContent.length} chars`,
    };
  } catch (err: any) {
    return { name: "Streaming", status: 0, success: false, duration: Date.now() - start, error: err.message };
  }
}

async function testKeyRotation(): Promise<TestResult> {
  const start = Date.now();
  try {
    // Fire 5 concurrent requests to potentially trigger 429 rotation
    const promises = Array(5).fill(null).map((_, i) =>
      fetch(`${PROXY_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer dummy",
        },
        body: JSON.stringify({
          model: MODEL,
          messages: [{ role: "user", content: `Request ${i + 1}` }],
          max_tokens: 10,
        }),
      }).then(r => r.json())
    );

    const results = await Promise.all(promises);
    const has429 = results.some(r => r.error?.includes("429") || r.code === 429);
    const allSuccess = results.every(r => !r.error);

    return {
      name: "Key Rotation",
      status: 200,
      success: !has429 && allSuccess,
      duration: Date.now() - start,
      truncatedResponse: `5 concurrent requests: allSuccess=${allSuccess}, had429=${has429}`,
    };
  } catch (err: any) {
    return { name: "Key Rotation", status: 0, success: false, duration: Date.now() - start, error: err.message };
  }
}

async function main() {
  console.log("=".repeat(60));
  console.log("NVIDIA KEY PROXY TEST SUITE");
  console.log("=".repeat(60));
  console.log();

  console.log("[1/3] Waiting for proxy to be ready...");
  const ready = await waitForProxy();
  if (!ready) {
    console.error("ERROR: Proxy not responding at", PROXY_URL);
    process.exit(1);
  }
  console.log("      Proxy is ready!\n");

  console.log("[2/3] Running non-streaming test...");
  const nonStream = await testNonStreaming();
  console.log(`      Status: ${nonStream.status} | Duration: ${nonStream.duration}ms | Success: ${nonStream.success}`);
  if (nonStream.error) console.log(`      Error: ${nonStream.error}`);
  if (nonStream.truncatedResponse) console.log(`      Response: ${nonStream.truncatedResponse}`);
  console.log();

  console.log("[3/3] Running streaming test...");
  const stream = await testStreaming();
  console.log(`      Status: ${stream.status} | Duration: ${stream.duration}ms | Success: ${stream.success}`);
  if (stream.error) console.log(`      Error: ${stream.error}`);
  if (stream.truncatedResponse) console.log(`      Response: ${stream.truncatedResponse}`);
  console.log();

  // Key rotation test - may trigger 429 on single key
  console.log("Bonus: Key rotation stress test (5 concurrent)...");
  const rotation = await testKeyRotation();
  console.log(`      Status: ${rotation.status} | Duration: ${rotation.duration}ms | Success: ${rotation.success}`);
  if (rotation.truncatedResponse) console.log(`      Result: ${rotation.truncatedResponse}`);
  console.log();

  console.log("=".repeat(60));
  const allPassed = nonStream.success && stream.success;
  console.log(allPassed ? "ALL TESTS PASSED" : "SOME TESTS FAILED");
  console.log("=".repeat(60));

  process.exit(allPassed ? 0 : 1);
}

main();
