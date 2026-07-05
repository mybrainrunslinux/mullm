from pathlib import Path

import pytest

from router import main


@pytest.mark.asyncio
async def test_game_list_discovers_ready_games_and_assets(tmp_path: Path, monkeypatch):
    ready = tmp_path / "code" / "ready"
    ready.mkdir(parents=True)
    (ready / "archers-crossing.html").write_text("<!doctype html><title>Archers</title>", encoding="utf-8")
    (ready / "ballista.glb").write_bytes(b"glb")
    monkeypatch.setattr(main, "_READY_GAMES_DIR", ready)

    payload = await main.game_list()

    assert payload["count"] == 1
    assert payload["games"][0]["file"] == "archers-crossing.html"
    assert payload["games"][0]["path"] == "/code/ready/archers-crossing.html"
    assert "Archery" in payload["games"][0]["categories"]
    assert payload["asset_count"] == 1
    assert payload["assets"][0]["file"] == "ballista.glb"


def test_games_page_uses_direct_navigation_not_iframe_player():
    html = (Path(__file__).resolve().parents[1] / "router" / "games.html").read_text(encoding="utf-8")

    assert "window.location.href = url;" in html
    assert "frame.src = url;" not in html


def test_games_page_uses_manifest_as_catalog_source_of_truth():
    html = (Path(__file__).resolve().parents[1] / "router" / "games.html").read_text(encoding="utf-8")

    assert "async function bootGames()" in html
    assert "fetch('/api/game-list')" in html
    assert "GAMES.length = 0;" in html
    assert "metadataFromManifest(g)" in html


def test_packaged_game_csp_allows_threejs_cdns_only_on_game_pages():
    assert "https://cdnjs.cloudflare.com" in main._GAME_CSP
    assert "https://unpkg.com" in main._GAME_CSP
    assert "https://cdn.jsdelivr.net" in main._GAME_CSP
    assert "cdnjs.cloudflare.com" not in main._CSP


def test_packaged_three_games_use_local_three_vendor():
    root = Path(__file__).resolve().parents[1]
    bamboo = (root / "code" / "ready" / "bamboo-village.html").read_text(encoding="utf-8")
    foot_golf = (root / "code" / "ready" / "foot-golf.html").read_text(encoding="utf-8")
    three_core = (root / "router" / "static" / "three" / "three.core.js").read_text(encoding="utf-8")

    assert (root / "router" / "static" / "three" / "three.module.js").exists()
    assert (root / "router" / "static" / "three" / "addons" / "controls" / "PointerLockControls.js").exists()
    assert (root / "router" / "static" / "three" / "addons" / "generators" / "TerrainGenerator.js").exists()
    assert "const REVISION = '185';" in three_core
    assert "/static/three/three.module.js" in bamboo
    assert "/static/three/three.module.js" in foot_golf
    assert "cdnjs.cloudflare.com/ajax/libs/three.js" not in bamboo
    assert "unpkg.com/three" not in foot_golf


def test_sword_dojo_uses_local_three_and_blade_axis_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "router" / "swords.html").read_text(encoding="utf-8")

    assert '"three": "/static/three/three.module.js"' in html
    assert '"three/addons/": "/static/three/addons/"' in html
    assert "unpkg.com/three" not in html
    assert "userData.swordTipLocal" in html
    assert "estimateSwordTipSign(model)" in html
    assert "rotate the local +Y blade axis forward" in html
    assert "resetSwordPose();" in html
