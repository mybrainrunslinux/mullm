"""Asset storage adapters for Scene/Studio generated media."""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from router.config import settings

ROOT = Path(__file__).resolve().parent.parent

AssetBackend = Literal["local", "s3", "azure_blob", "external_api"]
CompressionMethod = Literal[
    "none", "gzip", "brotli", "draco", "meshopt", "ktx2", "draco_ktx2", "game_ready", "auto",
]


class AssetStoreError(RuntimeError):
    """Raised when an asset store operation is unsupported or misconfigured."""


@dataclass(frozen=True)
class AssetLocation:
    backend: str
    name: str
    path: str
    url: str
    bytes: int


def asset_root() -> Path:
    if settings.asset_root:
        root = Path(settings.asset_root).expanduser()
    else:
        cache_dir = Path(settings.cache_dir).expanduser()
        root = cache_dir.parent.parent / "assets"
    return root


def assets_3d_dir() -> Path:
    return asset_root() / "3d"


def packaged_assets_3d_dir() -> Path:
    return ROOT / "assets" / "3d"


def sanitize_asset_name(name: str) -> str:
    raw = name.removesuffix(".glb")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", raw).strip("-")
    safe = re.sub(r"-+", "-", safe).removesuffix(".glb")
    if not safe:
        raise AssetStoreError("invalid asset name")
    return safe[:160]


def asset_url(filename: str) -> str:
    if settings.asset_external_base_url and settings.asset_storage_backend != "local":
        return f"{settings.asset_external_base_url.rstrip('/')}/{filename}"
    return f"/assets/3d/{filename}"


def resolve_asset_file(filename: str) -> Path:
    if Path(filename).name != filename:
        raise AssetStoreError("invalid asset filename")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise AssetStoreError("invalid asset filename")
    asset_dirs = [assets_3d_dir(), packaged_assets_3d_dir()]
    allowed_suffixes = {
        ".glb",
        ".gltf",
        ".bin",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".ktx2",
        ".gz",
        ".br",
    }
    if Path(filename).suffix.lower() not in allowed_suffixes:
        raise AssetStoreError("unsupported asset file type")
    for root in asset_dirs:
        path = root / filename
        if path.exists() and path.is_file():
            return path
    raise FileNotFoundError(filename)


class AssetStore(ABC):
    backend: AssetBackend

    @abstractmethod
    def put_bytes(self, name: str, data: bytes, metadata: dict[str, Any] | None = None) -> AssetLocation:
        raise NotImplementedError

    @abstractmethod
    def url_for(self, filename: str) -> str:
        raise NotImplementedError


class LocalAssetStore(AssetStore):
    backend: AssetBackend = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or assets_3d_dir()

    def put_bytes(self, name: str, data: bytes, metadata: dict[str, Any] | None = None) -> AssetLocation:
        safe = sanitize_asset_name(name)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{safe}.glb"
        path.write_bytes(data)
        if metadata is not None:
            path.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return AssetLocation(
            backend=self.backend,
            name=safe,
            path=str(path),
            url=self.url_for(path.name),
            bytes=len(data),
        )

    def url_for(self, filename: str) -> str:
        return asset_url(filename)


class S3AssetStore(AssetStore):
    backend: AssetBackend = "s3"

    def __init__(self) -> None:
        self.bucket = getattr(settings, "asset_s3_bucket", "")
        if not self.bucket:
            raise AssetStoreError("S3 asset storage requires asset_s3_bucket")

    def put_bytes(self, name: str, data: bytes, metadata: dict[str, Any] | None = None) -> AssetLocation:
        raise AssetStoreError("S3 upload adapter is not installed in core; enable the Studio/cloud storage extra")

    def url_for(self, filename: str) -> str:
        return asset_url(filename)


class AzureBlobAssetStore(AssetStore):
    backend: AssetBackend = "azure_blob"

    def __init__(self) -> None:
        self.container = getattr(settings, "asset_azure_container", "")
        if not self.container:
            raise AssetStoreError("Azure Blob asset storage requires asset_azure_container")

    def put_bytes(self, name: str, data: bytes, metadata: dict[str, Any] | None = None) -> AssetLocation:
        raise AssetStoreError("Azure Blob upload adapter is not installed in core; enable the Studio/cloud storage extra")

    def url_for(self, filename: str) -> str:
        return asset_url(filename)


class ExternalApiAssetStore(AssetStore):
    backend: AssetBackend = "external_api"

    def __init__(self) -> None:
        if not settings.asset_external_base_url:
            raise AssetStoreError("External asset API storage requires asset_external_base_url")

    def put_bytes(self, name: str, data: bytes, metadata: dict[str, Any] | None = None) -> AssetLocation:
        raise AssetStoreError("External asset API upload adapter requires a deployment-specific plugin")

    def url_for(self, filename: str) -> str:
        return asset_url(filename)


def get_asset_store() -> AssetStore:
    backend = settings.asset_storage_backend
    if backend == "local":
        return LocalAssetStore()
    if backend == "s3":
        return S3AssetStore()
    if backend == "azure_blob":
        return AzureBlobAssetStore()
    if backend == "external_api":
        return ExternalApiAssetStore()
    raise AssetStoreError(f"unsupported asset storage backend: {backend}")


