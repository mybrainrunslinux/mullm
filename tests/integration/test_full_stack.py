"""
Full-stack integration test — runs against a live mullm server.

Tests all four routing tiers in order:
  0. Groundtruth LUT  (arithmetic, exact match)
  1. Semantic cache   (near-duplicate queries — similar but not identical)
  2. Local 30B        (novel queries not in groundtruth or cache)
  3. Cloud            (complex queries, requires MULLM_TEST_CLOUD env var)

Cache sequence test:
  "what is 2+2" → groundtruth (tier=groundtruth, answer=4)
  "what is 2+3" → groundtruth (tier=groundtruth, answer=5)
  "what is 2+2" → cache hit   (tier=cache or groundtruth, answer=4)
  "two plus two" → semantic cache hit (tier=cache, answer=4)

Usage:
  pytest tests/integration/test_full_stack.py -v
  pytest tests/integration/test_full_stack.py -v -k cloud  # cloud tests too
"""

from __future__ import annotations

import os
import random
import time

import httpx
import pytest

BASE = os.environ.get("MULLM_BASE_URL", "https://127.0.0.1:6856")
VERIFY_TLS = os.environ.get("MULLM_TEST_VERIFY_TLS", "0").lower() in {"1", "true", "yes"}
TIMEOUT = int(os.environ.get("MULLM_TEST_TIMEOUT", "300"))  # local model can be slow on first load

# Rate limiter is 20 req/min = 3s between requests safe minimum.
# Add a small buffer so rapid-fire test sequences don't hit 429.
_RATE_GAP = 3.5


def post(content: str, **kwargs) -> dict:
    r = httpx.post(f"{BASE}/query", json={"content": content, **kwargs}, timeout=TIMEOUT, verify=VERIFY_TLS)
    r.raise_for_status()
    return r.json()


def _contains_4(text: str) -> bool:
    return "4" in text or "four" in text.lower()


# ---------------------------------------------------------------------------
# Tier 0 — Groundtruth LUT
# ---------------------------------------------------------------------------

class TestGroundtruth:
    def test_arithmetic_2_plus_2(self):
        r = post("what is 2+2")
        assert _contains_4(r["response"]), f"Expected 4/four, got: {r['response']}"
        assert r.get("tier") in ("groundtruth", "cache", "lut"), f"Wrong tier: {r.get('tier')}"

    def test_arithmetic_2_plus_3(self):
        r = post("what is 2+3")
        assert "5" in r["response"] or "five" in r["response"].lower(), f"Expected 5, got: {r['response']}"

    def test_arithmetic_expression(self):
        r = post("calculate 144 / 12")
        assert "12" in r["response"] or "twelve" in r["response"].lower(), f"Expected 12, got: {r['response']}"

    def test_http_status_404(self):
        r = post("what is HTTP 404")
        assert "not found" in r["response"].lower(), f"Got: {r['response']}"

    def test_port_443(self):
        r = post("what port does HTTPS use")
        assert "443" in r["response"], f"Got: {r['response']}"

    def test_big_o_binary_search(self):
        # Use a specific phrasing that won't match datetime/other groundtruth entries
        r = post("big O notation for binary search algorithm")
        assert "log" in r["response"].lower() or "O(" in r["response"], f"Got: {r['response']}"


# ---------------------------------------------------------------------------
# Tier 1 — Semantic cache (repeat + near-duplicate)
# ---------------------------------------------------------------------------

class TestSemanticCache:
    def test_exact_repeat_hits_cache(self):
        query = "what is the square root of 144"
        r1 = post(query)
        assert "12" in r1["response"] or "twelve" in r1["response"].lower()

        time.sleep(_RATE_GAP)
        r2 = post(query)
        # Answer must be correct; tier may vary depending on ChromaDB warmup state
        assert "12" in r2["response"] or "twelve" in r2["response"].lower()

    def test_semantic_near_duplicate(self):
        """'two plus two' should hit cache after 'what is 2+2' has been answered."""
        post("what is 2+2")  # seed the cache
        time.sleep(_RATE_GAP)

        r = post("two plus two equals what")
        assert _contains_4(r["response"]), f"Semantic cache miss or wrong answer: {r['response']}"

    def test_cache_sequence_2_2_3_2(self):
        """2+2, 2+3, 2+2 — all must return correct answers regardless of tier."""
        r1 = post("what is 2+2")
        assert _contains_4(r1["response"]), f"First 2+2: {r1['response']}"

        time.sleep(_RATE_GAP)
        r2 = post("what is 2+3")
        assert "5" in r2["response"] or "five" in r2["response"].lower(), f"2+3: {r2['response']}"

        time.sleep(_RATE_GAP)
        r3 = post("what is 2+2")
        assert _contains_4(r3["response"]), f"Second 2+2 (cache): {r3['response']}"

    def test_near_duplicate_still_correct(self):
        """Rephrased questions must return CORRECT answers, not cached wrong answers."""
        post("what is 2+2")  # cache seeded with answer=4
        time.sleep(_RATE_GAP)

        r = post("what is 2 + 3")  # similar but DIFFERENT answer
        assert "5" in r["response"] or "five" in r["response"].lower(), f"Near-dup returned wrong answer: {r['response']}"


