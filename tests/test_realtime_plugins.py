from router import realtime_plugins


def test_register_pattern_plugin_resolves_text():
    realtime_plugins.clear_plugins()
    realtime_plugins.register_plugin(
        realtime_plugins.RealtimePlugin(
            name="test",
            patterns=[(realtime_plugins.re.compile(r"^hello plugin$"), "hello from plugin")],
        )
    )

    assert realtime_plugins.resolve_with_plugins("hello plugin") == "hello from plugin"


def test_load_user_plugin_from_directory(tmp_path):
    realtime_plugins.clear_plugins()
    plugin = tmp_path / "demo_plugin.py"
    plugin.write_text(
        'PLUGIN_NAME = "demo"\n'
        'PATTERNS = [(r"^custom answer$", "from user plugin")]\n',
        encoding="utf-8",
    )

    loaded = realtime_plugins.load_user_plugins(tmp_path)

    assert loaded == ["demo"]
    assert realtime_plugins.resolve_with_plugins("custom answer") == "from user plugin"
