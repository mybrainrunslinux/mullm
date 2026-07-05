from router.main import module_manifest_endpoint
from router.module_catalog import module_manifest


def test_module_manifest_keeps_core_installed_and_studio_optional():
    modules = {m["id"]: m for m in module_manifest()}

    assert modules["core"]["installed"] is True
    assert modules["core"]["enabled"] is True
    assert modules["core"]["requires_download"] is False

    assert modules["studio"]["requires_download"] is True
    assert modules["studio"]["enabled"] is False
    assert modules["studio"]["learn_url"].endswith("/learn/comfyui")
    assert "/comfyui" in modules["studio"]["routes"]


async def test_module_manifest_endpoint_shape():
    payload = await module_manifest_endpoint()

    assert "modules" in payload
    assert any(m["id"] == "core" for m in payload["modules"])
    assert any(m["id"] == "studio" and m["requires_download"] for m in payload["modules"])


async def test_module_install_endpoint_records_opt_in_job(tmp_path, monkeypatch):
    from router import studio_installer
    from router.main import module_install_create

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(studio_installer, "STUDIO_ROOT", tmp_path / "studio")

    payload = await module_install_create("studio")

    assert payload["kind"] == "module-install:studio"
    assert payload["status"] == "done"
    assert payload["result"]["module"] == "studio"
    assert payload["result"]["profile_count"] >= 3
