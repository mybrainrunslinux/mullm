from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forest3d_reimagined_page_has_router_pipeline_and_gpu_gate():
    html = (ROOT / "router" / "forest3d.html").read_text(encoding="utf-8")

    assert "Forest 3D Routing View" in html
    assert "GPU estimate" in html
    assert "fetch('/api/dashboard')" in html
    assert "CLASSIFY" in html
    assert "CACHE" in html
    assert "CLOUD" in html


def test_skyrail_archer_is_portrait_fair_and_playable():
    html = (ROOT / "router" / "skyrail-archer.html").read_text(encoding="utf-8")

    assert "Skyrail Archer" in html
    assert "Equal-screen rule" in html
    assert "Math.min(vw, vh*.62)" in html
    assert "deviceorientation" in html
    assert "function fire()" in html
    assert "const bows=" in html
