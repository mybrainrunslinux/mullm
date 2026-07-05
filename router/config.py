"""
muLLM router configuration.

Config priority (highest → lowest):
  1. Environment variables (MULLM_*, ANTHROPIC_API_KEY, etc.)
  2. mullm.toml in current directory (project-local)
  3. ~/.mullm/config.toml (user global)
  4. Built-in defaults

All runtime settings live here.  Import the module-level singleton:

    from router.config import settings
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, InitSettingsSource, SettingsConfigDict


def _resolve_secret_reference(value: Any) -> Any:
    """Resolve explicit local secret references from dotenv/TOML values.

    Shell expressions such as ``$(pass foo/bar)`` are intentionally not
    evaluated by dotenv parsers.  muLLM supports the explicit and auditable
    ``pass:foo/bar`` form instead.
    """
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if raw.startswith("pass://"):
        name = raw[len("pass://") :]
    elif raw.startswith("pass:"):
        name = raw[len("pass:") :]
    else:
        return value
    if not name or "\n" in name or "\r" in name or not shutil.which("pass"):
        return None
    proc = subprocess.run(["pass", "show", name], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    lines = proc.stdout.splitlines()
    return lines[0] if lines else None


def _default_state_dir() -> Path:
    """Return a user-writable directory for runtime state.

    Source checkouts can still override this with ``mullm.toml`` or
    ``MULLM_CACHE_DIR``. The built-in default must not point inside the installed
    package, because wheels usually live in read-only ``site-packages``.
    """
    override = os.getenv("MULLM_STATE_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "muLLM"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "muLLM"
    base = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "mullm"


def _default_cache_dir() -> Path:
    return _default_state_dir() / "cache" / "data"


def _default_asset_root() -> Path:
    return _default_state_dir() / "assets"


def _default_scoring_log() -> Path:
    return _default_cache_dir() / "scoring_log.jsonl"

# ---------------------------------------------------------------------------
# Cloud model pricing catalogue (6 canonical models, $/million tokens)
# ---------------------------------------------------------------------------

CLOUD_MODEL_PRICING: dict[str, dict] = {
    # --- Anthropic ---
    "claude-haiku-4-5": {
        "provider": "anthropic",
        "cost_per_m_input": 1.00,
        "cost_per_m_output": 5.00,
        "max_context": 200_000,
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "cost_per_m_input": 3.00,
        "cost_per_m_output": 15.00,
        "max_context": 1_000_000,
    },
    "claude-opus-4-6": {
        "provider": "anthropic",
        "cost_per_m_input": 5.00,
        "cost_per_m_output": 25.00,
        "max_context": 1_000_000,
    },
    "claude-opus-4-7": {
        "provider": "anthropic",
        "cost_per_m_input": 5.00,
        "cost_per_m_output": 25.00,
        "max_context": 1_000_000,
    },
    "claude-opus-4-8": {
        "provider": "anthropic",
        "cost_per_m_input": 5.00,
        "cost_per_m_output": 25.00,
        "max_context": 1_000_000,
    },
    "claude-fable-5": {
        "provider": "anthropic",
        "cost_per_m_input": 10.00,
        "cost_per_m_output": 50.00,
        "max_context": 1_000_000,
    },
    # --- OpenAI ---
    "gpt-4o-mini": {
        "provider": "openai",
        "cost_per_m_input": 0.15,
        "cost_per_m_output": 0.60,
        "max_context": 128_000,
    },
    "gpt-4o": {
        "provider": "openai",
        "cost_per_m_input": 2.50,
        "cost_per_m_output": 10.00,
        "max_context": 128_000,
    },
    "gpt-5.5": {                                # VERIFY model ID string
        "provider": "openai",
        "cost_per_m_input": 5.00,
        "cost_per_m_output": 30.00,
        "max_context": 1_000_000,
    },
    "gpt-5.5-pro": {                            # VERIFY model ID string
        "provider": "openai",
        "cost_per_m_input": 30.00,
        "cost_per_m_output": 180.00,
        "max_context": 1_000_000,
    },
    "gpt-5.4-pro": {                            # VERIFY model ID string
        "provider": "openai",
        "cost_per_m_input": 30.00,
        "cost_per_m_output": 180.00,
        "max_context": 1_050_000,
    },
    # --- Google ---
    "gemini-1.5-flash": {
        "provider": "google",
        "cost_per_m_input": 0.075,
        "cost_per_m_output": 0.30,
        "max_context": 1_000_000,
    },
    "gemini-1.5-pro": {
        "provider": "google",
        "cost_per_m_input": 1.25,
        "cost_per_m_output": 10.00,
        "max_context": 1_000_000,
    },
    "gemini-2.5-flash": {
        "provider": "google",
        "cost_per_m_input": 0.30,
        "cost_per_m_output": 2.50,
        "max_context": 1_000_000,
    },
    "gemini-3.1-pro-preview": {                 # VERIFY model ID string
        "provider": "google",
        "cost_per_m_input": 2.00,
        "cost_per_m_output": 12.00,
        "max_context": 2_000_000,
    },
    # --- Cerebras (OpenAI-compatible, ~3000 tok/s on WSE) ---
    "gpt-oss-120b": {                           # VERIFY: may be "llama-3.3-70b" or similar
        "provider": "cerebras",
        "cost_per_m_input": 0.35,
        "cost_per_m_output": 0.75,
        "max_context": 131_072,
    },
    # --- DeepSeek (OpenAI-compatible) ---
    "deepseek-v4-pro": {                        # VERIFY model ID string
        "provider": "deepseek",
        "cost_per_m_input": 0.435,
        "cost_per_m_output": 0.87,
        "max_context": 1_000_000,
    },
    "deepseek-v4-flash": {                      # VERIFY model ID string
        "provider": "deepseek",
        "cost_per_m_input": 0.14,
        "cost_per_m_output": 0.28,
        "max_context": 1_000_000,
    },
    # --- Zhipu AI / GLM (OpenAI-compatible) ---
    "glm-5.1": {                                # VERIFY model ID string
        "provider": "glm",
        "cost_per_m_input": 1.00,
        "cost_per_m_output": 4.00,
        "max_context": 202_752,
    },
}

# Adaptive cache similarity thresholds per intent category.
# Higher = stricter (fewer false hits).  Values tuned on production data.
CACHE_THRESHOLDS_BY_CATEGORY: dict[str, float] = {
    "code":         0.97,
    "deploy":       0.95,
    "note":         0.95,
    "research":     0.93,  # paraphrases of the same tech question share the same answer
    "lookup":       0.88,  # factual Q&A — word-order variants are safe hits
    "conversation": 0.93,
    "creative":     0.91,
}

# Temperature presets (deterministic → creative)
TEMP_PRECISE: float  = 0.10
TEMP_BALANCED: float = 0.40
TEMP_CREATIVE: float = 0.65

CATEGORY_TEMP_MAP: dict[str, float] = {
    "code":         TEMP_PRECISE,
    "deploy":       TEMP_PRECISE,
    "note":         TEMP_PRECISE,
    "lookup":       TEMP_BALANCED,
    "research":     TEMP_BALANCED,
    "conversation": TEMP_BALANCED,
    "creative":     TEMP_CREATIVE,
}


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

def load_toml_config() -> dict[str, Any]:
    """
    Load and merge TOML config files, returning a flat dict of Settings field
    names (matching the flat Settings class) ready to pass as init_kwargs.

    Resolution order (later overrides earlier):
      1. ~/.mullm/config.toml  (user global)
      2. mullm.toml in cwd     (project-local)
      3. Path from MULLM_CONFIG_PATH env var (explicit override)
    """
    import tomllib
    def _load(p):
        return tomllib.loads(p.read_text(encoding="utf-8"))  # no TOML support on old Python without tomli installed

    candidates: list[Path] = []

    # 1. User global
    user_global = Path.home() / ".mullm" / "config.toml"
    if user_global.exists():
        candidates.append(user_global)

    # 2. Project-local (cwd)
    project_local = Path.cwd() / "mullm.toml"
    if project_local.exists():
        candidates.append(project_local)

    # 3. Explicit override via env var (read raw to avoid chicken-and-egg)
    config_path_env = os.environ.get("MULLM_CONFIG_PATH", "").strip()
    if config_path_env:
        explicit = Path(config_path_env)
        if explicit.exists():
            candidates.append(explicit)
        else:
            import warnings
            warnings.warn(
                f"MULLM_CONFIG_PATH={config_path_env!r} does not exist; ignoring.",
                stacklevel=2,
            )

    merged: dict[str, Any] = {}
    for path in candidates:
        try:
            data = _load(path)
            merged = _deep_merge(merged, data)
        except Exception as exc:  # noqa: BLE001
            import warnings
            warnings.warn(f"Could not load TOML config {path}: {exc}", stacklevel=2)

    return _flatten_toml(merged)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*; override wins on conflicts."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _flatten_toml(toml: dict[str, Any]) -> dict[str, Any]:
    """
    Map the nested TOML structure onto the flat Settings field names.

    TOML section → Settings field mapping:
      [core]
        mode              → mullm_mode
        local_first       → (informational only; no Settings field yet)
        port              → port
        log_query_content → log_query_content
      [core.budget]
        warn_usd          → budget_warn
        moderate_usd      → budget_moderate
        hard_usd          → budget_hard
      [inference.ollama]
        base_url          → ollama_base_url
        default_model     → ollama_model
        keepalive         → (informational; mapped to ollama_keep_alive if numeric)
      [inference.backends]
        priority          → local_backend_priority
      [inference.vllm]
        base_url          → vllm_base_url
        model             → vllm_model
      [inference.tabbyapi]
        base_url          → tabbyapi_base_url
        model             → tabbyapi_model
      [inference.litellm]
        base_url          → litellm_base_url
        model             → litellm_model
      [inference.llamacpp]
        model_path        → llamacpp_model_path
        n_ctx             → llamacpp_n_ctx
        n_gpu_layers      → llamacpp_n_gpu_layers
      [inference.exllamav2]
        model_path        → exllamav2_model_path
      [inference.mlx]
        model_path        → mlx_model_path
      [cloud]
        anthropic_default_model → cloud_cheap_model_anthropic
        openai_default_model    → cloud_cheap_model_openai
        google_default_model    → cloud_cheap_model_google
      [cache]
        similarity_threshold → cache_cosine_threshold
        max_entries          → (informational; no Settings field yet)
      [studio]
        comfyui_base_url     → comfyui_base_url
      [studio.assets]
        root                 → asset_root
        storage_backend      → asset_storage_backend
        compression          → asset_compression
        s3_bucket            → asset_s3_bucket
        azure_container      → asset_azure_container
      [language]
        enabled              → enabled_languages_raw
    """
    out: dict[str, Any] = {}

    core = toml.get("core", {})
    if "mode" in core:
        out["mullm_mode"] = core["mode"]
    if "port" in core:
        out["port"] = core["port"]
    if "log_query_content" in core:
        out["log_query_content"] = core["log_query_content"]
    if "remote_access" in core:
        out["remote_access"] = core["remote_access"]

    budget = core.get("budget", {})
    if "warn_usd" in budget:
        out["budget_warn"] = budget["warn_usd"]
    if "moderate_usd" in budget:
        out["budget_moderate"] = budget["moderate_usd"]
    if "hard_usd" in budget:
        out["budget_hard"] = budget["hard_usd"]

    inference = toml.get("inference", {})
    backends = inference.get("backends", {})
    if "priority" in backends:
        priority = backends["priority"]
        out["local_backend_priority"] = ",".join(priority) if isinstance(priority, list) else str(priority)

    ollama = inference.get("ollama", {})
    if "base_url" in ollama:
        out["ollama_base_url"] = ollama["base_url"]
    if "default_model" in ollama:
        out["ollama_model"] = ollama["default_model"]
    if "keepalive" in ollama:
        # Convert "30m" → seconds if string, else use as-is
        ka = ollama["keepalive"]
        if isinstance(ka, str) and ka.endswith("m"):
            try:
                out["ollama_keep_alive"] = int(ka[:-1]) * 60
            except ValueError:
                pass
        elif isinstance(ka, int):
            out["ollama_keep_alive"] = ka

    for section, fields in {
        "vllm": {"base_url": "vllm_base_url", "model": "vllm_model"},
        "tabbyapi": {"base_url": "tabbyapi_base_url", "api_key": "tabbyapi_api_key", "model": "tabbyapi_model"},
        "litellm": {"base_url": "litellm_base_url", "api_key": "litellm_api_key", "model": "litellm_model"},
        "llamacpp": {
            "model_path": "llamacpp_model_path",
            "n_ctx": "llamacpp_n_ctx",
            "n_gpu_layers": "llamacpp_n_gpu_layers",
        },
        "exllamav2": {"model_path": "exllamav2_model_path"},
        "mlx": {"model_path": "mlx_model_path"},
    }.items():
        values = inference.get(section, {})
        for toml_key, field_name in fields.items():
            if toml_key in values:
                out[field_name] = values[toml_key]

    cloud = toml.get("cloud", {})
    if "anthropic_default_model" in cloud:
        out["cloud_cheap_model_anthropic"] = cloud["anthropic_default_model"]
    if "openai_default_model" in cloud:
        out["cloud_cheap_model_openai"] = cloud["openai_default_model"]
    if "google_default_model" in cloud:
        out["cloud_cheap_model_google"] = cloud["google_default_model"]

    cache = toml.get("cache", {})
    if "similarity_threshold" in cache:
        out["cache_cosine_threshold"] = cache["similarity_threshold"]

    modules = toml.get("modules", {})
    if "enable_studio" in modules:
        out["enable_studio"] = modules["enable_studio"]
    elif "studio" in modules:
        out["enable_studio"] = modules["studio"]

    studio = toml.get("studio", {})
    if "comfyui_base_url" in studio:
        out["comfyui_base_url"] = studio["comfyui_base_url"]
    assets = studio.get("assets", {})
    if "root" in assets:
        out["asset_root"] = assets["root"]
    if "storage_backend" in assets:
        out["asset_storage_backend"] = assets["storage_backend"]
    if "external_base_url" in assets:
        out["asset_external_base_url"] = assets["external_base_url"]
    if "compression" in assets:
        out["asset_compression"] = assets["compression"]
    if "max_local_gb" in assets:
        out["asset_max_local_gb"] = assets["max_local_gb"]
    if "s3_bucket" in assets:
        out["asset_s3_bucket"] = assets["s3_bucket"]
    if "azure_container" in assets:
        out["asset_azure_container"] = assets["azure_container"]

    language = toml.get("language", {})
    if "enabled" in language:
        enabled = language["enabled"]
        out["enabled_languages_raw"] = ",".join(enabled) if isinstance(enabled, list) else str(enabled)

    classifier = toml.get("classifier", {})
    if "model_path" in classifier:
        out["classifier_model_path"] = classifier["model_path"]
    if "backend" in classifier:
        out["classifier_backend"] = classifier["backend"]
    if "confidence_threshold" in classifier:
        out["classifier_confidence_threshold"] = float(classifier["confidence_threshold"])
    if "http_url" in classifier:
        out["classifier_http_url"] = classifier["http_url"]
    if "onnx_model_path" in classifier:
        out["classifier_onnx_model_path"] = classifier["onnx_model_path"]
    if "onnx_tokenizer_path" in classifier:
        out["classifier_onnx_tokenizer_path"] = classifier["onnx_tokenizer_path"]

    return out


# ---------------------------------------------------------------------------
# Custom TOML settings source (inserts below env vars in pydantic-settings)
# ---------------------------------------------------------------------------

class _TomlSettingsSource(InitSettingsSource):
    """
    Pydantic-settings source that loads from TOML files.
    Sits below env var sources so env vars always win.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls, init_kwargs=load_toml_config())

    def __repr__(self) -> str:
        return "TomlSettingsSource(~/.mullm/config.toml, mullm.toml, $MULLM_CONFIG_PATH)"


