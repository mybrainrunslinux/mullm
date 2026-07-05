"""
Container CLI smoke tests — run against a live mullm container.

DEPRECATED: replaced by tests/test_env_setup.py which tests Python/CUDA/uv/ComfyUI.
This file requires a live server and is skipped in normal CI.

To run manually against a live server:
    MULLM_BASE_URL=http://127.0.0.1:6856 pytest tests/test_cli_container.py -v --run-container

Or inside compose:
    podman-compose -f compose.test.yml run --rm test-runner pytest tests/test_cli_container.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import httpx
import pytest

# Skip unless explicitly enabled — requires a live server on MULLM_BASE_URL
pytestmark = pytest.mark.skip(reason="Container tests require a live server. Run with --run-container or set MULLM_RUN_CONTAINER=1")

BASE = os.environ.get("MULLM_BASE_URL", "http://127.0.0.1:6856")
TIMEOUT = 30

# Server rate limit is 20 req/min → 3s gap is safe
_RATE_GAP = 3.1


def _post(content: str) -> dict:
    r = httpx.post(f"{BASE}/query", json={"content": content}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Groundtruth tier — must be instant and free
# ---------------------------------------------------------------------------

class TestGroundtruth:
    def test_pi(self):
        r = _post("what is pi")
        assert r["tier"] == "groundtruth"
        assert "3.14" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_speed_of_light(self):
        r = _post("speed of light")
        assert r["tier"] == "groundtruth"
        assert "299" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_arithmetic(self):
        r = _post("what is 2 plus 2")
        assert r["tier"] == "groundtruth"
        assert "4" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_capital_of_france(self):
        r = _post("what is the capital of France")
        assert r["tier"] == "groundtruth"
        assert "Paris" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_binary_search_complexity(self):
        r = _post("what is the time complexity of binary search")
        assert r["tier"] == "groundtruth"
        assert "log" in r["response"].lower()
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_ssh_port(self):
        r = _post("what port does ssh use")
        assert r["tier"] == "groundtruth"
        assert "22" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)

    def test_http_404(self):
        r = _post("http status 404")
        assert r["tier"] == "groundtruth"
        assert "404" in r["response"]
        assert r["cost"] == 0.0
        time.sleep(_RATE_GAP)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self):
        r = httpx.get(f"{BASE}/health", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("ok", "degraded")
        assert "version" in data

    def test_health_has_chromadb(self):
        r = httpx.get(f"{BASE}/health", timeout=10)
        data = r.json()
        assert "chromadb_available" in data

    def test_groundtruth_does_not_need_ollama(self):
        """Groundtruth tier must work even when ollama_available is false."""
        time.sleep(_RATE_GAP)
        health = httpx.get(f"{BASE}/health", timeout=10).json()
        r = _post("what is 2 plus 2")
        assert r["tier"] == "groundtruth", (
            f"Groundtruth failed even though server is {'with' if health.get('ollama_available') else 'without'} Ollama"
        )


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestResponseShape:
    def test_required_fields(self):
        time.sleep(_RATE_GAP)
        r = _post("what is pi")
        for field in ("tier", "response", "cost", "latency_ms"):
            assert field in r, f"Missing field: {field}"

    def test_cost_is_float(self):
        time.sleep(_RATE_GAP)
        r = _post("what is pi")
        assert isinstance(r["cost"], (int, float))

    def test_latency_is_positive(self):
        time.sleep(_RATE_GAP)
        r = _post("what is 2 plus 2")
        assert r["latency_ms"] > 0


# ---------------------------------------------------------------------------
# CLI subprocess (when running locally with mullm installed)
# ---------------------------------------------------------------------------

class TestCLI:
    @pytest.mark.skipif(
        os.environ.get("MULLM_BASE_URL", "").startswith("http://mullm"),
        reason="CLI subprocess not available inside container"
    )
    def test_cli_groundtruth(self):
        """mullm CLI returns groundtruth answer for pi."""
        result = subprocess.run(
            [sys.executable, "-m", "router.cli", "what is pi"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "3.14" in result.stdout or "3.14" in result.stderr

    @pytest.mark.skipif(
        os.environ.get("MULLM_BASE_URL", "").startswith("http://mullm"),
        reason="CLI subprocess not available inside container"
    )
    def test_cli_arithmetic(self):
        result = subprocess.run(
            [sys.executable, "-m", "router.cli", "what is 2 plus 2"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "4" in result.stdout or "4" in result.stderr
