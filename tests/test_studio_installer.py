import json

import pytest

from router import studio_installer


def test_install_builtin_asset_pack(tmp_path):
    result = studio_installer.install_builtin_asset_pack(tmp_path)

    profiles = json.loads((tmp_path / "comfyui" / "profiles.json").read_text())
    assert result["profile_count"] >= 3
    assert any(profile["id"] == "sdxl_realism_texture" for profile in profiles["profiles"])
    assert (tmp_path / "comfyui" / "workflows").is_dir()
    assert (tmp_path / "comfyui" / "loras").is_dir()


@pytest.mark.asyncio
async def test_remote_manifest_requires_https_or_localhost():
    with pytest.raises(ValueError):
        await studio_installer.install_from_manifest_url("http://example.com/manifest.json")
