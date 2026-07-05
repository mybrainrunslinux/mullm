// Groundtruth short-circuit performance tests — TDD for S31 P1
// These queries MUST resolve via groundtruth (<50ms), never hitting a model
const { test, expect } = require("@playwright/test");

const BASE = process.env.MULLM_URL || "https://localhost:8100";

async function queryAndMeasure(request, content) {
  const resp = await request.post(`${BASE}/query`, {
    data: { content, source: "api", session_id: "perf-test" },
    ignoreHTTPSErrors: true,
  });
  expect(resp.ok()).toBeTruthy();
  const data = await resp.json();
  return data;
}

test.describe("Groundtruth Short-Circuit Performance", () => {
  test.use({ ignoreHTTPSErrors: true });

  // Date/time queries — must be instant
  test("date query resolves <50ms via realtime", async ({ request }) => {
    const data = await queryAndMeasure(request, "what's today's date?");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  test("time query resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "what time is it?");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  test("time in city resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "time in tokyo");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Identity queries
  test("identity query resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "who are you?");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Groundtruth extras — Big-O, HTTP codes, etc.
  test("Big-O query resolves <50ms via groundtruth", async ({ request }) => {
    const data = await queryAndMeasure(request, "hashmap big o complexity");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  test("HTTP status code resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "what is http 404");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Capital city lookup
  test("capital city resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "capital of france");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Math evaluation
  test("math eval resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "what is 2+2");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Eclipse query
  test("eclipse query resolves <50ms", async ({ request }) => {
    const data = await queryAndMeasure(request, "next solar eclipse");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
    expect(data.cost).toBe(0);
  });

  // Batch latency: 10 groundtruth queries should all be <50ms
  test("batch: 10 groundtruth queries all under 50ms", async ({ request }) => {
    const queries = [
      "what's today's date?",
      "what time is it?",
      "time in london",
      "who are you?",
      "capital of japan",
      "what is http 500",
      "hashmap time complexity",
      "next lunar eclipse",
      "what is 5*5",
      "time in new york",
    ];
    const results = await Promise.all(queries.map((q) => queryAndMeasure(request, q)));
    for (let i = 0; i < results.length; i++) {
      console.log(`  ${queries[i].padEnd(30)} → ${results[i].total_latency_ms}ms (${results[i].model_used})`);
      expect(results[i].model_used).toBe("realtime");
      expect(results[i].total_latency_ms).toBeLessThan(50);
      expect(results[i].cost).toBe(0);
    }
  });
});
