"""Paid smoke: pytest tests/test_frontier_live.py --grep=@spend -s.

Eight sequential calls, no retries, 1024 output tokens each; standard catalog
worst-case reservation is below $0.25 total for these short fixed prompts.
No user content is sent. A failure is reported, never silently substituted.
"""
import json

import pytest

from router import cloud
from router.frontier_models import FRONTIER_MODELS

pytestmark = pytest.mark.spend


@pytest.fixture(autouse=True)
async def close_http_client():
    yield
    await cloud.close_client()



@pytest.mark.parametrize("model", list(FRONTIER_MODELS))
async def test_frontier_live(model):
    provider = FRONTIER_MODELS[model][0]
    if not cloud._provider_key(provider):
        pytest.fail(f"Missing credential for {provider}")
    fn = cloud._raw_openai if provider == "openai" else cloud._raw_anthropic
    try:
        result = await fn("Reply with exactly the word READY.", model, max_tokens=1024)
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        detail = response.json().get("error", {}).get("message", "")[:300] if response is not None else ""
        pytest.fail(f"{model}: {type(exc).__name__}, HTTP {status}: {detail}", pytrace=False)
    print(json.dumps({"model": model, "tokens_in": result["tokens_in"],
                      "tokens_out": result["tokens_out"], "cost": result["cost"],
                      "nonempty": bool(result["text"].strip())}))
    assert result["text"].strip(), f"{model} returned no visible text"
    assert "READY" in result["text"].upper()
