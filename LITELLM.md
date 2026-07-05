# Alternative Router / Proxy Support Plan

## What vLLM Is (and Current Status)

vLLM is a high-throughput inference server you self-host. It serves any HuggingFace model
(Llama 3, Mistral, Qwen, DeepSeek, etc.) behind an OpenAI-compatible `/v1/chat/completions`
endpoint. In mullm it is **already wired up** behind the `VLLM` tier:

- Set `VLLM_BASE_URL=http://your-box:8000` and `VLLM_MODEL=your-model-name` in env
- The `vllm` force_tier routes through `execute_tier_vllm()` in `router/tiers.py`
- Falls back to `local_multi` if `VLLM_BASE_URL` is unset
- Health check: `GET /api/vllm/health`

**To test it with the 3090 box:**
```
VLLM_BASE_URL=http://192.168.x.x:8000 VLLM_MODEL=deepseek-coder-v2-lite mullm --query "..."
# or in PLAN.md tasks: force_tier: vllm
```

vLLM on a 3090 (24 GB) comfortably runs 7–14B models at full speed. For 30–70B you'd use
quantized (GGUF/AWQ) variants, or stay on Ollama for those. vLLM is faster than Ollama for
batched/parallel requests — exactly what the orchestrator fires.

---

## LiteLLM

LiteLLM is a proxy that normalizes 100+ providers (Anthropic, OpenAI, Gemini, Cohere,
Replicate, Bedrock, Azure, Mistral, Groq, etc.) to a single OpenAI-compatible endpoint.
You run one server, point mullm at it, and the routing lives in LiteLLM's config.

### Why it's interesting for mullm

- **Zero new provider code in mullm.** Everything in `router/cloud.py` that calls
  `anthropic.messages.create` / `openai.chat.completions.create` / etc. would collapse into
  one HTTP call to the LiteLLM proxy.
- **Budget routing.** LiteLLM has a `router` mode that tracks per-model spend and falls back
  automatically — complements mullm's daily budget cap.
- **Caching.** LiteLLM has built-in semantic cache (Redis / in-memory) — could offload
  mullm's cache tier to it.
- **Rate limit handling.** Automatic retry with exponential backoff across providers.
- **Cost lookup.** LiteLLM maintains a live model cost table — this is the pricing cache we
  discussed. No need to build it from scratch.

### Integration path

**Option A — LiteLLM as a drop-in backend (recommended first step)**

1. Run LiteLLM proxy locally: `litellm --config litellm_config.yaml --port 4000`
2. Add `LITELLM_BASE_URL=http://localhost:4000` to mullm env
3. In `router/cloud.py` add a `call_litellm(model, messages, ...)` function that POSTs to
   `{LITELLM_BASE_URL}/v1/chat/completions` with an OpenAI-format body
4. Map mullm's tier → model string as LiteLLM expects:
   - `cloud_cheap` → `"haiku"` → LiteLLM routes to `claude-haiku-4-5-20251001`
   - `cloud_full`  → `"sonnet"` → LiteLLM routes to `claude-sonnet-4-20250514`
   - `cloud_power` → `"opus"`   → LiteLLM routes to `claude-opus-4-7`
5. LiteLLM config controls the actual model IDs — mullm stops caring about vendor-specific
   client libraries for cloud models.

**Option B — LiteLLM replaces cloud.py entirely**

More aggressive: delete `call_anthropic()`, `call_openai()`, `call_gemini()` in cloud.py and
replace with a single `call_via_litellm()`. Clean, but one more service to keep running.

### litellm_config.yaml skeleton