# ---------------------------------------------------------------------------
# Settings (pydantic-settings v2)
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("MULLM_ENV_FILE", ".env"),
        env_prefix="MULLM_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Server ───────────────────────────────────────────────
    port: int = 6856
    version: str = "0.9.0"
    dev_mode: bool = True          # When True, auth is skipped; set False in prod
    server_reload: bool = False    # Development hot-reload; keep off for installed/user runs
    log_level: str = "INFO"
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None
    ssl_ca_certs: str | None = None
    mtls_enabled: bool = False
    tls_min_version: str = "TLSv1.3"
    security_contact_email: str = "contact@mullm.com"
    auto_generate_cert: bool = True
    # Bind to 0.0.0.0 (all interfaces) instead of 127.0.0.1 (localhost only).
    # Required if you want to reach mullm from your phone or another machine
    # on the same network.  Set MULLM_REMOTE_ACCESS=true or remote_access=true
    # in mullm.toml → [core].
    remote_access: bool = False

    # ── Mode ─────────────────────────────────────────────────
    mullm_mode: Literal["single_user", "team"] = "single_user"
    ui_mode: Literal["regular", "demo", "dev"] = "regular"
    enable_studio: bool = False
    groundtruth_mode: Literal["registry", "legacy"] = "registry"
    enabled_languages_raw: str = "en"

    # ── Config path (MULLM_CONFIG_PATH) ──────────────────────
    # Read early via os.environ in load_toml_config(); stored here for
    # introspection only.
    config_path: str = ""

    # ── Auth ─────────────────────────────────────────────────
    api_key: str | None = None  # Bearer token; required in prod (dev_mode=False)

    # ── CORS ─────────────────────────────────────────────────
    # Comma-separated list of allowed origins; default localhost only
    cors_origins_raw: str = "http://localhost:6856,http://127.0.0.1:6856"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    # ── Rate limiting ─────────────────────────────────────────
    rate_limit_per_minute: int = 40
    ip_rate_limit_per_minute: int = 120

    # ── Enterprise security ───────────────────────────────────
    require_custom_header: str | None = None  # if set, all requests must include X-Mullm-Token: <value>
    require_referer_match: bool = False
    allow_mcp_requests: bool = False
    allow_a2a_requests: bool = False
    allow_offbox_mcp_a2a: bool = False
    allowed_outbound_domains_raw: str = ""
    sandbox_mode: Literal["off", "workspace", "container"] = "workspace"
    sandbox_root: str = ""
    sandbox_allow_network: bool = False
    vram_limit_gb: float = 0.0          # 0 = auto/no explicit muLLM cap
    vram_reserve_gb: float = 1.0        # keep free for desktop/other workloads
    cache_max_gb: float = 10.0
    cache_eviction_policy: Literal["lru", "ttl", "manual"] = "lru"

    @property
    def allowed_outbound_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_outbound_domains_raw.split(",") if d.strip()]

    # ── Ollama ───────────────────────────────────────────────
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "MULLM_OLLAMA_BASE_URL"),
    )
    ollama_model: str = Field(
        default="qwen3-coder:30b",
        validation_alias=AliasChoices("CODE_MODEL", "OLLAMA_MODEL", "MULLM_OLLAMA_MODEL"),
    )
    ollama_vision_model: str = Field(
        default="qwen2.5vl:7b",
        validation_alias=AliasChoices("VISION_MODEL", "MULLM_OLLAMA_VISION_MODEL"),
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        validation_alias=AliasChoices("EMBED_MODEL", "MULLM_OLLAMA_EMBED_MODEL"),
    )
    ollama_num_ctx: int = Field(
        default=65536,
        validation_alias=AliasChoices("OLLAMA_NUM_CTX", "MULLM_OLLAMA_NUM_CTX"),
    )
    ollama_keep_alive: int = Field(
        default=5400,
        validation_alias=AliasChoices("OLLAMA_KEEP_ALIVE", "MULLM_OLLAMA_KEEP_ALIVE"),
    )   # seconds to keep model in VRAM
    ollama_concurrency: int = Field(
        default=1,
        validation_alias=AliasChoices("OLLAMA_NUM_PARALLEL", "MULLM_OLLAMA_CONCURRENCY"),
    )     # 30b+9b cannot coexist in 32 GB
    local_backend_priority: str = Field(
        default="ollama,tabbyapi,vllm,sglang,llamacpp,mlx,exllamav2",
        validation_alias=AliasChoices("LOCAL_BACKEND_PRIORITY", "MULLM_LOCAL_BACKEND_PRIORITY"),
    )
    vllm_base_url: str = Field(default="", validation_alias=AliasChoices("VLLM_BASE_URL", "MULLM_VLLM_BASE_URL"))
    vllm_model: str = Field(default="default", validation_alias=AliasChoices("VLLM_MODEL", "MULLM_VLLM_MODEL"))
    sglang_base_url: str = Field(default="", validation_alias=AliasChoices("SGLANG_BASE_URL", "MULLM_SGLANG_BASE_URL"))
    sglang_model: str = Field(default="default", validation_alias=AliasChoices("SGLANG_MODEL", "MULLM_SGLANG_MODEL"))
    tabbyapi_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("TABBYAPI_BASE_URL", "TABBY_BASE_URL", "MULLM_TABBYAPI_BASE_URL"),
    )
    tabbyapi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TABBYAPI_API_KEY", "TABBY_API_KEY", "MULLM_TABBYAPI_API_KEY"),
    )
    tabbyapi_model: str = Field(
        default="default",
        validation_alias=AliasChoices("TABBYAPI_MODEL", "TABBY_MODEL", "MULLM_TABBYAPI_MODEL"),
    )
    litellm_base_url: str = Field(default="", validation_alias=AliasChoices("LITELLM_BASE_URL", "MULLM_LITELLM_BASE_URL"))
    litellm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LITELLM_API_KEY", "MULLM_LITELLM_API_KEY"))
    litellm_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("LITELLM_MODEL", "MULLM_LITELLM_MODEL"))
    llamacpp_model_path: str = Field(default="", validation_alias=AliasChoices("LLAMACPP_MODEL_PATH", "MULLM_LLAMACPP_MODEL_PATH"))
    llamacpp_n_ctx: int = Field(default=8192, validation_alias=AliasChoices("LLAMACPP_N_CTX", "MULLM_LLAMACPP_N_CTX"))
    llamacpp_n_gpu_layers: int = Field(default=-1, validation_alias=AliasChoices("LLAMACPP_N_GPU_LAYERS", "MULLM_LLAMACPP_N_GPU_LAYERS"))
    exllamav2_model_path: str = Field(default="", validation_alias=AliasChoices("EXLLAMAV2_MODEL_PATH", "MULLM_EXLLAMAV2_MODEL_PATH"))
    mlx_model_path: str = Field(default="", validation_alias=AliasChoices("MLX_MODEL_PATH", "MULLM_MLX_MODEL_PATH"))
    embed_concurrency: int = Field(
        default=2,
        validation_alias=AliasChoices("EMBED_CONCURRENCY", "MULLM_EMBED_CONCURRENCY"),
    )
    comfyui_base_url: str = "http://127.0.0.1:8188"
    asset_root: str = Field(default_factory=lambda: str(_default_asset_root()))
    asset_storage_backend: Literal["local", "s3", "azure_blob", "external_api"] = "local"
    asset_external_base_url: str = ""
    asset_compression: Literal["none", "gzip", "brotli", "draco", "meshopt", "ktx2", "auto"] = "auto"
    asset_max_local_gb: float = 50.0
    asset_s3_bucket: str = ""
    asset_azure_container: str = ""
    redis_url: str = Field(
        default="",
        validation_alias=AliasChoices("MULLM_REDIS_URL", "REDIS_URL", "MULLM_CACHE_REDIS_URL"),
    )
    tripo_base_url: str = "https://api.3daistudio.com"
    rodin_base_url: str = "https://api.hyper3d.com"
    sana_wm_base_url: str = ""
    sana_wm_local_path: str = ""

    # ── Cloud API keys ────────────────────────────────────────
    # Accept both bare provider key names and MULLM_-prefixed variants.
    # pydantic-settings env_prefix applies to the field name, but
    # validation_alias lets us also accept the bare name directly.
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ANTHROPIC_API_KEY",
            "MULLM_ANTHROPIC_API_KEY",
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENAI_API_KEY",
            "MULLM_OPENAI_API_KEY",
        ),
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_API_KEY",
            "MULLM_GOOGLE_API_KEY",
        ),
    )
    cerebras_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CEREBRAS_API_KEY",
            "MULLM_CEREBRAS_API_KEY",
        ),
    )
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEEPSEEK_API_KEY",
            "MULLM_DEEPSEEK_API_KEY",
        ),
    )
    glm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GLM_API_KEY",
            "ZHIPU_API_KEY",
            "MULLM_GLM_API_KEY",
        ),
    )
    tripo_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRIPO_API_KEY",
            "MULLM_TRIPO_API_KEY",
        ),
    )
    rodin_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "RODIN_API_KEY",
            "HYPER3D_API_KEY",
            "MULLM_RODIN_API_KEY",
        ),
    )
    sana_wm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SANA_WM_API_KEY",
            "MULLM_SANA_WM_API_KEY",
        ),
    )
    meshy_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MESHY_API_KEY",
            "MULLM_MESHY_API_KEY",
        ),
    )
    civitai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CIVITAI_API_KEY",
            "CIVIT_AI_API_KEY",
            "MULLM_CIVITAI_API_KEY",
        ),
    )

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "google_api_key",
        "cerebras_api_key",
        "deepseek_api_key",
        "glm_api_key",
        "tripo_api_key",
        "rodin_api_key",
        "sana_wm_api_key",
        "meshy_api_key",
        "civitai_api_key",
        mode="before",
    )
    @classmethod
    def _resolve_configured_secret_reference(cls, v: Any) -> Any:
        return _resolve_secret_reference(v)

    # Cloud model routing
    cloud_cheap_model_anthropic: str  = "claude-haiku-4-5"
    cloud_full_model_anthropic: str   = "claude-sonnet-4-6"
    cloud_power_model_anthropic: str  = "claude-opus-4-7"
    # When True, Claude Fable 5 replaces the Opus power model (top tier and
    # WITH RICE). Toggled from /setup ("fable_top_tier"); off = exact pre-0.9
    # behavior (Opus). Fable requests carry a server-side fallback to Opus so
    # a safety refusal degrades gracefully instead of failing the query.
    fable_top_tier: bool = True
    cloud_cheap_model_openai: str     = "gpt-4o-mini"
    cloud_full_model_openai: str      = "gpt-5.4-pro"
    cloud_power_model_openai: str     = "gpt-5.5"
    cloud_cheap_model_google: str     = "gemini-2.5-flash"
    cloud_full_model_google: str      = "gemini-3.1-pro-preview"
    cloud_power_model_google: str     = "gemini-3.1-pro-preview"
    cloud_cheap_model_cerebras: str   = "gpt-oss-120b"
    cloud_full_model_cerebras: str    = "gpt-oss-120b"
    cloud_power_model_cerebras: str   = "gpt-oss-120b"
    cloud_cheap_model_deepseek: str   = "deepseek-v4-flash"
    cloud_full_model_deepseek: str    = "deepseek-v4-pro"
    cloud_power_model_deepseek: str   = "deepseek-v4-pro"
    cloud_cheap_model_glm: str        = "glm-5.1"
    cloud_full_model_glm: str         = "glm-5.1"
    cloud_power_model_glm: str        = "glm-5.1"
    preferred_cloud_provider: str     = "anthropic"  # anthropic | openai | google | cerebras | deepseek | glm

    # ── Budget thresholds ($) ────────────────────────────────
    budget_warn: float   = 7.00
    budget_moderate: float = 10.00
    budget_hard: float   = 50.00
    budget_weekly: float = 20.00

    # ── Vector cache ──────────────────────────────────────────
    semantic_cache_backend: Literal["sqlite", "chroma", "off"] = "sqlite"
    cache_cosine_threshold: float = 0.98   # global default; per-category overrides in dict above
    cache_ttl_days: int = 30
    log_query_content: bool = False         # when False, omit query/response from semantic cache

    # ── Request deduplication ─────────────────────────────────
    dedup_window_seconds: float = 2.0

    # ── Paths ─────────────────────────────────────────────────
    project_root: Path = Path(__file__).parent.parent
    cache_dir: Path = Field(default_factory=_default_cache_dir)
    scoring_log: Path = Field(default_factory=_default_scoring_log)

    # ── Intent classifier ─────────────────────────────────────
    classifier_backend: Literal["auto", "rules", "deberta", "http", "onnx"] = "auto"
    classifier_model_path: str = ""        # local DeBERTa/transformers path; empty = conventional fallback
    classifier_confidence_threshold: float = 0.80
    classifier_http_url: str = ""          # POST {"content": "..."}; expects category/complexity/confidence JSON
    classifier_http_timeout_seconds: float = 0.35
    classifier_onnx_model_path: str = ""
    classifier_onnx_tokenizer_path: str = ""
    classifier_retrain_enabled: bool = False
    classifier_retrain_schedule: str = "off"  # off | hourly | daily | weekly | cron:<expr>
    classifier_retrain_data_path: str = ""
    classifier_retrain_output_path: str = ""
    classifier_retrain_min_samples: int = 100
    classifier_retrain_dry_run: bool = True
    classifier_retrain_mode: Literal["intent", "binary"] = "intent"

    # ── Privacy ───────────────────────────────────────────────
    data_retention_days: int = 90

    # ── Commit attribution ────────────────────────────────────
    commit_attribution_mode: Literal["auto", "always", "never"] = "never"
    commit_attribution_name: str = "muLLM"
    commit_attribution_email: str = "noreply@mullm.local"

    # ── Misc ──────────────────────────────────────────────────
    request_timeout_seconds: int = 600     # 10-minute hard limit per request

    @field_validator("port")
    @classmethod
    def _validate_port(cls, v: int) -> int:
        if not (1024 <= v <= 65535):
            raise ValueError(f"Port must be 1024–65535, got {v}")
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: InitSettingsSource,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        # Priority (left = highest):
        #   init_args > env vars > .env file > TOML files > built-in defaults
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _TomlSettingsSource(settings_cls),
            file_secret_settings,
        )


# Module-level singleton — import this everywhere
settings = Settings()

# Ensure cache directory exists at import time
settings.cache_dir.mkdir(parents=True, exist_ok=True)
