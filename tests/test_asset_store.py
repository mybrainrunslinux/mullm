from pathlib import Path

import pytest

from router import asset_store
from router.asset_store import (
    AssetStoreError,
    LocalAssetStore,
    compress_asset,
    compression_status,
    get_asset_store,
)
from router.config import settings


def test_default_asset_root_uses_runtime_state_not_package_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "asset_root", "")
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache" / "data")

    assert asset_store.asset_root() == tmp_path / "assets"


def test_local_asset_store_writes_glb_and_sidecar(tmp_path):
    store = LocalAssetStore(tmp_path)
    saved = store.put_bytes("Hero Sword!.glb", b"glTF fake", {"prompt": "hero sword"})

    assert saved.name == "Hero-Sword"
    assert saved.backend == "local"
    assert Path(saved.path).read_bytes() == b"glTF fake"
    assert Path(saved.path).with_suffix(".json").exists()


def test_asset_url_uses_external_base_for_object_storage(monkeypatch):
    monkeypatch.setattr(settings, "asset_storage_backend", "s3")
    monkeypatch.setattr(settings, "asset_external_base_url", "https://cdn.example.test/mullm")

    assert asset_store.asset_url("sword.glb") == "https://cdn.example.test/mullm/sword.glb"


def test_get_asset_store_rejects_unconfigured_s3(monkeypatch):
    monkeypatch.setattr(settings, "asset_storage_backend", "s3")
    monkeypatch.setattr(settings, "asset_s3_bucket", "")

    with pytest.raises(AssetStoreError, match="asset_s3_bucket"):
        get_asset_store()


def test_gzip_compression_returns_variant(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    source = asset_dir / "test.glb"
    source.write_bytes(b"glTF fake glTF fake glTF fake")
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    result = compress_asset(source, "gzip")

    assert result.url == "/assets/3d/test.glb.gz"
    assert Path(result.path).exists()
    assert result.bytes > 0


def test_compression_status_keeps_optional_gltf_modes_visible():
    status = compression_status()

    assert status["gzip"]["available"] is True
    assert "brotli" in status
    assert status["brotli"]["kind"] == "python-optional"
    assert status["draco"]["kind"] == "external-tool"
    assert status["meshopt"]["kind"] == "external-tool"
    assert status["ktx2"]["kind"] == "external-tool"


def test_draco_without_tool_fails_as_missing_adapter(tmp_path, monkeypatch):
    source = tmp_path / "test.glb"
    source.write_bytes(b"glTF fake")
    monkeypatch.setattr("router.asset_store.shutil.which", lambda _cmd: None)

    with pytest.raises(AssetStoreError, match="draco"):
        compress_asset(source, "draco")
