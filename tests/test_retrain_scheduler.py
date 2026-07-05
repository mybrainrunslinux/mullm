from __future__ import annotations

import time

from router import retrain_scheduler


def test_retrain_status_counts_samples(monkeypatch, tmp_path):
    from router import config

    data = tmp_path / "train.csv"
    data.write_text("query,category\nhello,conversation\nbuild this,code\n", encoding="utf-8")
    monkeypatch.setattr(config.settings, "classifier_retrain_enabled", True)
    monkeypatch.setattr(config.settings, "classifier_retrain_schedule", "daily")
    monkeypatch.setattr(config.settings, "classifier_retrain_data_path", str(data))
    monkeypatch.setattr(config.settings, "classifier_retrain_min_samples", 2)

    status = retrain_scheduler.status()

    assert status["enabled"] is True
    assert status["interval_seconds"] == 86400
    assert status["sample_count"] == 2
    assert status["data_exists"] is True


def test_retrain_interval_parser():
    assert retrain_scheduler._interval_seconds("hourly") == 3600
    assert retrain_scheduler._interval_seconds("every:5m") == 300
    assert retrain_scheduler._interval_seconds("off") is None


def test_retrain_due_status_uses_last_started(monkeypatch, tmp_path):
    from router import config

    data = tmp_path / "train.csv"
    data.write_text("query,category\nhello,conversation\n", encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text('{"last_started_at": 1000}', encoding="utf-8")
    monkeypatch.setattr(retrain_scheduler, "STATE_PATH", state)
    monkeypatch.setattr(config.settings, "classifier_retrain_enabled", True)
    monkeypatch.setattr(config.settings, "classifier_retrain_schedule", "hourly")
    monkeypatch.setattr(config.settings, "classifier_retrain_data_path", str(data))

    status = retrain_scheduler.status()

    assert status["last_started_at"] == 1000
    assert status["next_due_at"] == 4600
    assert status["next_due_at"] < time.time()
