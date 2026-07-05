"""Installable muLLM module registry.

The default install must stay small and reviewable. Larger surfaces such as
Studio are represented here as explicit, opt-in modules so setup can explain
the download/install step before enabling routes or nav.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    name: str
    description: str
    audience: str
    package: str
    extra: str | None
    default_enabled: bool
    requires_download: bool
    installer: str
    size_hint: str
    routes: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    learn_url: str | None = None


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        id="core",
        name="muLLM Core",
        description="Router, classifier, groundtruth, cache, privacy logging, setup, chat, dashboard, and OpenAI-compatible API.",
        audience="researchers, individual users, enterprise evaluators",
        package="mullm",
        extra=None,
        default_enabled=True,
        requires_download=False,
        installer="bundled",
        size_hint="included",
        routes=("/chat", "/dashboard", "/setup", "/privacy", "/security", "/cost", "/performance"),
    ),
    ModuleSpec(
        id="code",
        name="muLLM Code",
        description="CLI orchestration, repo-aware patch workflows, agent integrations, and self-update gates.",
        audience="developers and coding-agent users",
        package="mullm-code",
        extra="code",
        default_enabled=False,
        requires_download=True,
        installer="background-pip-extra",
        size_hint="small; repo tooling only",
        routes=("/dev", "/coverage", "/bench"),
    ),
    ModuleSpec(
        id="studio",
        name="muLLM Studio",
        description="Game, image, video, 3D, audio, ComfyUI, Meshy, Dojo, and reusable game-system surfaces. Includes Kokoro local TTS (free, offline voice synthesis) plus OpenAI and ElevenLabs TTS backends.",
        audience="game developers, media creators, and demos",
        package="mullm-studio",
        extra="studio",
        default_enabled=False,
        requires_download=True,
        installer="background-pip-extra",
        size_hint="larger; may install media tools and workflows",
        routes=("/studio", "/3d", "/comfyui", "/image", "/video", "/musaic", "/tts", "/gamesystems"),
        dependencies=("ffmpeg", "ComfyUI optional", "Ollama or local media backend optional", "espeak-ng (system package — auto-installed for Kokoro TTS)"),
        learn_url="https://0101technology.com/learn/comfyui",
    ),
    ModuleSpec(
        id="bench",
        name="muLLM Bench",
        description="PR-Gauntlet, muPatch, HumanEval, MultiPL-E, benchmark dashboards, and reproducibility artifacts.",
        audience="paper reviewers, researchers, and regression testing",
        package="mullm-bench",
        extra="bench",
        default_enabled=False,
        requires_download=True,
        installer="background-pip-extra",
        size_hint="variable; benchmark datasets and toolchains can be large",
        routes=("/bench", "/megabench", "/review", "/coverage"),
    ),
    ModuleSpec(
        id="enterprise",
        name="muLLM Enterprise",
        description="OIDC/SAML, policy packs, immutable audit exports, DSAR flows, quotas, and managed deployment support.",
        audience="teams and regulated deployments",
        package="mullm-enterprise",
        extra="enterprise",
        default_enabled=False,
        requires_download=True,
        installer="commercial-or-services",
        size_hint="policy and integration dependent",
        routes=("/security", "/privacy", "/audit", "/admin"),
    ),
)


def module_by_id(module_id: str) -> ModuleSpec | None:
    for spec in MODULES:
        if spec.id == module_id:
            return spec
    return None


def _env_enabled(module_id: str, default: bool) -> bool:
    raw = os.getenv(f"MULLM_ENABLE_{module_id.upper()}")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _installed(spec: ModuleSpec) -> bool:
    if spec.id == "core":
        return True
    if importlib.util.find_spec(spec.package.replace("-", "_")) is not None:
        return True
    if spec.extra and os.getenv(f"MULLM_{spec.id.upper()}_INSTALLED"):
        return True
    return False


def module_manifest() -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for spec in MODULES:
        installed = _installed(spec)
        enabled = _env_enabled(spec.id, spec.default_enabled and installed)
        manifest.append(
            {
                "id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "audience": spec.audience,
                "package": spec.package,
                "extra": spec.extra,
                "installed": installed,
                "enabled": enabled,
                "default_enabled": spec.default_enabled,
                "requires_download": spec.requires_download,
                "installer": spec.installer,
                "size_hint": spec.size_hint,
                "routes": list(spec.routes),
                "dependencies": list(spec.dependencies),
                "learn_url": spec.learn_url,
            }
        )
    return manifest
