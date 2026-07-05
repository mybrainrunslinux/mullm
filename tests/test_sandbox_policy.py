from router import sandbox_policy


def test_sandbox_allows_project_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_mode", "workspace")
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_root", str(tmp_path))
    target = tmp_path / "allowed.txt"

    assert sandbox_policy.is_path_allowed(target)
    assert sandbox_policy.require_path_allowed(target) == target.resolve()


def test_sandbox_rejects_outside_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_mode", "workspace")
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_root", str(tmp_path))

    assert not sandbox_policy.is_path_allowed(tmp_path.parent / "outside.txt")


def test_sandbox_off_allows_outside_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_mode", "off")
    monkeypatch.setattr(sandbox_policy.settings, "sandbox_root", str(tmp_path))

    assert sandbox_policy.is_path_allowed(tmp_path.parent / "outside.txt")
