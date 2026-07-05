import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from router import main as router_main
from router import page_registry
from router.main import app

EXCLUDED_EXACT = {
    "/docs",
    "/redoc",
    "/openapi.json",
    # Provider/network probes have separate tests and may depend on local setup.
    "/api/civitai/loras/search",
    "/api/terrain/sources",
    "/query/hyper",
}

EXCLUDED_PREFIXES = (
    "/events",
    "/query/stream",
    "/static/",
    "/assets/",
    "/outputs/",
    "/generated/",
    "/api/stream/",
    "/api/jobs/",
    "/cancel/",
    "/api/agents/",
    "/api/setup/install",
)


@pytest.mark.asyncio
async def test_docs_pages_allow_swagger_and_redoc_assets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        docs = await client.get("/docs")
        redoc = await client.get("/redoc")
        spec = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert "swagger-ui-bundle.js" in docs.text
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert redoc.status_code == 200
    assert "redoc.standalone.js" in redoc.text
    assert "fonts.googleapis.com" in redoc.headers["content-security-policy"]
    assert "worker-src 'self' blob:" in redoc.headers["content-security-policy"]
    assert "cdn.redoc.ly" in redoc.headers["content-security-policy"]
    assert spec.status_code == 200
    assert "/query" in spec.json()["paths"]


PLACEHOLDER_TERMS = (
    "coming soon",
    "under construction",
    "not implemented",
    "not yet wired",
    "lorem ipsum",
)


def _should_probe(path: str, methods: tuple[str, ...]) -> bool:
    if "GET" not in methods:
        return False
    if "{" in path:
        return False
    if path in EXCLUDED_EXACT:
        return False
    return not any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


@pytest.mark.asyncio
async def test_packaged_get_routes_are_available_without_placeholder_shells():
    """Release gate: public packaged GET routes should not 404 or show shells."""
    route_map: dict[str, tuple[str, ...]] = {}
    for route in router_main._iter_app_routes():
        path = getattr(route, "path", "")
        methods = tuple(sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}))
        if path and _should_probe(path, methods):
            route_map[path] = methods

    failures = []
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=15,
        follow_redirects=False,
    ) as client:
        for path in sorted(route_map):
            try:
                response = await client.get(path)
            except Exception as exc:  # pragma: no cover - failure detail path
                failures.append(f"{path}: raised {exc!r}")
                continue
            if response.status_code >= 400:
                failures.append(f"{path}: HTTP {response.status_code}")
                continue
            text = response.content[:3000].decode("utf-8", "replace").lower()
            matched = [term for term in PLACEHOLDER_TERMS if term in text]
            if matched:
                failures.append(f"{path}: placeholder terms {matched}")

    assert failures == []


@pytest.mark.asyncio
async def test_packaged_html_local_links_are_available(monkeypatch):
    """Release gate: packaged HTML should not link to local 404s."""
    monkeypatch.setattr(page_registry.settings, "ui_mode", "dev")
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)
    html_dir = Path(__file__).resolve().parents[1] / "router"
    links: list[tuple[str, str]] = []
    attr_pattern = re.compile(r"""(?:href|src)\s*=\s*["'](/[^"'#?]+)""")
    for html_file in sorted(html_dir.glob("*.html")):
        text = html_file.read_text(encoding="utf-8", errors="replace")
        for match in attr_pattern.finditer(text):
            path = match.group(1)
            if "${" in path:
                continue
            links.append((html_file.name, path))

    failures = []
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=15,
        follow_redirects=False,
    ) as client:
        for path in sorted({path for _source, path in links}):
            response = await client.get(path)
            if response.status_code >= 400:
                refs = [source for source, link in links if link == path][:5]
                failures.append(f"{path}: HTTP {response.status_code} linked from {refs}")

    assert failures == []


