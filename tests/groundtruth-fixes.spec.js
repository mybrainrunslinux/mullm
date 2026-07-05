const { test, expect } = require("@playwright/test");

const baseURL = process.env.MULLM_URL || "https://127.0.0.1:8100";

test.describe("Groundtruth and regression fixes", () => {
  test.use({ ignoreHTTPSErrors: true });

  test("groundtruth fires even with skip_cache:true", async ({ request }) => {
    const response = await request.post(`${baseURL}/query`, {
      data: { content: "What is the capital of France?", skip_cache: true },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.tier_used).toBe("local");
    expect(data.model_used).toBe("realtime");
    expect(data.total_latency_ms).toBeLessThan(50);
  });

  test("anagram detection works correctly", async ({ request }) => {
    const response = await request.post(`${baseURL}/query`, {
      data: { content: "Is listen an anagram of silent? Answer yes or no.", skip_cache: true },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.response.toLowerCase()).toContain("yes");
    expect(data.model_used).toBe("realtime");
  });

  test("arithmetic groundtruth with trailing noise", async ({ request }) => {
    const response = await request.post(`${baseURL}/query`, {
      data: { content: "What is 17 × 23? Just the number.", skip_cache: true },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.model_used).toBe("realtime");
    expect(data.response).toContain("391");
  });

  test("sort numbers groundtruth", async ({ request }) => {
    const response = await request.post(`${baseURL}/query`, {
      data: { content: "Sort these numbers: 7, 2, 9, 1, 5. Just the sorted list.", skip_cache: true },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.model_used).toBe("realtime");
    expect(data.response).toMatch(/1.*2.*5.*7.*9/);
  });

  test("long queries are NOT intercepted by groundtruth", async ({ request }) => {
    const response = await request.post(`${baseURL}/query`, {
      data: {
        content:
          "Strategic analysis: what are the key architectural weaknesses of local-first LLM routers and what would make a competitor definitively better in terms of routing accuracy latency and multi-modal support?",
        skip_cache: true,
      },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    // Long queries must NOT hit realtime groundtruth (would return nonsense)
    expect(data.model_used).not.toBe("realtime");
  });

  test("games page has zero 404s @games", async ({ page }) => {
    const errors404 = [];
    page.on("response", (resp) => {
      if (resp.status() === 404) errors404.push(resp.url());
    });
    await page.goto(`${baseURL}/games`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000); // let lazy requests fire
    expect(errors404).toHaveLength(0);
  });

  test("tierbench content field — no all-error results", async ({ request }) => {
    const response = await request.post(`${baseURL}/api/bench/run`, {
      params: { mode: "tier", limit: 3 },
    });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(Array.isArray(data.results)).toBeTruthy();
    const errored = data.results.filter((r) => r.detail && r.detail.includes("HTTP 422"));
    expect(errored).toHaveLength(0);
  });
});
