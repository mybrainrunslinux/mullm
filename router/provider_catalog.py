"""Provider capability catalog shared by setup, docs, and discovery."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    kind: str
    env: list[str]
    status: str
    capabilities: list[str]
    module: str = "core"
    api_style: str = "openai-compatible"
    notes: str = ""
    docs_url: str = ""
    safety_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        id="ollama",
        name="Ollama",
        kind="local_llm",
        env=["OLLAMA_BASE_URL", "MULLM_OLLAMA_MODEL"],
        status="active",
        module="core",
        api_style="ollama",
        capabilities=["chat", "streaming", "embeddings", "vision"],
        notes="Primary local free tier.",
        docs_url="https://ollama.com",
    ),
    ProviderSpec(
        id="anthropic",
        name="Anthropic",
        kind="cloud_llm",
        env=["ANTHROPIC_API_KEY"],
        status="active",
        module="core",
        api_style="native",
        capabilities=["chat", "streaming"],
        notes="Native SDK path in router.cloud and registry.",
    ),
    ProviderSpec(
        id="openai",
        name="OpenAI",
        kind="cloud_llm",
        env=["OPENAI_API_KEY"],
        status="active",
        module="core",
        capabilities=["chat", "streaming", "image"],
    ),
    ProviderSpec(
        id="google",
        name="Google Gemini",
        kind="cloud_llm",
        env=["GOOGLE_API_KEY"],
        status="active",
        module="core",
        capabilities=["chat", "streaming", "video"],
        notes="Gemini text path is active; Veo belongs to studio/video adapter.",
    ),
    ProviderSpec(
        id="deepseek",
        name="DeepSeek",
        kind="cloud_llm",
        env=["DEEPSEEK_API_KEY"],
        status="active",
        module="core",
        capabilities=["chat", "code"],
    ),
    ProviderSpec(
        id="openrouter",
        name="OpenRouter",
        kind="meta_router",
        env=["OPENROUTER_API_KEY"],
        status="registered",
        module="core",
        capabilities=["chat", "model_marketplace"],
        notes="Registered backend; route selection needs registry integration.",
    ),
    ProviderSpec(
        id="litellm",
        name="LiteLLM Proxy",
        kind="meta_router",
        env=["LITELLM_BASE_URL", "LITELLM_API_KEY", "LITELLM_MODEL"],
        status="registered",
        module="core",
        capabilities=["chat", "model_marketplace", "fallback"],
        notes="Use as local/team proxy via OpenAI-compatible backend.",
    ),
    ProviderSpec(
        id="vllm",
        name="vLLM",
        kind="self_hosted_llm",
        env=["VLLM_BASE_URL", "VLLM_MODEL"],
        status="registered",
        module="core",
        capabilities=["chat", "streaming"],
    ),
    ProviderSpec(
        id="tabbyapi",
        name="TabbyAPI / ExLlamaV3",
        kind="self_hosted_llm",
        env=["TABBYAPI_BASE_URL", "TABBYAPI_API_KEY", "TABBYAPI_MODEL"],
        status="registered",
        module="core",
        capabilities=["chat", "streaming", "exllamav3", "quantized_local_models"],
        notes="OpenAI-compatible server path for ExLlamaV3-class local inference.",
    ),
    ProviderSpec(
        id="omniroute",
        name="OmniRoute",
        kind="meta_router",
        env=["OMNIROUTE_BASE_URL", "OMNIROUTE_API_KEY", "OMNIROUTE_MODEL"],
        status="custom_adapter",
        module="core",
        capabilities=["chat", "fallback", "compression", "mcp", "a2a"],
        notes="Use the OpenAI-compatible custom backend fields to connect and benchmark against muLLM routing.",
        docs_url="https://github.com/diegosouzapw/OmniRoute",
    ),
    ProviderSpec(
        id="meshy",
        name="Meshy",
        kind="cloud_3d",
        env=["MESHY_API_KEY"],
        status="setup_only",
        module="studio",
        api_style="async-task",
        capabilities=["text_to_3d", "image_to_3d", "refine", "download_glb"],
    ),
    ProviderSpec(
        id="topologyai",
        name="TopologyAI",
        kind="cloud_3d",
        env=["TOPOLOGYAI_API_KEY", "TOPOLOGYAI_BASE_URL"],
        status="custom_adapter",
        module="studio",
        api_style="custom-3d-provider",
        capabilities=["text_to_3d", "image_to_3d"],
        notes="Connect through the custom 3D provider adapter when a compatible endpoint is available.",
    ),
    ProviderSpec(
        id="comfyui",
        name="ComfyUI",
        kind="local_media",
        env=["COMFYUI_BASE_URL"],
        status="partial",
        module="studio",
        api_style="async-task",
        capabilities=["image", "texture", "hunyuan3d", "lora", "workflow_graph"],
        notes="Requires user-managed ComfyUI on port 8188 today.",
    ),
    ProviderSpec(
        id="kling",
        name="Kling",
        kind="cloud_video",
        env=["KLING_API_KEY", "KLING_BASE_URL"],
        status="provider_gated",
        module="studio",
        api_style="async-task",
        capabilities=["text_to_video", "image_to_video", "video_edit"],
        safety_notes=["Require consent checks for likeness, voice, and realistic person generation."],
    ),
    ProviderSpec(
        id="veo",
        name="Google Veo",
        kind="cloud_video",
        env=["GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "VEO_MODEL"],
        status="provider_gated",
        module="studio",
        api_style="vertex-ai",
        capabilities=["text_to_video", "image_to_video", "extend_video", "first_last_frame"],
        docs_url="https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos",
        safety_notes=["Use official Vertex AI path when possible; enforce watermark/provenance policy."],
    ),
    ProviderSpec(
        id="seedance2",
        name="Seedance 2.0",
        kind="cloud_video",
        env=["SEEDANCE_API_KEY", "SEEDANCE_BASE_URL"],
        status="provider_gated",
        module="studio",
        api_style="async-task",
        capabilities=["text_to_video", "image_to_video", "reference_to_video"],
        safety_notes=["Prefer official/contracted API access over reverse-engineered endpoints."],
    ),
]


def provider_catalog() -> list[dict]:
    return [p.to_dict() for p in PROVIDERS]


def providers_by_module(module: str) -> list[dict]:
    return [p.to_dict() for p in PROVIDERS if p.module == module]