def test_route_inventory_does_not_report_registered_pages_missing():
    """Release gate: /api/routes must not show false missing page routes."""
    inventory = router_main._route_inventory()
    missing = [
        item["path"]
        for item in inventory["pages"]
        if item.get("status") == "missing"
    ]

    assert missing == []


def test_shipped_router_files_do_not_advertise_placeholder_features():
    """Release gate: shipped UI/API files must not advertise future-only shells."""
    router_dir = Path(__file__).resolve().parents[1] / "router"
    terms = PLACEHOLDER_TERMS + ("backend stub", "cloud stub")
    failures: list[str] = []
    for path in sorted([*router_dir.glob("*.html"), *router_dir.glob("*.py")]):
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        matched = [term for term in terms if term in text]
        if matched:
            failures.append(f"{path.name}: {matched}")

    assert failures == []


def test_hyper_page_does_not_ship_simulated_success_path():
    """Hyper must use the live SSE backend or show an error, not canned success."""
    html = (Path(__file__).resolve().parents[1] / "router" / "hyper.html").read_text(
        encoding="utf-8",
        errors="replace",
    )
    forbidden = (
        "DEMO_TASKS",
        "Demo Mode",
        "simulated execution",
        "fallbackToDemo",
        "runDemo(",
        "asset ready",
        "without a live server",
    )

    assert [term for term in forbidden if term in html] == []


