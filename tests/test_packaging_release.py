import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def project_metadata() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_platform_packaging_uses_project_version():
    version = project_version()
    files = [
        ROOT / "packaging/linux/build_appimage.sh",
        ROOT / "packaging/mac/build_dmg.sh",
        ROOT / "packaging/windows/build_exe.bat",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "0.9.9" not in text
        assert "pyproject.toml" in text
    assert version == "1.0.0"


def test_python_support_metadata_includes_313_ci():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.11"' in pyproject
    assert '"Programming Language :: Python :: 3.11"' in pyproject
    assert '"Programming Language :: Python :: 3.12"' in pyproject
    assert '"Programming Language :: Python :: 3.13"' in pyproject
    assert 'python-version: ["3.11", "3.12", "3.13"]' in ci


def test_chromadb_is_optional_not_default_dependency():
    metadata = project_metadata()
    dependencies = metadata["dependencies"]
    extras = metadata["optional-dependencies"]

    assert any(dep.lower().startswith("numpy") for dep in dependencies)
    assert any(dep.lower().startswith("pillow") for dep in dependencies)
    assert not any(dep.lower().startswith("chromadb") for dep in dependencies)
    assert any(dep.lower().startswith("chromadb") for dep in extras["vector-cache"])
    assert "mullm[gpu,classifier,google,sentence-transformers,vector-cache,studio,dev,security]" in extras[
        "all"
    ]


def test_cache_docs_describe_sqlite_default_and_chroma_opt_in():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    privacy_page = (ROOT / "router" / "privacy.html").read_text(encoding="utf-8")
    security_page = (ROOT / "router" / "security.html").read_text(encoding="utf-8")
    packaging = (ROOT / "PACKAGING.md").read_text(encoding="utf-8")

    assert "MULLM_SEMANTIC_CACHE_BACKEND" in readme
    assert "MULLM_CACHE_ENABLED" not in readme
    assert "semantic_cache.sqlite3" in privacy
    assert "MULLM_SEMANTIC_CACHE_BACKEND=chroma" in privacy
    assert "semantic_cache.sqlite3" in privacy_page
    assert "SQLite by default, optional ChromaDB" in security_page
    assert "semantic_cache.sqlite3" in packaging


def test_security_policy_matches_current_workflow():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")

    assert "1.0.x" in policy
    assert "pre-1.0 development" in policy
    assert ".github/workflows/security.yml" in policy
    assert "scripts/grype_scan.sh" not in policy
    assert "python -m venv .security-venv" in policy
    assert "python -m bandit -c pyproject.toml -r router -lll" in policy
    assert "python -m pip_audit -r constraints.txt --strict --desc" in policy
    assert "bash scripts/security-wheel-audit.sh" in policy
    assert "Bandit and pip-audit" in workflow
    assert "python -m bandit -c pyproject.toml -r router -lll" in workflow
    assert "python -m pip_audit -r constraints.txt --strict --desc" in workflow
    assert "bash scripts/security-wheel-audit.sh" in workflow
    assert "Semgrep OSS rules" in workflow
    assert "Grype filesystem scan" in workflow


def test_security_wheel_audit_script_checks_resolved_wheel_dependencies():
    script = ROOT / "scripts" / "security-wheel-audit.sh"
    assert script.exists()

    text = script.read_text(encoding="utf-8")
    assert "-m build --wheel" in text
    assert "python -m venv \"$VENV_DIR\"" in text
    assert "\"$VENV_DIR/bin/python\" -m pip install -c \"$ROOT/constraints.txt\"" in text
    assert "mullm-*.whl" in text
    assert "pip freeze --all" in text
    assert "grep -viE '^(mullm|pip-audit)==" in text
    assert "python\" -m pip_audit -r \"$RESOLVED_REQUIREMENTS\" --strict --desc --progress-spinner off" in text


def test_service_launchers_prefer_current_mullm_server_entrypoint():
    linux_service = (ROOT / "packaging/linux/mullm.service").read_text(encoding="utf-8")
    mac_plist = (ROOT / "packaging/mac/mullm.plist").read_text(encoding="utf-8")
    windows_service = (ROOT / "packaging/windows/mullm_service.ps1").read_text(encoding="utf-8")

    assert "ExecStart=/usr/bin/env mullm-server" in linux_service
    assert "Environment=PATH=" in linux_service
    assert "%h/.local/bin" in linux_service
    assert "%h/.mullm/bin" in linux_service
    assert "%h/.mullm1/bin" in linux_service
    assert "ExecStart=mullm1-server" not in linux_service
    assert "User=%i" not in linux_service

    assert "$HOME/.local/bin/mullm-server" in mac_plist
    assert "$HOME/.mullm/bin/mullm-server" in mac_plist
    assert "$HOME/.mullm1/bin/mullm1-server" in mac_plist
    assert mac_plist.index("mullm-server") < mac_plist.index("mullm1-server")

    assert "Get-Command mullm-server" in windows_service
    assert "Get-Command mullm1-server" in windows_service
    assert windows_service.index("Get-Command mullm-server") < windows_service.index(
        "Get-Command mullm1-server"
    )
    assert ".mullm\\Scripts\\mullm-server.exe" in windows_service
    assert "$HOME/.mullm1/bin/mullm1-server" in mac_plist
    assert ".mullm1\\Scripts\\mullm1-server.exe" in windows_service


def test_release_dry_run_workflow_exists():
    workflow = ROOT / ".github" / "workflows" / "release-dry-run.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "Wheel install smoke" in text
    assert "ubuntu-latest" in text
    assert "macos-latest" in text
    assert "windows-latest" in text
    assert "python -m build" in text
    assert "python -m pip install -c constraints.txt dist/*.whl" in text
    assert "Installed server smoke" in text
    assert "bash scripts/release-smoke.sh" in text


def test_release_smoke_script_verifies_installed_wheel_surfaces():
    script = ROOT / "scripts" / "release-smoke.sh"
    assert script.exists()

    text = script.read_text(encoding="utf-8")
    assert "-m build --wheel" in text
    assert "python -m venv \"$RUN_VENV\"" in text
    assert "MULLM_STATE_DIR=\"$STATE_DIR\"" in text
    assert "MULLM_ENABLE_STUDIO=true" in text
    assert "\"$RUN_VENV/bin/mullm\" --version" in text
    assert '("/health", b\'"status":"ok"\')' in text
    assert '("/setup", b"setup")' in text
    assert '("/chat", b"chat")' in text
    assert '("/swords", b"three")' in text
    assert '("/api/settings", b\'"providers"\')' in text
    assert '("/api/musaic/status", b\'"ffmpeg_available"\')' in text
    assert '("/static/three/three.module.js", b"REVISION")' in text
    assert '("/code/ready/bamboo-village.html", b"<html")' in text
    assert '"force_tier": "groundtruth"' in text
    assert '"groundtruth_category"' in text
    assert 'fetch("/cache/clear", method="DELETE")' in text
    assert '"cache": "ok"' in text
    assert 'semantic_cache.sqlite3' in text


def test_default_runtime_cache_is_not_inside_package(monkeypatch, tmp_path):
    from router import config

    monkeypatch.delenv("MULLM_STATE_DIR", raising=False)
    package_root = (ROOT / "router").resolve()
    default_cache = config._default_cache_dir().resolve()
    default_assets = config._default_asset_root().resolve()

    assert not default_cache.is_relative_to(package_root)
    assert not default_assets.is_relative_to(package_root)

    custom_state = tmp_path / "state"
    monkeypatch.setenv("MULLM_STATE_DIR", str(custom_state))
    assert config._default_cache_dir() == custom_state / "cache" / "data"
    assert config._default_asset_root() == custom_state / "assets"
