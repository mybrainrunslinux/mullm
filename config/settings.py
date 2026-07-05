"""
muLLM configuration.
All thresholds, model names, tier settings in one place.
Override via environment variables or .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / "cache" / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR = str(CACHE_DIR / "chromadb")
SQLITE_PATH = str(CACHE_DIR / "graph.db")
SCORING_LOG = str(CACHE_DIR / "scoring_log.jsonl")
AUDIT_LOG_PATH = str(CACHE_DIR / "audit_log.jsonl")

# ── Audit Log ────────────────────────────────────────────────
# Append-only immutable request log. Set AUDIT_LOG_ENABLED=1 to activate.
# Never deleted or rotated — append-only is the "immutable" guarantee.
AUDIT_LOG_ENABLED: bool = os.getenv("AUDIT_LOG_ENABLED", "0") == "1"

# ── Ollama ───────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Models — to use custom Modelfile variants (recommended):
#   ollama create megallmaniac-classifier -f Modelfile.classifier
#   ollama create megallmaniac-gen -f Modelfile.gen
# Then set env vars accordingly.
CLASSIFIER_MODEL = os.getenv(
    "CLASSIFIER_MODEL", "qwen2.5:0.5b"
)  # tiny 379MB model — runs alongside main model, no swap
CODE_MODEL = os.getenv("CODE_MODEL", "qwen3-coder:30b")
GENERAL_MODEL = os.getenv("GENERAL_MODEL", "qwen3-coder:30b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "65536"))  # context window — 64K for Qwen3 think blocks on RTX 5090
OLLAMA_KEEP_ALIVE = int(os.getenv("OLLAMA_KEEP_ALIVE", "5400"))  # 90 min — keep models loaded in vRAM
KEEPALIVE_INTERVAL = int(
    os.getenv("KEEPALIVE_INTERVAL", "300")
)  # 5 min — safety net, model kept by keep_alive=-1  # 30 min — ping interval to keep models warm
VISION_MODEL = os.getenv(
    "VISION_MODEL", "qwen2.5vl:7b"
)  # qwen2.5vl:7b = SOTA local vision; fallback: minicpm-v  # multimodal vision (fallback: llava:13b)
FALLBACK_GENERAL_MODEL = "qwen3-coder:30b"
ESCALATION_MODEL = os.getenv("ESCALATION_MODEL", "qwen3-coder:30b")
ESCALATION_KEEP_ALIVE = int(os.getenv("ESCALATION_KEEP_ALIVE", "0"))  # Unload immediately — 30B blocks 9B if kept warm
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")  # 768-dim, 8K context — migrated S24
# Old: mxbai-embed-large (1024-dim, 512 tokens) — ChromaDB rebuilt with nomic S24
REDIS_RAM_URL = os.getenv("REDIS_RAM_URL", "redis://localhost:8179/0")  # 4GB RAM cache for exact-match queries

# ── Alternative Cloud Inference (OpenAI-compatible) ──────────
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")

# ── vLLM ────────────────────────────────────────────────────
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "")  # e.g. http://localhost:8000; disabled when empty
VLLM_MODEL = os.getenv("VLLM_MODEL", "default")  # model name served by vLLM

# ── Web Search ───────────────────────────────────────────────
WEB_SEARCH_ENABLED = os.getenv("MULLM_WEB_SEARCH", "1") == "1"  # pre-route + response interception

# ── Anthropic Prompt Caching ─────────────────────────────────
# When enabled, the system prompt is sent with cache_control: ephemeral.
# Cache hits cost ~10% of normal input token price; writes cost ~125%.
# Net savings ≈ 70-90% on system prompt tokens for repeated queries.
# Requires Anthropic API; toggle via env var or /api/settings.
PROMPT_CACHE_ENABLED: bool = os.getenv("MULLM_PROMPT_CACHE", "0") == "1"

# ── Context Prefix (SoT-style) ───────────────────────────────
# When set, this file's content is prepended to every cloud query as a
# stable frozen prefix — enables prompt cache hits across sessions.
# Set MULLM_CONTEXT_FILE=/path/to/groundtruth.md or pass ?context_file= per-request.
CONTEXT_FILE: str = os.getenv("MULLM_CONTEXT_FILE", "")

# ── Concurrency ──────────────────────────────────────────────
# [Suggestion #1] Max concurrent embed calls to avoid GPU starvation
EMBED_CONCURRENCY = int(os.getenv("EMBED_CONCURRENCY", "2"))
# [Suggestion #8] Max concurrent Ollama generation calls
OLLAMA_CONCURRENCY = int(os.getenv("OLLAMA_CONCURRENCY", "1"))  # 1 = safe; 30b+9b can't coexist in 32GB

# ── Cache Thresholds ─────────────────────────────────────────
CACHE_HIT_THRESHOLD = float(os.getenv("CACHE_HIT_THRESHOLD", "0.98"))
CACHE_PARTIAL_THRESHOLD = float(os.getenv("CACHE_PARTIAL_THRESHOLD", "0.92"))
# [Suggestion #7] Cache entries older than this (seconds) become partial hits
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(30 * 86400)))  # 30 days

# Adaptive cache thresholds per intent category (vCache-inspired)
# Higher = stricter (fewer false hits); Lower = more permissive (higher hit rate)
# Different query types have different "safe" similarity levels:
#   math/code: small wording changes = different answer → need high similarity
#   factual/lookup: paraphrases of the same question have the same answer → lower OK
#   creative: similar prompts get similar good responses → lowest threshold
CACHE_THRESHOLDS: dict[str, float] = {
    "math": float(os.getenv("CACHE_THRESH_MATH", "0.97")),
    "code": float(os.getenv("CACHE_THRESH_CODE", "0.97")),
    "deploy": float(os.getenv("CACHE_THRESH_DEPLOY", "0.95")),
    "note": float(os.getenv("CACHE_THRESH_NOTE", "0.95")),
    "lookup": float(os.getenv("CACHE_THRESH_LOOKUP", "0.90")),
    "factual": float(os.getenv("CACHE_THRESH_FACTUAL", "0.91")),
    "research": float(os.getenv("CACHE_THRESH_RESEARCH", "0.96")),
    "conversation": float(os.getenv("CACHE_THRESH_CONV", "0.94")),
    "creative": float(os.getenv("CACHE_THRESH_CREATIVE", "0.93")),
    "system": float(os.getenv("CACHE_THRESH_SYSTEM", "0.95")),
    "default": float(os.getenv("CACHE_HIT_THRESHOLD", "0.98")),
}

# ── Intent Categories ────────────────────────────────────────
INTENT_CATEGORIES = [
    "note",
    "lookup",
    "code",
    "research",
    "creative",
    "deploy",
    "conversation",
]

# ── Complexity → Tier Mapping ────────────────────────────────
COMPLEXITY_TIER_MAP = {
    1: "cache",
    2: "local",
    3: "local",  # S26: single-pass is fast enough for complexity 3
    4: "local_multi",  # S26: two-pass only for genuinely complex tasks
    5: "cloud_full",
}

# ── Cloud Model Pricing ($/million tokens) ───────────────────
# Keyed by both short names AND full model IDs so lookups always work
_CLOUD_MODEL_DEFS = {
    "gemini-flash": {
        "provider": "google",
        "cost_per_m_input": 0.075,
        "cost_per_m_output": 0.30,
        "strengths": ["simple_code", "summaries", "translation"],
        "max_context": 1_000_000,
    },
    "gemini-pro": {
        "provider": "google",
        "cost_per_m_input": 1.25,
        "cost_per_m_output": 10.00,
        "strengths": ["complex_reasoning", "long_context", "multi_modal"],
        "max_context": 1_000_000,
    },
    "gemini-flash-lite": {
        "provider": "google",
        "cost_per_m_input": 0.075,
        "cost_per_m_output": 0.30,
        "strengths": ["fast", "cheap"],
        "max_context": 1_000_000,
    },
    "gemma-4-31b-it": {
        "provider": "google",
        "cost_per_m_input": 0.10,
        "cost_per_m_output": 0.40,
        "strengths": ["fast", "cheap", "open_source"],
        "max_context": 128_000,
    },
    "gemma-4-26b-a4b-it": {
        "provider": "google",
        "cost_per_m_input": 0.10,
        "cost_per_m_output": 0.40,
        "strengths": ["fast", "cheap", "open_source"],
        "max_context": 128_000,
    },
    "gemini-pro-latest": {
        "provider": "google",
        "cost_per_m_input": 1.25,
        "cost_per_m_output": 10.00,
        "strengths": ["complex_reasoning", "long_context", "multi_modal"],
        "max_context": 1_000_000,
    },
    "gemini-flash-latest": {
        "provider": "google",
        "cost_per_m_input": 0.075,
        "cost_per_m_output": 0.30,
        "strengths": ["fast", "cheap", "multi_modal"],
        "max_context": 1_000_000,
    },
    "nano-banana": {
        "provider": "google",
        "cost_per_m_input": 0.05,
        "cost_per_m_output": 0.20,
        "strengths": ["image_gen", "image_edit", "fast", "cheap"],
        "max_context": 128_000,
    },
    "nano-banana-pro": {
        "provider": "google",
        "cost_per_m_input": 0.15,
        "cost_per_m_output": 0.60,
        "strengths": ["image_gen", "image_edit", "multi_modal", "creative"],
        "max_context": 128_000,
    },
    # Gemini 3.1 Pro — 80.6% SWE-bench Verified, ~60% lower cost than Opus for coding
    "gemini-3.1-pro": {
        "provider": "google",
        "cost_per_m_input": 1.25,   # estimated — similar to 2.5-pro tier
        "cost_per_m_output": 5.00,
        "strengths": ["complex_code", "swe_bench", "reasoning", "long_context", "agentic"],
        "max_context": 1_000_000,
    },
    # MiniMax M2.5 Lightning — 80.2% SWE-bench Verified open-weight, fast inference
    "minimax-m2.5": {
        "provider": "minimax",
        "cost_per_m_input": 0.30,   # estimated — open-weight API pricing
        "cost_per_m_output": 1.20,
        "strengths": ["complex_code", "swe_bench", "fast", "open_weight"],
        "max_context": 200_000,
    },
    "minimax-m2.5-lightning": {
        "provider": "minimax",
        "cost_per_m_input": 0.10,   # lightning = faster/cheaper variant
        "cost_per_m_output": 0.40,
        "strengths": ["fast", "code_gen", "open_weight"],
        "max_context": 200_000,
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "cost_per_m_input": 0.15,
        "cost_per_m_output": 0.60,
        "strengths": ["tool_calling", "medium_code", "structured_output"],
        "max_context": 128_000,
    },
    "gpt-4o": {
        "provider": "openai",
        "cost_per_m_input": 2.50,
        "cost_per_m_output": 10.00,
        "strengths": ["complex_code", "reasoning", "multi_modal"],
        "max_context": 128_000,
    },
    "gpt-4-turbo": {
        "provider": "openai",
        "cost_per_m_input": 10.00,
        "cost_per_m_output": 30.00,
        "strengths": ["legacy_compat"],
        "max_context": 128_000,
    },
    "o1": {
        "provider": "openai",
        "cost_per_m_input": 15.00,
        "cost_per_m_output": 60.00,
        "strengths": ["deep_reasoning", "math", "science"],
        "max_context": 200_000,
    },
    "o3-mini": {
        "provider": "openai",
        "cost_per_m_input": 1.10,
        "cost_per_m_output": 4.40,
        "strengths": ["reasoning", "cost_effective"],
        "max_context": 200_000,
    },
    # gpt-5.3 was never a real standalone model — removed (gpt-5.3-codex only)
    "gpt-5.3-codex": {
        "provider": "openai",
        "cost_per_m_input": 2.50,
        "cost_per_m_output": 10.00,
        "strengths": ["code_gen", "code_review", "agentic", "tool_calling"],
        "max_context": 256_000,
    },
    # gpt-5.4 family — verified available 2026-04-10 via /v1/models
    "gpt-5.4": {
        "provider": "openai",
        "cost_per_m_input": 3.00,  # estimated — bump 30% for safety
        "cost_per_m_output": 12.00,
        "strengths": ["complex_code", "reasoning", "multi_modal", "agentic"],
        "max_context": 256_000,
    },
    "gpt-5.4-pro": {
        "provider": "openai",
        "cost_per_m_input": 5.00,  # estimated — bump 30% for safety
        "cost_per_m_output": 20.00,
        "strengths": ["novel_architecture", "deep_reasoning", "full_deploy", "agentic"],
        "max_context": 256_000,
    },
    # gpt-5.5 family — verified available 2026-04-23 via /v1/models
    # Note: gpt-5.5-pro requires Responses API (v1/responses), not chat completions
    "gpt-5.5": {
        "provider": "openai",
        "cost_per_m_input": 4.00,   # estimated ~35% premium over gpt-5.4
        "cost_per_m_output": 16.00,
        "strengths": ["complex_code", "reasoning", "agentic", "tool_calling"],
        "max_context": 256_000,
        "notes": "requires max_completion_tokens not max_tokens",
    },
    "gpt-5.5-pro": {
        "provider": "openai",
        "cost_per_m_input": 8.00,   # estimated premium
        "cost_per_m_output": 32.00,
        "strengths": ["complex_code", "reasoning", "agentic", "tool_calling"],
        "max_context": 256_000,
        "notes": "requires Responses API (v1/responses) — not usable via chat completions",
    },
    "gpt-5.4-mini": {
        "provider": "openai",
        "cost_per_m_input": 0.25,  # estimated
        "cost_per_m_output": 1.00,
        "strengths": ["fast", "cheap", "simple_code"],
        "max_context": 128_000,
    },
    "gpt-4.1": {
        "provider": "openai",
        "cost_per_m_input": 2.00,  # verified cheaper than 4o
        "cost_per_m_output": 8.00,
        "strengths": ["complex_code", "tool_calling", "reasoning"],
        "max_context": 256_000,
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "cost_per_m_input": 0.15,
        "cost_per_m_output": 0.60,
        "strengths": ["fast", "cheap", "simple_code", "classification"],
        "max_context": 128_000,
    },
    "gpt-5-mini": {
        "provider": "openai",
        "cost_per_m_input": 0.50,  # estimated
        "cost_per_m_output": 2.00,
        "strengths": ["fast", "cheap", "simple_code"],
        "max_context": 128_000,
    },
    "gpt-4o-audio": {
        "provider": "openai",
        "cost_per_m_input": 2.50,
        "cost_per_m_output": 10.00,
        "strengths": ["voice", "audio", "multi_modal"],
        "max_context": 128_000,
    },
    # SambaNova — fast inference on RDU chips
    "Meta-Llama-3.3-70B-Instruct": {
        "provider": "sambanova",
        "cost_per_m_input": 0.60,
        "cost_per_m_output": 1.20,
        "strengths": ["fast", "cheap", "general"],
        "max_context": 128_000,
    },
    "Llama-3.1-405B-Instruct": {
        "provider": "sambanova",
        "cost_per_m_input": 5.00,
        "cost_per_m_output": 10.00,
        "strengths": ["large", "complex_reasoning"],
        "max_context": 16_384,
    },
    # Together.ai — wide open-model catalog
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "provider": "together",
        "cost_per_m_input": 0.88,
        "cost_per_m_output": 0.88,
        "strengths": ["fast", "cheap", "general"],
        "max_context": 128_000,
    },
    "Qwen/Qwen2.5-72B-Instruct-Turbo": {
        "provider": "together",
        "cost_per_m_input": 1.20,
        "cost_per_m_output": 1.20,
        "strengths": ["fast", "code", "reasoning"],
        "max_context": 32_768,
    },
    # Cerebras — wafer-scale inference, extremely fast
    "llama3.3-70b": {
        "provider": "cerebras",
        "cost_per_m_input": 0.85,
        "cost_per_m_output": 1.20,
        "strengths": ["ultra_fast", "cheap", "general"],
        "max_context": 128_000,
    },
    "llama-3.1-8b": {
        "provider": "cerebras",
        "cost_per_m_input": 0.10,
        "cost_per_m_output": 0.10,
        "strengths": ["ultra_fast", "cheap", "small"],
        "max_context": 128_000,
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "cost_per_m_input": 3.00,
        "cost_per_m_output": 15.00,
        "strengths": ["complex_code", "architecture", "multi_file", "reasoning"],
        "max_context": 200_000,
    },
    "claude-haiku": {
        "provider": "anthropic",
        "cost_per_m_input": 0.80,
        "cost_per_m_output": 4.00,
        "strengths": ["fast", "cheap", "simple_code", "classification"],
        "max_context": 200_000,
    },
    "claude-opus": {
        "provider": "anthropic",
        "cost_per_m_input": 15.00,
        "cost_per_m_output": 75.00,
        "strengths": ["novel_architecture", "deep_reasoning", "full_deploy"],
        "max_context": 200_000,
    },
}

# Build full lookup: short keys + full model IDs all point to the same pricing
CLOUD_MODELS = dict(_CLOUD_MODEL_DEFS)
_FULL_ID_TO_SHORT = {
    "claude-sonnet-4-20250514": "claude-sonnet",
    "claude-haiku-4-5-20251001": "claude-haiku",
    "claude-opus-4-6": "claude-opus",
    "claude-opus-4-20250514": "claude-opus",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4-turbo",
    "o1": "o1",
    "o3-mini": "o3-mini",
    "gemini-2.5-pro": "gemini-pro",
    "gemini-2.0-flash": "gemini-flash",
    "gemini-2.0-flash-lite": "gemini-flash-lite",
    "gemini-pro-latest": "gemini-pro-latest",
    "gemini-flash-latest": "gemini-flash-latest",
    "nano-banana": "nano-banana",
    "nano-banana-pro": "nano-banana-pro",
    "gpt-5.3-codex": "gpt-5.3-codex",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-2026-03-05": "gpt-5.4",
    "gpt-5.4-pro": "gpt-5.4-pro",
    "gpt-5.5": "gpt-5.5",
    "gpt-5.5-2026-04-23": "gpt-5.5",
    "gpt-5.5-pro": "gpt-5.5-pro",
    "gpt-5.5-pro-2026-04-23": "gpt-5.5-pro",
    "gpt-5.4-pro-2026-03-05": "gpt-5.4-pro",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-mini-2026-03-17": "gpt-5.4-mini",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-2025-04-14": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-4.1-mini-2025-04-14": "gpt-4.1-mini",
    "gpt-5-mini": "gpt-5-mini",
    "gpt-4o-audio-preview": "gpt-4o-audio",
    "gemini-3.1-pro": "gemini-3.1-pro",
    "gemini-3.1-pro-latest": "gemini-3.1-pro",
    "minimax-m2.5": "minimax-m2.5",
    "minimax-m2.5-lightning": "minimax-m2.5-lightning",
    "MiniMax-M2.5": "minimax-m2.5",
    "MiniMax-M2.5-Lightning": "minimax-m2.5-lightning",
}
for full_id, short_key in _FULL_ID_TO_SHORT.items():
    if full_id not in CLOUD_MODELS and short_key in CLOUD_MODELS:
        CLOUD_MODELS[full_id] = CLOUD_MODELS[short_key]

# ── Permission Thresholds (estimated cost in $) ──────────────
AUTO_APPROVE_CEILING = float(os.getenv("AUTO_APPROVE_CEILING", "0.01"))
ASK_APPROVAL_CEILING = float(os.getenv("ASK_APPROVAL_CEILING", "0.50"))

# ── Temperature Presets ──────────────────────────────────────
# Three levels: precise (deterministic), balanced, creative
TEMP_PRECISE = 0.1  # code, deploy, math — near-deterministic
TEMP_BALANCED = 0.4  # general, lookup, research — good default
TEMP_CREATIVE = 0.65  # creative writing, brainstorming — looser
# Map intent categories to default temperature
CATEGORY_TEMP_MAP = {
    "code": TEMP_PRECISE,
    "deploy": TEMP_PRECISE,
    "lookup": TEMP_BALANCED,
    "research": TEMP_BALANCED,
    "conversation": TEMP_BALANCED,
    "note": TEMP_PRECISE,
    "creative": TEMP_CREATIVE,
}

# ── Budget Caps (tiered) ───────────────────────────────────
DAILY_BUDGET_CAP = float(os.getenv("DAILY_BUDGET_CAP", "5.00"))  # legacy compat
BUDGET_WARN_LIMIT = float(os.getenv("MULLM_WARN_LIMIT", "7.00"))  # show warning
BUDGET_MODERATE_LIMIT = float(os.getenv("MULLM_MODERATE_LIMIT", "10.00"))  # soft cap, local-only
BUDGET_HARD_LIMIT = float(os.getenv("MULLM_HARD_LIMIT", "50.00"))  # absolute max per day
BUDGET_WEEKLY_LIMIT = float(os.getenv("MULLM_WEEKLY_LIMIT", "20.00"))

# ── Deduplication ────────────────────────────────────────────
# [Suggestion #4] Window in seconds for request deduplication
DEDUP_WINDOW_SECONDS = float(os.getenv("DEDUP_WINDOW_SECONDS", "2.0"))

# ── Scoring Log ──────────────────────────────────────────────
# [Suggestion #5] Max records before rotation
SCORING_LOG_MAX_RECORDS = int(os.getenv("SCORING_LOG_MAX_RECORDS", "50000"))

# ── GDPR/CCPA Privacy Controls ───────────────────────────────
# Entries in scoring_log.jsonl older than this are purged on startup (non-blocking).
# Set to 0 to disable auto-purge.
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))
# When False, ChromaDB stores only routing metadata (model, tier, category, cost, latency, timestamp)
# — the query text and response are NOT persisted to the vector cache.
# Scoring_log.jsonl never stores query content regardless of this setting.
LOG_QUERY_CONTENT = os.getenv("LOG_QUERY_CONTENT", "true").lower() == "true"

# ── Classifier ───────────────────────────────────────────────
# [Suggestion #11] Below this, run LLM classifier as second opinion
CLASSIFIER_DUAL_THRESHOLD = float(os.getenv("CLASSIFIER_DUAL_THRESHOLD", "0.80"))

# ── Voice Output ─────────────────────────────────────────────
VOICE_OUTPUT_ENABLED = os.getenv("VOICE_OUTPUT_ENABLED", "true").lower() == "true"
VOICE_MAX_WORDS = int(os.getenv("VOICE_MAX_WORDS", "10000"))  # Hard limit for TTS
VOICE_ASK_THRESHOLD_WORDS = int(os.getenv("VOICE_ASK_THRESHOLD_WORDS", "1000"))  # Ask user for long content
VOICE_DEFAULT_RATE = float(os.getenv("VOICE_DEFAULT_RATE", "1.0"))  # Speech rate (0.1-10)
VOICE_DEFAULT_PITCH = float(os.getenv("VOICE_DEFAULT_PITCH", "1.0"))  # Speech pitch (0-2)
VOICE_DEFAULT_VOICE = os.getenv("VOICE_DEFAULT_VOICE", "")  # Empty = system default

# ── Provider / Model Blocking ─────────────────────────────────
# Default disabled providers (empty = all enabled).
# Override via config/toggles.json or POST /api/setup/toggles.
# Valid values: "anthropic", "openai", "google", "local"
DISABLED_PROVIDERS: list[str] = []
# Default disabled models (empty = all enabled).
# Use full model short-keys from CLOUD_MODELS above.
DISABLED_MODELS: list[str] = []

# ── Prompt Compression (LLMLingua-2) ────────────────────────
# Only applied to cloud calls on prompts exceeding MIN_TOKENS tokens.
# Set LLMLINGUA_ENABLED=false to disable without uninstalling.
LLMLINGUA_RATIO = float(os.getenv("LLMLINGUA_RATIO", "0.5"))
LLMLINGUA_MIN_TOKENS = int(os.getenv("LLMLINGUA_MIN_TOKENS", "800"))
LLMLINGUA_ENABLED = os.getenv("LLMLINGUA_ENABLED", "true").lower() == "true"

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "json"

# ── Commit Attribution ────────────────────────────────────────
# When mullm generates code that gets committed, append a Co-authored-by trailer.
# mode: "always" | "never" | "auto" (auto = always for now; session-aware later)
# Install the git hook with: mullm --install-git-hook
COMMIT_ATTRIBUTION_MODE  = os.getenv("MULLM_COMMIT_ATTRIBUTION", "auto")
COMMIT_ATTRIBUTION_NAME  = os.getenv("MULLM_COMMIT_ATTRIBUTION_NAME", "muLLM")
COMMIT_ATTRIBUTION_EMAIL = os.getenv("MULLM_COMMIT_ATTRIBUTION_EMAIL", "mullm@mullm.com")

# Runtime-override file (~/.mullm/runtime.toml) for settings changed from the UI.
# These are loaded on top of env vars at startup and persisted across restarts.
RUNTIME_CONFIG_PATH = Path.home() / ".mullm" / "runtime.toml"
