"""World and 3D asset generation provider adapters.

The adapters keep Studio/Scene integrations behind a small contract so pages
can support Meshy/Tripo/Rodin/SANA-style providers without embedding provider
details in UI handlers.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from router.config import settings

GenerationKind = Literal["text_to_3d", "image_to_3d", "world"]


class WorldProviderError(RuntimeError):
    """Raised when a world/asset provider is misconfigured or unavailable."""


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    kind: GenerationKind = "text_to_3d"
    image_urls: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSubmission:
    provider: str
    endpoint: str
    method: str
    headers: dict[str, str]
    json: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    files_required: bool = False
    notes: list[str] = field(default_factory=list)

    def redacted(self) -> dict[str, Any]:
        headers = {key: ("<redacted>" if key.lower() == "authorization" else value) for key, value in self.headers.items()}
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "method": self.method,
            "headers": headers,
            "json": self.json,
            "data": self.data,
            "files_required": self.files_required,
            "notes": self.notes,
        }


class BaseWorldProvider:
    provider: str = ""
    label: str = ""
    docs_url: str = ""
    capabilities: tuple[str, ...] = ()

    def api_key(self) -> str:
        return ""

    def base_url(self) -> str:
        return ""

    def configured(self) -> bool:
        return bool(self.api_key() or self.base_url())

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "configured": self.configured(),
            "has_key": bool(self.api_key()),
            "base_url": self.base_url(),
            "docs_url": self.docs_url,
            "capabilities": list(self.capabilities),
        }

    def build_submission(self, request: GenerationRequest) -> ProviderSubmission:
        raise NotImplementedError

    async def submit(self, request: GenerationRequest, timeout_s: float = 90.0) -> dict[str, Any]:
        submission = self.build_submission(request)
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            if submission.json is not None:
                response = await client.request(
                    submission.method,
                    submission.endpoint,
                    headers=submission.headers,
                    json=submission.json,
                )
            else:
                response = await client.request(
                    submission.method,
                    submission.endpoint,
                    headers=submission.headers,
                    data=submission.data,
                )
        if response.status_code >= 400:
            raise WorldProviderError(f"{self.provider} request failed: HTTP {response.status_code} {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorldProviderError(f"{self.provider} returned non-JSON response") from exc
        return {
            "provider": self.provider,
            "submitted": True,
            "submitted_at": time.time(),
            "response": payload,
            "submission": submission.redacted(),
        }


class TripoProvider(BaseWorldProvider):
    provider = "tripo"
    label = "Tripo-compatible 3D"
    docs_url = "https://www.tripo3d.ai/api"
    capabilities = ("text_to_3d", "image_to_3d", "multiview_to_3d", "pbr", "glb")

    def api_key(self) -> str:
        return settings.tripo_api_key or os.getenv("TRIPO_API_KEY", "")

    def base_url(self) -> str:
        return (os.getenv("TRIPO_BASE_URL") or settings.tripo_base_url).rstrip("/")

    def configured(self) -> bool:
        return bool(self.api_key() and self.base_url())

    def build_submission(self, request: GenerationRequest) -> ProviderSubmission:
        if not self.api_key():
            raise WorldProviderError("TRIPO_API_KEY is required for Tripo-compatible generation")
        version = str(request.options.get("version") or "3.1").strip("/")
        if request.kind == "image_to_3d":
            path = f"/v1/3d-models/tripo/image-to-3d/{version}/"
            image_url = request.image_urls[0] if request.image_urls else request.options.get("image_url")
            if not image_url:
                raise WorldProviderError("image_to_3d requires image_url")
            payload: dict[str, Any] = {"image_url": image_url}
        else:
            path = f"/v1/3d-models/tripo/text-to-3d/{version}/"
            payload = {"prompt": request.prompt}
        payload.update(
            {
                "texture": bool(request.options.get("texture", True)),
                "pbr": bool(request.options.get("pbr", True)),
                "texture_quality": request.options.get("texture_quality", "standard"),
            }
        )
        return ProviderSubmission(
            provider=self.provider,
            endpoint=f"{self.base_url()}{path}",
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key()}", "Content-Type": "application/json"},
            json=payload,
            notes=["Base URL is configurable because Tripo-compatible APIs are exposed by multiple hosted gateways."],
        )


class RodinProvider(BaseWorldProvider):
    provider = "rodin"
    label = "Hyper3D Rodin"
    docs_url = "https://developer.hyper3d.ai/"
    capabilities = ("text_to_3d", "image_to_3d", "pbr", "glb", "fbx", "obj", "stl")

    def api_key(self) -> str:
        return settings.rodin_api_key or os.getenv("RODIN_API_KEY", "") or os.getenv("HYPER3D_API_KEY", "")

    def base_url(self) -> str:
        return (os.getenv("RODIN_BASE_URL") or settings.rodin_base_url).rstrip("/")

    def configured(self) -> bool:
        return bool(self.api_key() and self.base_url())

    def build_submission(self, request: GenerationRequest) -> ProviderSubmission:
        if not self.api_key():
            raise WorldProviderError("RODIN_API_KEY or HYPER3D_API_KEY is required for Rodin generation")
        data: dict[str, Any] = {
            "prompt": request.prompt,
            "geometry_file_format": request.options.get("geometry_file_format", "glb"),
            "material": request.options.get("material", "PBR"),
            "quality": request.options.get("quality", "high"),
        }
        for optional in ("seed", "tier", "addons", "bbox_condition", "condition_mode"):
            if optional in request.options:
                data[optional] = request.options[optional]
        return ProviderSubmission(
            provider=self.provider,
            endpoint=f"{self.base_url()}/api/v2/rodin",
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key()}"},
            data=data,
            files_required=request.kind == "image_to_3d",
            notes=["Image-to-3D requires multipart image files; this core adapter currently submits text fields only."],
        )


class SanaWmProvider(BaseWorldProvider):
    provider = "sana_wm"
    label = "SANA-WM"
    docs_url = "https://nvlabs.github.io/Sana/WM/"
    capabilities = ("world", "camera_6dof", "scene_decomposition", "local_or_custom_endpoint")

    def api_key(self) -> str:
        return settings.sana_wm_api_key or os.getenv("SANA_WM_API_KEY", "")

    def base_url(self) -> str:
        return (os.getenv("SANA_WM_BASE_URL") or settings.sana_wm_base_url).rstrip("/")

    def configured(self) -> bool:
        return bool(self.base_url() or settings.sana_wm_local_path or os.getenv("SANA_WM_LOCAL_PATH"))

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["local_path"] = settings.sana_wm_local_path or os.getenv("SANA_WM_LOCAL_PATH", "")
        data["public_api_stable"] = False
        return data

    def build_submission(self, request: GenerationRequest) -> ProviderSubmission:
        payload = {
            "prompt": request.prompt,
            "camera_path": request.options.get("camera_path", "orbit"),
            "duration_s": request.options.get("duration_s", 60),
            "resolution": request.options.get("resolution", "720p"),
            "decompose_scene": bool(request.options.get("decompose_scene", True)),
            "scene_objects": request.options.get("scene_objects", []),
        }
        if not self.base_url():
            return ProviderSubmission(
                provider=self.provider,
                endpoint=settings.sana_wm_local_path or os.getenv("SANA_WM_LOCAL_PATH", "local-sana-wm"),
                method="LOCAL",
                headers={},
                json=payload,
                notes=[
                    "SANA-WM is treated as a local/custom world-model adapter until a stable public HTTP API is configured.",
                    "Use SANA_WM_BASE_URL to point muLLM at a local service or cluster endpoint.",
                ],
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key():
            headers["Authorization"] = f"Bearer {self.api_key()}"
        return ProviderSubmission(
            provider=self.provider,
            endpoint=f"{self.base_url()}/generate",
            method="POST",
            headers=headers,
            json=payload,
        )


PROVIDERS: dict[str, BaseWorldProvider] = {
    "tripo": TripoProvider(),
    "rodin": RodinProvider(),
    "sana_wm": SanaWmProvider(),
}


def provider_status() -> dict[str, Any]:
    return {"providers": {name: adapter.status() for name, adapter in PROVIDERS.items()}}


def get_provider(name: str) -> BaseWorldProvider:
    key = name.strip().lower().replace("-", "_")
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise WorldProviderError(f"unsupported world provider: {name}") from exc


async def generate(provider: str, request: GenerationRequest, dry_run: bool = False) -> dict[str, Any]:
    adapter = get_provider(provider)
    submission = adapter.build_submission(request)
    if dry_run or submission.method == "LOCAL":
        return {
            "provider": adapter.provider,
            "submitted": False,
            "dry_run": dry_run,
            "local": submission.method == "LOCAL",
            "submission": submission.redacted(),
        }
    return await adapter.submit(request)
