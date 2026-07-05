from router import page_registry


def test_studio_pages_are_not_allowed_in_regular_mode(monkeypatch):
    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "enable_studio", False)

    assert page_registry.page_allowed("chat") is True
    assert page_registry.page_allowed("comfyui") is False
    assert page_registry.page_allowed("games") is False
    assert page_registry.page_allowed("capyballista") is False
    assert page_registry.page_allowed("scene") is False
    assert page_registry.page_allowed("lighting") is False
    assert page_registry.page_allowed("forest3d") is False
    assert page_registry.page_allowed("skyrail-archer") is False


def test_studio_pages_allowed_when_module_enabled(monkeypatch):
    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)

    assert page_registry.page_allowed("comfyui") is True
    assert page_registry.page_allowed("capyballista") is True
    assert page_registry.page_allowed("studio") is True
    assert page_registry.page_allowed("lighting") is True
    assert page_registry.page_allowed("forest3d") is True
    assert page_registry.page_allowed("skyrail-archer") is True
    assert any(page["href"] == "/scene" for page in page_registry.visible_pages())
    assert any(page["href"] == "/capyballista" for page in page_registry.visible_pages())
