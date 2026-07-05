import pytest
from httpx import ASGITransport, AsyncClient

from router.languages import language_payload, normalize_enabled_languages
from router.main import app


def test_language_selection_always_keeps_english_and_limits_supported_codes():
    assert normalize_enabled_languages(["hu", "fr", "xx", "en", "hu"]) == ["en", "hu", "fr"]


def test_language_payload_marks_five_supported_additional_languages():
    payload = language_payload("hu,es,de,it,fr", {"en-hu": True, "hu-en": False})
    enabled = payload["enabled"]
    codes = {item["code"] for item in payload["languages"]}

    assert enabled == ["en", "hu", "es", "de", "it", "fr"]
    assert {"en", "hu", "es", "de", "it", "fr"}.issubset(codes)
    hu = next(item for item in payload["languages"] if item["code"] == "hu")
    assert hu["installed_pairs"]["en-hu"] is True


@pytest.mark.asyncio
async def test_language_setup_api_saves_enabled_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/languages", json={"enabled": ["hu", "de", "xx"]})

    assert response.status_code == 200
    assert response.json()["enabled"] == ["en", "hu", "de"]
    assert 'enabled = ["en", "hu", "de"]' in (tmp_path / "mullm.toml").read_text()
