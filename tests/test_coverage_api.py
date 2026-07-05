from pathlib import Path

import pytest
from fastapi import HTTPException

from router import coverage_api


def test_coverage_payload_has_live_shape():
    payload = coverage_api.coverage_payload()
    assert "coverage" in payload
    assert "specs" in payload
    assert "visual_artifacts" in payload
    assert "history" in payload
    assert isinstance(payload["total_specs"], int)


def test_coverage_artifact_guard_rejects_non_media():
    with pytest.raises(HTTPException) as exc:
        coverage_api._safe_artifact_path("router/main.py")
    assert exc.value.status_code == 404


def test_coverage_artifact_guard_rejects_missing_media():
    with pytest.raises(HTTPException) as exc:
        coverage_api._safe_artifact_path("test-results/not-present.png")
    assert exc.value.status_code == 404


def test_coverage_artifact_guard_allows_allowed_media(tmp_path, monkeypatch):
    media_dir = tmp_path / "test-results"
    media_dir.mkdir()
    image = media_dir / "shot.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(coverage_api, "ROOT", tmp_path)
    monkeypatch.setattr(coverage_api, "MEDIA_DIRS", [media_dir])

    assert coverage_api._safe_artifact_path(Path("test-results/shot.png").as_posix()) == image.resolve()