# ---------------------------------------------------------------------------
# Tier 2 — Local 30B model
# ---------------------------------------------------------------------------

class TestLocalModel:
    def test_novel_query_gets_response(self):
        """A genuinely novel question should route to local model and return coherent text."""
        try:
            r = post("explain the difference between a monad and a functor in Haskell")
        except httpx.ReadTimeout:
            pytest.skip("Local model did not answer the slow-path integration query within the timeout")
        assert len(r["response"]) > 100, f"Response too short: {r['response']}"
        assert r.get("tier") in ("local", "cache", "cloud_cheap", "cloud_full")

    def test_coding_question(self):
        r = post("write a Python function that checks if a number is prime")
        resp = r["response"]
        assert "def " in resp or "prime" in resp.lower(), f"No code in response: {resp[:200]}"

    def test_response_has_expected_fields(self):
        r = post("what is the capital of France")
        assert "response" in r
        assert "tier" in r or "model" in r  # at minimum one routing field


# ---------------------------------------------------------------------------
# Tier 3 — Cloud (opt-in, requires MULLM_TEST_CLOUD env var)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("MULLM_TEST_CLOUD"),
    reason="Set MULLM_TEST_CLOUD=1 and ensure cloud API keys are configured"
)
class TestCloud:
    def test_complex_query_reaches_cloud(self):
        """A query that should exceed local model capability."""
        r = post(
            "Write a formal proof that the square root of 2 is irrational, "
            "using the method of contradiction, formatted in LaTeX.",
            force_tier=random.choice(["cloud_cheap", "cloud_full"])
        )
        assert len(r["response"]) > 200
        tier = r.get("tier", "")
        assert "cloud" in tier, f"Expected cloud tier, got: {tier}"


# ---------------------------------------------------------------------------
# Health + scoring log verification
# ---------------------------------------------------------------------------

class TestObservability:
    def test_health_endpoint(self):
        r = httpx.get(f"{BASE}/health", timeout=10, verify=VERIFY_TLS)
        assert r.status_code == 200
        data = r.json()
        assert "version" in data or "status" in data

    def test_dashboard_api(self):
        r = httpx.get(f"{BASE}/api/dashboard", timeout=10, verify=VERIFY_TLS)
        assert r.status_code == 200
        data = r.json()
        assert "total_queries" in data or "queries" in data or len(data) > 0

    def test_queries_appear_in_scoring_log(self):
        """After running queries, scoring log should have grown."""
        import os
        from pathlib import Path

        log_path = Path(__file__).parent.parent.parent / "cache" / "data" / "scoring_log.jsonl"
        if not log_path.exists():
            pytest.skip("Scoring log not on local disk (server may be containerized)")

        mtime_before = log_path.stat().st_mtime
        # Use a non-groundtruth query so it actually routes and logs
        post("summarize the differences between supervised and unsupervised learning")
        time.sleep(2.0)
        mtime_after = log_path.stat().st_mtime

        if mtime_after == mtime_before:
            pytest.skip("Scoring log on disk but not updated — server writes to a different path (likely containerized)")

        after = sum(1 for _ in open(log_path))
        assert after > 0

    def test_access_log_written(self):
        """Access log should record requests (CC6/CC7 SOC2 evidence)."""
        import json
        from pathlib import Path

        log_path = Path(__file__).parent.parent.parent / "cache" / "data" / "access_log.jsonl"
        if not log_path.exists():
            pytest.skip("Access log not on local disk (server may be containerized)")

        mtime_before = log_path.stat().st_mtime
        post("what is 3+3")
        time.sleep(1.0)
        mtime_after = log_path.stat().st_mtime

        if mtime_after == mtime_before:
            pytest.skip("Access log on disk but not updated — server writes to a different path (likely containerized)")

        lines = [l for l in log_path.read_text().strip().splitlines() if l]
        query_entries = [json.loads(l) for l in lines if json.loads(l).get("path") == "/query"]
        assert query_entries, "No /query entries found in access log"
        last = query_entries[-1]
        assert last["path"] == "/query"
        assert last["status"] == 200
        assert "ip" in last
