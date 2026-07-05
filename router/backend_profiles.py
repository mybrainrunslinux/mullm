"""Local backend setup profiles for beginner, advanced, and nightly users."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BackendProfile:
    id: str
    label: str
    channel: str
    audience: str
    stable: bool
    backend: str
    model: str
    context_tokens: int
    vram_target_gb: int
    notes: list[str]
    env: dict[str, str]
    commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES: tuple[BackendProfile, ...] = (
    BackendProfile(
        id="beginner_cache_groundtruth",
        label="No local model required",
        channel="stable",
        audience="beginner",
        stable=True,
        backend="groundtruth_cache",
        model="none",
        context_tokens=0,
        vram_target_gb=0,
        notes=[
            "Use muLLM as a groundtruth, semantic cache, classifier, dashboard, and OpenAI-compatible policy layer.",
            "No cloud provider is called unless cloud toggles and keys are configured.",
        ],
        env={
            "MULLM_PROVIDER_LOCAL": "false",
            "MULLM_CLOUD_TEXT": "false",
        },
        commands=[],
    ),
    BackendProfile(
        id="ollama_safe_8gb",
        label="Ollama safe local coding",
        channel="stable",
        audience="beginner",
        stable=True,
        backend="ollama",
        model="qwen2.5-coder:7b",
        context_tokens=32768,
        vram_target_gb=8,
        notes=[
            "Best first-run path for 8-12GB GPUs and Windows users.",
            "Pull nomic-embed-text for semantic cache embeddings.",
        ],
        env={
            "MULLM_OLLAMA_MODEL": "qwen2.5-coder:7b",
            "MULLM_OLLAMA_NUM_CTX": "32768",
            "MULLM_VRAM_LIMIT_GB": "8",
        },
        commands=[
            "ollama pull qwen2.5-coder:7b",
            "ollama pull nomic-embed-text",
        ],
    ),
    BackendProfile(
        id="ollama_omnicoder_9b_fast",
        label="OmniCoder 9B fast local coding",
        channel="advanced",
        audience="coder",
        stable=True,
        backend="ollama",
        model="omnicoder:9b",
        context_tokens=65536,
        vram_target_gb=10,
        notes=[
            "Fast local-code path for routine edits, cache fill, and low/medium complexity PR-Gauntlet tasks.",
            "Keep this as the first quality/speed comparison against the 30B MoE baseline.",
        ],
        env={
            "MULLM_OLLAMA_MODEL": "omnicoder:9b",
            "MULLM_OLLAMA_NUM_CTX": "65536",
            "MULLM_VRAM_LIMIT_GB": "10",
        },
        commands=[
            "ollama pull omnicoder:9b",
            "ollama pull nomic-embed-text",
        ],
    ),
    BackendProfile(
        id="ollama_moe_30b_24gb",
        label="Current 30B MoE coder baseline",
        channel="advanced",
        audience="coder",
        stable=True,
        backend="ollama",
        model="qwen3-coder-65k:latest",
        context_tokens=65536,
        vram_target_gb=24,
        notes=[
            "Use this as the parity baseline for PR-Gauntlet, MultiPL-E subset, and normal coding work.",
            "Clamp muLLM to 24GB on a 32GB card when ComfyUI or games share the GPU.",
        ],
        env={
            "MULLM_OLLAMA_MODEL": "qwen3-coder-65k:latest",
            "MULLM_OLLAMA_NUM_CTX": "65536",
            "MULLM_VRAM_LIMIT_GB": "24",
        },
        commands=[
            "ollama pull qwen3-coder-65k:latest",
            "ollama pull nomic-embed-text",
        ],
    ),
    BackendProfile(
        id="tabbyapi_moe_30b_exllamav3",
        label="30B MoE coder via TabbyAPI / ExLlamaV3",
        channel="experimental",
        audience="researcher",
        stable=False,
        backend="tabbyapi",
        model="configured-in-tabby-30b-moe",
        context_tokens=131072,
        vram_target_gb=24,
        notes=[
            "Best near-term ExLlamaV3 path: let TabbyAPI own model loading and expose an OpenAI-compatible endpoint.",
            "Use this to compare tok/s and coding quality against Ollama with the same prompts and benchmark harness.",
        ],
        env={
            "MULLM_LOCAL_BACKEND_PRIORITY": "tabbyapi,ollama,vllm,llamacpp",
            "TABBYAPI_BASE_URL": "http://127.0.0.1:5000/v1",
            "TABBYAPI_MODEL": "configured-in-tabby-30b-moe",
            "MULLM_VRAM_LIMIT_GB": "24",
        },
        commands=[],
    ),
    BackendProfile(
        id="tabbyapi_qwen35_a3b_moe_probe",
        label="Qwen 35B A3B MoE probe via TabbyAPI",
        channel="experimental",
        audience="researcher",
        stable=False,
        backend="tabbyapi",
        model="configured-in-tabby-qwen35-a3b",
        context_tokens=131072,
        vram_target_gb=24,
        notes=[
            "Quality probe only until benchmarked; keep disabled for default routing if it underperforms your 30B coder model.",
            "Good candidate for cost-of-pass comparison because active parameters are small but behavior may vary by quant.",
        ],
        env={
            "MULLM_LOCAL_BACKEND_PRIORITY": "tabbyapi,ollama,vllm,llamacpp",
            "TABBYAPI_BASE_URL": "http://127.0.0.1:5000/v1",
            "TABBYAPI_MODEL": "configured-in-tabby-qwen35-a3b",
            "MULLM_VRAM_LIMIT_GB": "24",
        },
        commands=[],
    ),
    BackendProfile(
        id="llamacpp_qwen36_27b_q4km",
        label="Qwen3.6-27B dense GGUF",
        channel="experimental",
        audience="researcher",
        stable=False,
        backend="llamacpp",
        model="Qwen3.6-27B-Q4_K_M.gguf",
        context_tokens=131072,
        vram_target_gb=24,
        notes=[
            "Experimental dense-model comparison target for coding quality and tok/s.",
            "Use a recent llama.cpp build; MTP flags should stay behind the nightly toggle until your local build supports them.",
        ],
        env={
            "LLAMACPP_MODEL_PATH": "/models/Qwen3.6-27B-Q4_K_M.gguf",
            "LLAMACPP_N_CTX": "131072",
            "LLAMACPP_N_GPU_LAYERS": "-1",
            "MULLM_VRAM_LIMIT_GB": "24",
        },
        commands=[
            "llama-server -m /models/Qwen3.6-27B-Q4_K_M.gguf -c 131072 -ngl -1 --host 127.0.0.1 --port 8088",
        ],
    ),
    BackendProfile(
        id="llamacpp_qwen36_27b_mtp_nightly",
        label="Qwen3.6-27B MTP nightly",
        channel="nightly",
        audience="researcher",
        stable=False,
        backend="llamacpp",
        model="Qwen3.6-27B-MTP-Q4_K_M.gguf",
        context_tokens=131072,
        vram_target_gb=24,
        notes=[
            "Nightly-only profile for llama.cpp main/fork builds with MTP enabled.",
            "Keep this separate from the beginner path because CLI flags and model files are still changing.",
        ],
        env={
            "LLAMACPP_MODEL_PATH": "/models/Qwen3.6-27B-MTP-Q4_K_M.gguf",
            "LLAMACPP_N_CTX": "131072",
            "LLAMACPP_N_GPU_LAYERS": "-1",
            "MULLM_EXPERIMENTAL_CONFIGS": "true",
            "MULLM_NIGHTLY_CONFIGS": "true",
        },
        commands=[
            "llama-server -m /models/Qwen3.6-27B-MTP-Q4_K_M.gguf -c 131072 -ngl -1 --host 127.0.0.1 --port 8088 --spec-type draft-mtp --spec-draft-n-max 2",
        ],
    ),
    BackendProfile(
        id="tabbyapi_exllamav3",
        label="TabbyAPI / ExLlamaV3 server",
        channel="experimental",
        audience="researcher",
        stable=False,
        backend="tabbyapi",
        model="configured-in-tabby",
        context_tokens=131072,
        vram_target_gb=24,
        notes=[
            "Use this for ExLlamaV3 tok/s comparisons while keeping muLLM on an OpenAI-compatible contract.",
            "Configure TABBYAPI_BASE_URL and TABBYAPI_MODEL after TabbyAPI is running.",
        ],
        env={
            "TABBYAPI_BASE_URL": "http://127.0.0.1:5000/v1",
            "TABBYAPI_MODEL": "default",
            "MULLM_VRAM_LIMIT_GB": "24",
        },
        commands=[],
    ),
)


def backend_profiles(include_experimental: bool = False, include_nightly: bool = False) -> list[dict[str, Any]]:
    visible: list[BackendProfile] = []
    for profile in PROFILES:
        if profile.channel == "nightly" and not include_nightly:
            continue
        if profile.channel == "experimental" and not include_experimental:
            continue
        visible.append(profile)
    return [profile.to_dict() for profile in visible]
