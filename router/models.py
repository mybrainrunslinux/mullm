"""
muLLM Pydantic v2 request/response models.

All user-facing inputs are validated here before touching any business logic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Modality(str, Enum):
    TEXT    = "text"
    VOICE   = "voice"
    VISUAL  = "visual"
    SCREEN  = "screen"
    FILE    = "file"


class Source(str, Enum):
    CLI     = "cli"
    IDE     = "ide"
    PHONE   = "phone"
    WEB     = "web"
    WEBHOOK = "webhook"
    API     = "api"


class TierLabel(str, Enum):
    GROUNDTRUTH  = "groundtruth"   # Tier 0 — deterministic LUT
    CACHE        = "cache"          # Tier 1 — semantic vector cache
    LOCAL        = "local"          # Tier 2 — Ollama local inference
    LOCAL_MULTI  = "local_multi"    # Tier 2b — stronger local model / local ensemble
    CLOUD_CHEAP  = "cloud_cheap"    # Tier 3a — haiku / 4o-mini / flash
    CLOUD_FULL   = "cloud_full"     # Tier 3b — sonnet / 4o / pro
    CLOUD_POWER  = "cloud_power"    # Tier 3c — top configured model / explicit escalation


class Tier(str, Enum):
    """Extended tier enum matching the original routing pipeline."""
    CACHE        = "cache"
    LOCAL        = "local"
    LOCAL_MULTI  = "local_multi"
    CLOUD_CHEAP  = "cloud_cheap"
    CLOUD_FULL   = "cloud_full"
    CLOUD_POWER  = "cloud_power"


class IntentCategory(str, Enum):
    CODE         = "code"
    RESEARCH     = "research"
    CREATIVE     = "creative"
    CONVERSATION = "conversation"
    DEPLOY       = "deploy"
    NOTE         = "note"
    LOOKUP       = "lookup"
    VISION       = "vision"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Primary query payload — validated before entering the pipeline."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=32_768,
        description="The user's question or prompt.",
    )
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Opaque session identifier for cost-tracking and rate-limiting.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Client-generated request identifier used for cancellation.",
    )
    tier_override: TierLabel | None = Field(
        default=None,
        validation_alias=AliasChoices("tier_override", "force_tier"),
        description="Force a specific tier, bypassing classifier routing.",
    )
    model_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("model_override", "model"),
        max_length=128,
        description="Force a specific model name.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature; overrides the category default when set.",
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=20,
        description="Prior conversation turns for intent context (last 3 used).",
    )
    images: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Base64-encoded image strings for vision queries.",
    )
    stream: bool = Field(
        default=False,
        description="When True, request SSE streaming from the local Ollama tier.",
    )
    skip_cache: bool = Field(
        default=False,
        description="Bypass vector cache lookup for this request.",
    )
    use_web: bool = Field(
        default=False,
        description="Allow web retrieval. Default is false so chat cannot surprise-spend or browse.",
    )
    use_jina: bool = Field(
        default=False,
        description="Allow Jina page fetches when web retrieval is enabled.",
    )
    powerup: bool = Field(
        default=False,
        description="WITH RICE mode: fire the top Anthropic/OpenAI/Google models in parallel, then marshal-synthesize the best response. Disables cost-optimization; requires powerup_confirmed.",
    )
    powerup_confirmed: bool = Field(
        default=False,
        description="User has acknowledged the cost warning for powerup mode.",
    )
    allow_cloud_escalation: bool = Field(
        default=False,
        validation_alias=AliasChoices("allow_cloud_escalation", "auto_escalate"),
        description="Permit automatic local-to-cloud quality escalation.",
    )
    cost_strategy: str | None = Field(
        default=None,
        max_length=32,
        description="Cloud model selection strategy: quality/default or cost_optimize.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Pass-through options for the local tier: num_predict, think, bench_mode, etc.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_tier_aliases(cls, data: Any) -> Any:
        """Accept old UI/API tier names while reporting canonical tier labels."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for key in ("tier_override", "force_tier"):
            if str(normalized.get(key) or "").lower() == "cloud_multi":
                normalized[key] = "cloud_power"
        return normalized

    @field_validator("content")
    @classmethod
    def _strip_content(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("content must not be blank after stripping whitespace")
        return stripped

    @field_validator("history")
    @classmethod
    def _validate_history(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        for turn in v:
            if "role" not in turn or "content" not in turn:
                raise ValueError("Each history turn must have 'role' and 'content' keys")
            if turn["role"] not in {"user", "assistant", "system"}:
                raise ValueError(f"Invalid role: {turn['role']!r}")
        return v


class SplitQueryRequest(BaseModel):
    """Request for split/parallel routing of multi-part prompts."""

    content: str = Field(..., min_length=1, max_length=32_768)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    max_parts: int = Field(default=4, ge=1, le=10)


# ---------------------------------------------------------------------------
# Cache result model
# ---------------------------------------------------------------------------

class CacheResult(BaseModel):
    """Output of a cache lookup."""

    hit: bool
    similarity: float = 0.0
    cached_response: str | None = None
    cached_metadata: dict[str, Any] = Field(default_factory=dict)
    lookup_latency_ms: float = 0.0
    source: str = "vector"
    age_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Classification and routing models (original pipeline compatibility)
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    """Output of the intent classifier."""

    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: IntentCategory = IntentCategory.CONVERSATION
    complexity: int = Field(default=1, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list)
    needs_vision: bool = False
    needs_web: bool = False
    estimated_tokens: int = 0
    suggested_tier: Tier = Tier.LOCAL
    classifier_latency_ms: float = 0.0
    classifier_method: str = "rules"


class ModelSelection(BaseModel):
    """Which model to use and why."""

    model_name: str = ""
    provider: str = ""
    tier: Tier = Tier.LOCAL
    estimated_cost: float = 0.0
    reason: str = ""
    requires_approval: bool = False


class TierResult(BaseModel):
    """Final output of a tier's processing."""

    intent_id: str = ""
    tier: Tier = Tier.LOCAL
    success: bool = True
    response: str = ""
    model_used: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    escalate: bool = False
    escalate_reason: str = ""
    cache_back: bool = True
    fallback_warning: str = ""


class SubTaskResult(BaseModel):
    """Result of a single sub-task within a split routing request."""

    index: int = 0
    task: str = ""
    suggested_tier: str = "local"
    actual_tier: Tier = Tier.LOCAL
    model_used: str = ""
    provider: str = ""
    response: str = ""
    cost: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    from_cache: bool = False
    depends_on: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Core result models
# ---------------------------------------------------------------------------

class IntentObject(BaseModel):
    """Classifier output for a single query (content field accepted for pipeline input compat)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique intent ID.")
    content: str = Field(default="", description="Input text (pipeline input compatibility).")
    modality: Modality = Modality.TEXT
    source: Source = Source.API
    session_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    category: IntentCategory = IntentCategory.CONVERSATION
    complexity: int = Field(default=1, ge=1, le=5, description="1=trivial, 5=expert-level")
    keywords: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_vision: bool = False
    needs_web: bool = False
    raw_scores: dict[str, float] | None = None
    embedding: list[float] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PipelineResult(BaseModel):
    """Unified result returned by every tier."""

    response: str
    tier: TierLabel
    tier_used: str | None = None             # string alias for tier (compatibility)
    cost: float = Field(ge=0.0, description="Estimated USD cost for this request.")
    tokens_used: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    model_used: str
    cached: bool = False
    from_cache: bool = False                    # alias for cached
    session_id: str | None = None
    session_cost_total: float = 0.0             # cumulative session cost
    intent: IntentObject | None = None
    groundtruth_category: str | None = None  # set when tier == GROUNDTRUTH
    quality_escalated: bool = False              # True if local->cloud quality gate triggered

    @model_validator(mode="after")
    def _set_aliases(self) -> PipelineResult:
        if self.tier_used is None:
            self.tier_used = self.tier.value
        if self.cached and not self.from_cache:
            self.from_cache = True
        return self


class SplitResult(BaseModel):
    """Result of split routing — multiple sub-query results."""

    subtasks: list[Any] = Field(default_factory=list)
    parts: list[PipelineResult] = Field(default_factory=list)
    combined_response: str = ""
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    decompose_method: str = "fast"


# ---------------------------------------------------------------------------
# API response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    port: int
    mode: str                       # "dev" | "prod"
    ollama_available: bool
    ollama_ok: bool = False         # alias for compatibility
    chromadb_available: bool        # deprecated alias for semantic_cache_available
    semantic_cache_available: bool = False
    semantic_cache_backend: str = "sqlite"
    classifier_loaded: bool
    cache_docs: int = 0             # number of cached embeddings


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    owned_by: str


class ModelsListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class ChatMessage(BaseModel):
    role: str
    # OpenAI multimodal format sends content as a list of {type, text} parts
    content: str | list[dict[str, Any]] = ""

    def text(self) -> str:
        if isinstance(self.content, list):
            return " ".join(
                part.get("text", "") for part in self.content if part.get("type") == "text"
            )
        return self.content or ""


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible /v1/chat/completions request body."""

    model: str = Field(default="mullm-auto")
    messages: list[ChatMessage] = Field(..., min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=65536)
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


# ---------------------------------------------------------------------------
# Dashboard and system stats
# ---------------------------------------------------------------------------

class TierStats(BaseModel):
    hits: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float = 0.0


class DashboardData(BaseModel):
    total_queries: int
    total_cost: float
    cost_reduction_pct: float        # vs. always-cloud baseline
    session_cost: float
    tier_breakdown: dict[str, TierStats]
    top_categories: list[dict[str, Any]]
    queries_last_hour: int
    avg_latency_ms: float


class GpuStats(BaseModel):
    name: str | None = None
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    memory_pct: float = 0.0
    utilization_pct: float = 0.0
    temperature_c: float | None = None
    inferred_only: bool = False


class SystemStats(BaseModel):
    cpu_pct: float
    ram_used_gb: float
    ram_total_gb: float
    gpu: GpuStats | None = None
    ollama_loaded_models: list[str] = Field(default_factory=list)
    cpu_count: int = 0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    memory_pct: float = 0.0
    uptime_seconds: float = 0.0
    ollama_models: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Session cost summary
# ---------------------------------------------------------------------------

class SessionCostSummary(BaseModel):
    session_id: str
    total_cost: float
    query_count: int
    budget_status: str              # "ok" | "warn" | "moderate" | "hard"
    remaining_budget: float