def compression_status() -> dict[str, dict[str, Any]]:
    gltf_transform = shutil.which("gltf-transform")
    draco_encoder = shutil.which("draco_encoder")
    return {
        "none": {"available": True, "kind": "passthrough"},
        "gzip": {"available": True, "kind": "builtin"},
        "brotli": {
            "available": importlib.util.find_spec("brotli") is not None,
            "kind": "python-optional",
            "install_hint": "pip install brotli",
        },
        "draco": {
            "available": bool(gltf_transform or draco_encoder),
            "kind": "external-tool",
            "command": gltf_transform or draco_encoder or "",
            "install_hint": "Install @gltf-transform/cli or Google's draco_encoder.",
        },
        "meshopt": {
            "available": bool(gltf_transform),
            "kind": "external-tool",
            "command": gltf_transform or "",
            "install_hint": "Install @gltf-transform/cli for Meshopt compression.",
        },
        "ktx2": {
            "available": bool(gltf_transform),
            "kind": "external-tool",
            "command": gltf_transform or "",
            "install_hint": "Install @gltf-transform/cli plus KTX-Software/BasisU support for texture compression.",
        },
        "draco_ktx2": {
            "available": bool(gltf_transform),
            "kind": "external-tool",
            "command": gltf_transform or "",
            "install_hint": "Install @gltf-transform/cli plus KTX-Software (ktx binary) — best web-delivery size (geometry + texture compression).",
        },
        "game_ready": {
            "available": bool(gltf_transform),
            "kind": "external-tool",
            "command": gltf_transform or "",
            "install_hint": "weld + simplify(0.25) + 1K textures + KTX2 + Draco — targets ≤2MB game-ready props. Needs @gltf-transform/cli and KTX-Software.",
        },
        "auto": {
            "available": True,
            "kind": "policy",
            "selected_default": "gzip",
        },
    }


def compress_asset(path: Path, method: CompressionMethod = "auto") -> AssetLocation:
    selected = "gzip" if method == "auto" else method
    if selected == "none":
        return AssetLocation("local", path.stem, str(path), asset_url(path.name), path.stat().st_size)
    if selected == "gzip":
        output = Path(str(path) + ".gz")
        with path.open("rb") as src, gzip.open(output, "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
        return AssetLocation("local", path.stem, str(output), asset_url(output.name), output.stat().st_size)
    if selected == "brotli":
        try:
            import brotli  # type: ignore[import-not-found]
        except Exception as exc:
            raise AssetStoreError("brotli compression requires the optional brotli package") from exc
        output = Path(str(path) + ".br")
        output.write_bytes(brotli.compress(path.read_bytes(), quality=11))
        return AssetLocation("local", path.stem, str(output), asset_url(output.name), output.stat().st_size)
    if selected in {"draco", "meshopt", "ktx2", "draco_ktx2", "game_ready"}:
        # shutil.which only searches PATH — npm-global bin may not be on it when uvicorn starts.
        # Fall back to common install locations before giving up.
        gt = shutil.which("gltf-transform")
        if not gt:
            _npm_candidates = [
                Path.home() / ".npm-global" / "bin" / "gltf-transform",
                Path("/usr/local/bin/gltf-transform"),
                Path("/usr/bin/gltf-transform"),
            ]
            for _candidate in _npm_candidates:
                if _candidate.is_file():
                    gt = str(_candidate)
                    break
        if not gt:
            raise AssetStoreError(
                f"{selected} compression requires @gltf-transform/cli: npm i -g @gltf-transform/cli"
                " (also ensure ~/.npm-global/bin is on PATH)"
            )
        suffix_map = {
            "draco": "-draco.glb", "meshopt": "-meshopt.glb",
            "ktx2": "-ktx2.glb", "draco_ktx2": "-web.glb", "game_ready": "-game.glb",
        }
        output = path.with_name(path.stem + suffix_map[selected])
        # draco_ktx2 chains texture compression (etc1s) then geometry (draco)
        # — the recommended web-delivery combo (KTX2 first: draco output stays draco).
        # game_ready additionally welds, simplifies to ~25% triangles, and caps
        # textures at 1K first — sized for ≤2MB stylized game props.
        steps = {
            "draco":      [["draco", str(path), str(output)]],
            "meshopt":    [["meshopt", str(path), str(output)]],
            "ktx2":       [["etc1s", str(path), str(output)]],
            "draco_ktx2": [["etc1s", str(path), str(output)], ["draco", str(output), str(output)]],
            "game_ready": [
                ["weld", str(path), str(output)],
                ["simplify", "--ratio", "0.25", "--error", "0.001", str(output), str(output)],
                ["resize", "--width", "1024", "--height", "1024", str(output), str(output)],
                ["etc1s", str(output), str(output)],
                ["draco", str(output), str(output)],
            ],
        }[selected]
        import subprocess
        env = dict(os.environ)
        # KTX-Software's `ktx` binary is commonly a user-level install.
        _local_bin = str(Path.home() / ".local" / "bin")
        if _local_bin not in env.get("PATH", ""):
            env["PATH"] = _local_bin + os.pathsep + env.get("PATH", "")
        for step in steps:
            result = subprocess.run([gt, *step], capture_output=True, timeout=300, env=env)
            if result.returncode != 0:
                raise AssetStoreError(f"gltf-transform {step[0]} failed: {result.stderr.decode()[:300]}")
        return AssetLocation("local", path.stem, str(output), asset_url(output.name), output.stat().st_size)
    raise AssetStoreError(f"unsupported compression method: {selected}")
