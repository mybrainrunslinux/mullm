from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skip(reason="0101technology static site is out-of-band for muLLM parity right now")


def test_0101_data_visualizer_is_static_and_local_first():
    html = (ROOT / "sites" / "0101technology.com" / "data-visualizer.html").read_text(encoding="utf-8")

    assert "Local Data Visualizer" in html
    assert "No upload" in html
    assert "function parseCSV" in html
    assert "function downloadPNG" in html
    assert "function exportHTML" in html
    assert "fetch(" not in html


def test_0101_home_links_to_data_visualizer():
    html = (ROOT / "sites" / "0101technology.com" / "index.html").read_text(encoding="utf-8")

    assert '/data-visualizer.html' in html