def test_tts_page_prefers_available_server_voice_before_browser_fallback():
    """Voice Studio should not default users to poor browser speech when TTS is configured."""
    html = (Path(__file__).resolve().parents[1] / "router" / "tts.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert "Default to the best available server backend; browser voices are a fallback." in html
    assert "serverBackends.find(b => b.name === 'kokoro')" in html
    assert "serverBackends.find(b => b.name === 'openai')" in html
    assert "backend: activeBackend" in html
    assert html.count("utt.onstart =") == 1
    assert html.count("utt.onend =") == 1
    assert html.count("utt.onerror =") == 1


def test_tts_page_uses_actual_audio_type_for_downloads_and_batch():
    html = (Path(__file__).resolve().parents[1] / "router" / "tts.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert "function extFromContentType(type)" in html
    assert "resp.headers.get('Content-Type')" in html
    assert "recDl.download = `voice_${tone}_${ts}.${actualExt}`" in html
    assert 'id="batch-csv"' in html
    assert "fetch('/api/tts/batch'" in html
    assert "blobFromBase64(item.audio_base64, item.content_type)" in html


def test_musaic_exposes_foley_tab_and_direct_endpoint_ui():
    html = (Path(__file__).resolve().parents[1] / "router" / "musaic.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert 'id="tab-foley"' in html
    assert "switchTab('foley')" in html
    assert "location.pathname === '/foley'" in html
    assert "/api/foley/generate" in html
    assert 'id="foley-pitch"' in html


def test_drums_page_ships_interactive_kit_and_sequence_grid():
    html = (Path(__file__).resolve().parents[1] / "router" / "drums.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert "muLLM Drums" in html
    assert "const soundLibrary = []" in html
    assert "function buildSoundLibrary" in html
    assert "function playDrum" in html
    assert "function renderGrid" in html
    assert "function toggleRecording" in html
    assert "function saveRecordingMp3" in html
    assert "leftKeys = ['q','w','e','r','a','s','d','f','z','x','c','v']" in html
    assert "rightKeys = ['u','i','o','p','j','k','l',';','m',',','.','/']" in html
    assert 'id="signature"' in html
    assert 'max="16"' in html


def test_3d_page_uses_live_comfyui_3d_contract():
    html = (Path(__file__).resolve().parents[1] / "router" / "3d.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert 'id="gen-asset-type"' in html
    assert '<option value="sword">Sword</option>' in html
    assert "function selectedAssetType()" in html
    assert "function assetTypePayload(assetType)" in html
    assert "function promptForAssetType(prompt, assetType)" in html
    assert "single hero sword, centered" in html
    assert "neutral A-pose" in html
    assert "...assetTypePayload(assetType)" in html
    assert "fetch('/api/3d/comfyui'" in html
    assert "fetch('/api/3d/import-comfyui'" in html
    assert "fetch('/api/vram/free'" in html
    assert "/api/comfyui/history/${encodeURIComponent(promptId)}" in html
    assert "/api/3d/reference" not in html
    assert "/api/3d/convert" not in html
    assert "function firstComfy3DOutput(entry)" in html


def test_setup_page_exposes_asset_storage_config():
    html = (Path(__file__).resolve().parents[1] / "router" / "setup.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert 'id="asset-root"' in html
    assert "function loadAssetStorage()" in html
    assert "function saveAssetRoot()" in html
    assert "fetch(API + '/api/setup/assets'" in html
    assert "[studio.assets] root" in html
    assert '"three": "/static/three/three.module.js"' in html
    assert "cdn.jsdelivr.net/npm/three" not in html
    assert "meshy-clockwork-mage-lowpoly.glb" not in html


def test_walks_page_uses_local_three_and_procedural_fallback():
    html = (Path(__file__).resolve().parents[1] / "router" / "walks.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert '"three": "/static/three/three.module.js"' in html
    assert '"three/addons/": "/static/three/addons/"' in html
    assert "https://unpkg.com/three" not in html
    assert "async function chooseWalkModel()" in html
    assert "loadFallbackWalker()" in html
    assert "Procedural Walk Rig" in html


def test_core_csp_allows_shipped_font_and_chart_assets():
    csp = router_main._CSP

    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp
    assert "https://cdn.jsdelivr.net" in csp
    assert "worker-src 'self' blob:" in csp


def test_troubleshoot_uses_same_origin_api_base():
    html = (Path(__file__).resolve().parents[1] / "router" / "troubleshoot.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert "return window.location.origin;" in html
    assert "return 'https://127.0.0.1:6856'" not in html


def test_visible_studio_pages_fetch_registered_literal_api_routes():
    """Release gate: visible Studio pages should not call vanished literal APIs."""
    html_dir = Path(__file__).resolve().parents[1] / "router"
    route_paths = router_main._registered_route_paths()
    pages = [
        "3d.html",
        "comfyui.html",
        "image.html",
        "musaic.html",
        "setup.html",
        "swords.html",
        "tts.html",
    ]
    patterns = [
        re.compile(r"""fetch\(\s*["']([^"'`$?]+)"""),
        re.compile(r"""fetch\(\s*API\s*\+\s*["']([^"'`$?]+)"""),
        re.compile(r"""fetch\(\s*`\$\{BASE\}([^`$?]+)"""),
        re.compile(r"""xhr\.open\(\s*["'][A-Z]+["']\s*,\s*`\$\{BASE\}([^`$?]+)"""),
    ]

    def route_exists(path: str) -> bool:
        if path in route_paths:
            return True
        segments = path.strip("/").split("/")
        for route in route_paths:
            route_segments = route.strip("/").split("/")
            if len(segments) == len(route_segments) and all(
                actual == expected or (expected.startswith("{") and expected.endswith("}"))
                for actual, expected in zip(segments, route_segments, strict=True)
            ):
                return True
        return False

    failures: list[str] = []
    for page in pages:
        text = (html_dir / page).read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            for match in pattern.finditer(text):
                path = match.group(1).split("?", 1)[0]
                if not path.startswith(("/api/", "/mcp", "/rpc", "/query", "/classify")):
                    continue
                if path.endswith("/") or "${" in path:
                    continue
                if not route_exists(path):
                    failures.append(f"{page}: {path}")

    assert failures == []


def test_chat_escalation_does_not_reuse_wrong_cloud_model_override():
    """Escalating a selected provider should let the target tier choose its model."""
    html = (Path(__file__).resolve().parents[1] / "router" / "chat.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert 'fetch(API + "/api/providers/models")' in html
    assert "function tierDefaultModel(provider, tier)" in html
    assert "mod && (!tierModel || mod === tierModel) ? mod : \"\"" in html


def test_bench_routerbench_uses_packaged_snapshot_not_mock_mode():
    html = (Path(__file__).resolve().parents[1] / "router" / "bench.html").read_text(
        encoding="utf-8",
        errors="replace",
    )

    assert "mock mode" not in html.lower()
    assert "type: 'mock'" not in html
    assert "/api/bench/routerbench-static" in html
    assert "packaged static snapshot" in html


@pytest.mark.asyncio
async def test_provider_catalog_aliases_are_release_ready():
    """Provider catalog should be discoverable by both documented and intuitive paths."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        canonical = await client.get("/api/provider-catalog")
        alias = await client.get("/api/providers/catalog")
        models = await client.get("/api/providers/models")

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert models.status_code == 200
    assert canonical.json() == alias.json()

    providers = canonical.json()["providers"]
    assert providers
    assert all(provider["status"] != "planned" for provider in providers)
    assert {"cloud_cheap", "cloud_full", "cloud_power"} <= set(models.json()["tiers"])


@pytest.mark.asyncio
async def test_obsidian_status_reports_configurable_or_ready_mode(monkeypatch, tmp_path):
    """Obsidian is an implemented read-only indexer, not a future-only setup item."""
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    unset = await router_main.obsidian_status()
    assert unset["mode"] == "configure_vault"

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    configured = await router_main.obsidian_status()
    assert configured["mode"] == "ready"
    assert configured["exists"] is True


@pytest.mark.asyncio
async def test_game_system_source_examples_are_packaged():
    """Game Systems view-code examples should not depend on mutable cache state."""
    html = (Path(__file__).resolve().parents[1] / "router" / "gamesystems.html").read_text(
        encoding="utf-8"
    )
    paths = sorted(set(re.findall(r"fetchPath: '([^']+)'", html)))
    assert paths
    assert all(path.startswith("/static/gamesystems/") for path in paths)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in paths:
            response = await client.get(path)
            assert response.status_code == 200, path
            assert "export class" in response.text


@pytest.mark.asyncio
async def test_dev_page_status_has_backing_endpoints(monkeypatch):
    """Release gate: advertised dev/research pages should not be API shells."""
    monkeypatch.setattr(router_main.settings, "ui_mode", "dev")
    monkeypatch.setattr(page_registry.settings, "ui_mode", "dev")
    monkeypatch.setattr(router_main.settings, "enable_studio", True)
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)

    status = await router_main.pages_status()
    broken = [
        (page["href"], page.get("missing_endpoints", []))
        for page in status["pages"]
        if page.get("status") in {"missing", "degraded"}
    ]

    assert broken == []


@pytest.mark.asyncio
async def test_studio_mode_advertises_media_and_asset_pages(monkeypatch):
    """Installed Studio should expose the media/game-dev pages in navigation status."""
    monkeypatch.setattr(router_main.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(router_main.settings, "enable_studio", True)
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)

    status = await router_main.pages_status()
    hrefs = {page["href"]: page for page in status["pages"]}

    expected = {
        "/tts",
        "/musaic",
        "/image",
        "/video",
        "/videoeditor",
        "/asset-manager",
        "/studio",
        "/swords",
        "/bows",
        "/siege",
    }
    assert expected <= set(hrefs)
    assert all(hrefs[href]["status"] == "available" for href in expected)


def test_route_inventory_lists_registry_pages_served_by_generic_html_route(monkeypatch):
    """The /urls inventory should include clickable Studio pages, not just decorated routes."""
    monkeypatch.setattr(router_main.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(router_main.settings, "enable_studio", True)
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)

    inventory = router_main._route_inventory()
    page_paths = {page["path"] for page in inventory["pages"]}

    assert {"/tts", "/musaic", "/image", "/video", "/asset-manager"} <= page_paths
