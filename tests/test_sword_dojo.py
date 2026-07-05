from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWORDS_HTML = ROOT / "router" / "swords.html"


def test_sword_dojo_calibrates_imported_glb_tip_and_hilt():
    html = SWORDS_HTML.read_text(encoding="utf-8")

    assert "function estimateSwordEndpoints(model)" in html
    assert "tipLocal: model.worldToLocal" in html
    assert "hiltLocal: model.worldToLocal" in html
    assert "const pivot = new THREE.Group()" in html
    assert "pivot.add(model)" in html
    assert "pivot.userData.swordTipLocal = pivot.worldToLocal(tipWorld)" in html
    assert "pivot.userData.swordHiltLocal = pivot.worldToLocal(hiltWorld)" in html
    assert "attachSword(prepareSwordGLTF(model, name))" in html
    assert "normalizedBox.max.y" not in html


def test_sword_dojo_stab_and_slash_use_readable_combat_motion():
    html = SWORDS_HTML.read_text(encoding="utf-8")

    assert "const progress = Math.min(attackTimer / duration, 1)" in html
    assert "shoulder-to-hip slice" in html
    assert "slashComboIndex = (slashComboIndex + 1) % 3" in html
    assert "Forehand: high outside shoulder to low inside hip" in html
    assert "Backhand: the same diagonal across the body" in html
    assert "align the local +Y blade axis to camera -Z" in html
    assert "const forward = lunge * 0.70" in html
    assert "THREE.MathUtils.lerp(pose.rotation.x, -Math.PI / 2, align)" in html


def test_sword_selector_stays_clickable_above_top_nav():
    html = SWORDS_HTML.read_text(encoding="utf-8")

    assert "#topbar {" in html
    assert "z-index: 1000;" in html
    assert "#sword-bar {" in html
    assert "top: 52px;" in html
    assert "z-index: 1100;" in html


def test_sword_selector_uses_asset_dropdown_without_stale_swordguns():
    html = SWORDS_HTML.read_text(encoding="utf-8")

    assert 'id="sword-select"' in html
    assert "Generate Sword..." in html
    assert "fetch('/api/3d-assets?category=weapon')" in html
    assert "document.createDocumentFragment()" in html
    assert "steampunk-swordgun" not in html
    assert "SWORDGUN" not in html