```yaml
model_list:
  - model_name: haiku
    litellm_params:
      model: claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: sonnet
    litellm_params:
      model: claude-sonnet-4-20250514
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: opus
    litellm_params:
      model: claude-opus-4-7           # update when confirmed
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: gpt-mini
    litellm_params:
      model: gpt-4.1-mini
      api_key: os.environ/OPENAI_API_KEY

  - model_name: gemini-flash
    litellm_params:
      model: gemini/gemini-2.5-flash
      api_key: os.environ/GEMINI_API_KEY

router_settings:
  routing_strategy: cost-based-routing   # cheapest available first
  redis_host: localhost                   # enable shared cache
  redis_port: 6379

litellm_settings:
  success_callback: ["langfuse"]          # optional observability
  cache: true
  cache_params:
    type: redis
```

---

## OpenRouter

OpenRouter is a hosted meta-router: one API key, access to 200+ models from every major
provider. No self-hosting. Pricing is public and queryable via their API.

### Why useful

- **Model shopping.** One call to `https://openrouter.ai/api/v1/models` returns current
  per-token prices for every model. This is the daily price cache we discussed — free, no
  scraping needed.
- **Fallback pool.** If Anthropic rate-limits or has an outage, OpenRouter can route the
  same `claude-sonnet` request through their allocation.
- **Free tier.** Some models are free (Llama 3.3 70B, Qwen 2.5 72B, Mistral 7B via OpenRouter).

### Integration path

OpenRouter speaks OpenAI wire format. In `router/cloud.py`:

```python
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

async def call_openrouter(model: str, messages: list, **kwargs):
    """model = OpenRouter model string, e.g. 'anthropic/claude-sonnet-4'"""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": "https://boilingfroggames.com",
            },
            json={"model": model, "messages": messages, **kwargs},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
```

### Dynamic pricing cache via OpenRouter

```python
# In router/pricing.py (new file)
import httpx, json, time
from pathlib import Path

_CACHE_FILE = Path("/tmp/mullm_model_prices.json")
_CACHE_TTL = 86400  # 24h

async def fetch_prices() -> dict[str, float]:
    """Returns {model_id: cost_per_1k_tokens} from OpenRouter."""
    if _CACHE_FILE.exists() and time.time() - _CACHE_FILE.stat().st_mtime < _CACHE_TTL:
        return json.loads(_CACHE_FILE.read_text())
    async with httpx.AsyncClient() as c:
        r = await c.get("https://openrouter.ai/api/v1/models", timeout=10)
        models = r.json().get("data", [])
    prices = {m["id"]: float(m.get("pricing", {}).get("completion", 0)) * 1000
              for m in models}
    _CACHE_FILE.write_text(json.dumps(prices))
    return prices

async def cheapest_model_for(tier: str) -> str | None:
    """Given a quality tier, return the cheapest model that meets it."""
    # quality bands defined here — not hardcoded in cloud.py
    ...
```

Call `fetch_prices()` at mullm server startup and once per day (cron or background task).
The `cloud_power` tier can then select whichever of Opus / GPT-5.5 / Gemini Pro is cheapest
at that moment.

---

## Recommended Sequence

1. **vLLM on 3090 box** — already supported, just needs env vars and the model loaded.
   Test: `VLLM_BASE_URL=http://3090-box:8000 VLLM_MODEL=deepseek-coder-v2-lite mullm ...`

2. **OpenRouter pricing cache** — add `router/pricing.py`, call at startup, wire into
   `cloud_power` tier selection. Low risk, high value, ~100 lines.

3. **LiteLLM proxy (Option A)** — run alongside mullm, add `call_litellm()` as an
   alternate code path in cloud.py. Gate it on `LITELLM_BASE_URL` being set, same pattern
   as vLLM. Does not break existing code.

4. **LiteLLM full replace (Option B)** — only after Option A is validated. Removes
   ~600 lines of provider-specific client code from cloud.py.

## What This Unlocks

- Precise cost-aware routing: pick the cheapest model that meets quality threshold
- Off-peak discounts: OpenRouter exposes time-varying prices
- Zero-config new providers: update litellm_config.yaml, mullm picks it up automatically
- Shared cache across model families: a Haiku response cached is reusable when Sonnet
  would have answered identically
- IDE integration becomes simpler: one API surface (OpenAI wire format) that any tool speaks
