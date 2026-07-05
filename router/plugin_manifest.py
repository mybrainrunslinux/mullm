"""Capability/plugin manifest registry for muLLM UI and setup surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Permission = Literal["local_files", "network_outbound", "cloud_cost", "api_server", "gpu", "secrets"]


@dataclass(frozen=True)
class CapabilityManifest:
    id: str
    label: str
    group: str
    status: Literal["core", "available", "provider_gated"]
    pages: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    permissions: list[Permission] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


CAPABILITIES: list[CapabilityManifest] = [
    CapabilityManifest(
        id="chat",
        label="Chat",
        group="core",
        status="core",
        pages=["/chat", "/dashboard"],
        endpoints=["/query", "/query/stream", "/v1/chat/completions", "/v1/models"],
        permissions=["api_server"],
    ),
    CapabilityManifest(
        id="research",
        label="Research",
        group="research",
        status="available",
        pages=["/research", "/review", "/bench", "/megabench", "/onnx", "/compare", "/compare3d", "/dataviz", "/pareto", "/minitest"],
        endpoints=["/api/research/*", "/api/review/*", "/api/bench/*", "/api/onnx/*", "/api/compare/*"],
        dependencies=["chromadb"],
        permissions=["local_files", "network_outbound", "cloud_cost"],
        notes="Benchmark and ONNX surfaces are live; archive-backed endpoints return explicit archive status when no local run exists.",
    ),
    CapabilityManifest(
        id="code",
        label="Code",
        group="dev",
        status="available",
        pages=["/code", "/tests", "/terminalbench"],
        endpoints=["/api/understand", "/understand"],
        permissions=["local_files", "api_server"],
    ),
    CapabilityManifest(
        id="api",
        label="API",
        group="core",
        status="core",
        pages=["/setup", "/mcp", "/a2a", "/rpc"],
        endpoints=["/v1/*", "/api/setup/*", "/api/provider-catalog", "/api/plugins"],
        env=["MULLM_API_KEY", "MULLM_CORS_ORIGINS", "MULLM_REMOTE_ACCESS"],
        permissions=["api_server", "network_outbound", "secrets"],
    ),
    CapabilityManifest(
        id="image",
        label="Image",
        group="studio",
        status="available",
        pages=["/image", "/comfyui", "/textures"],
        endpoints=["/api/comfyui/status"],
        env=["COMFYUI_BASE_URL", "OPENAI_API_KEY", "STABILITY_API_KEY"],
        dependencies=["comfyui"],
        permissions=["gpu", "local_files", "cloud_cost"],
    ),
    CapabilityManifest(
        id="video",
        label="Video",
        group="studio",
        status="provider_gated",
        pages=["/video", "/videoeditor"],
        endpoints=["/api/video", "/api/video/generate", "/api/video/list", "/api/video/stitch", "/api/video/upscale"],
        env=["KLING_API_KEY", "VEO_API_KEY", "SEEDANCE_API_KEY"],
        dependencies=["comfyui"],
        permissions=["cloud_cost", "local_files"],
        notes="Local ComfyUI video generation is available; stitch/upscale/cloud providers require their adapters or API keys.",
    ),
    CapabilityManifest(
        id="3d",
        label="3D",
        group="studio",
        status="available",
        pages=["/3d", "/studio", "/assets", "/asset-manager", "/rigs", "/swords"],
        endpoints=["/api/3d/*"],
        env=["MESHY_API_KEY", "TOPOLOGYAI_API_KEY"],
        permissions=["cloud_cost", "local_files", "gpu"],
    ),
    CapabilityManifest(
        id="knowledge",
        label="Knowledge",
        group="core",
        status="available",
        pages=["/research"],
        endpoints=["/api/joplin/*", "/api/obsidian/*"],
        env=["JOPLIN_TOKEN", "JOPLIN_BASE_URL", "OBSIDIAN_VAULT_PATH"],
        dependencies=["chromadb"],
        permissions=["local_files"],
    ),
]


def capability_manifests(group: str | None = None) -> list[dict]:
    manifests = CAPABILITIES
    if group:
        manifests = [manifest for manifest in manifests if manifest.group == group]
    return [manifest.to_dict() for manifest in manifests]
