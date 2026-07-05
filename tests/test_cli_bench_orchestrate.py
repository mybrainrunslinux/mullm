import argparse
import os
import subprocess
from pathlib import Path

import pytest

from router import bench_api, cli
from router.benchmarks import runner


def test_cli_bench_archive_never_spends(monkeypatch):
    monkeypatch.delenv("MULLM_ALLOW_SPEND", raising=False)

    payload = cli._bench_archive_payload("archive")

    assert payload["mode"] == "archive"
    assert payload["live_rerun"] is False


def test_cli_bench_last_uses_humaneval_lock(tmp_path, monkeypatch):
    lock = tmp_path / "humaneval_full_lock.json"
    lock.write_text(
        """{
          "locked": true,
          "locked_at": "2026-04-09",
          "session": 31,
          "headline": "164/164 = 100% pass@1 at $0.00",
          "result": {
            "local": {"passed": 164, "total": 164, "pass_at_1": 1.0, "cost": 0.0}
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(bench_api, "HUMANEVAL_LOCK", lock)

    payload = cli._bench_archive_payload("last")

    assert payload["source"].endswith("humaneval_full_lock.json")
    assert payload["live_rerun"] is False
    assert payload["result"]["local"]["passed"] == 164
    assert payload["result"]["local"]["pass_at_1"] == 1.0


def test_cli_bench_archive_exposes_multipl_e_and_pr_gauntlet_110(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "multipl_e_results.json").write_text('[{"passed": true, "language": "py"}]', encoding="utf-8")
    (archive / "pr_gauntlet_hard_v14_results.json").write_text(
        '{"score": 20, "final": 110, "results": [{"issue": 1, "fixed": true}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bench_api, "ARCHIVE", archive)

    multipl = cli._bench_archive_payload("multipl-e")
    gauntlet = cli._bench_archive_payload("pr-gauntlet-hard")

    assert multipl["source"] == "multipl_e_results.json"
    assert multipl["result"][0]["language"] == "py"
    assert gauntlet["source"] == "pr_gauntlet_hard_v14_results.json"
    assert gauntlet["result"]["final"] == 110


def test_cli_live_benchmark_requires_explicit_spend(monkeypatch):
    monkeypatch.delenv("MULLM_ALLOW_SPEND", raising=False)

    with pytest.raises(SystemExit, match="Live benchmark runs are disabled"):
        cli._run_live_benchmark("auto", allow_spend=False, cap_usd=1.0)


def test_cli_live_benchmark_sets_spend_cap(monkeypatch):
    calls = []
    monkeypatch.setenv("MULLM_ALLOW_SPEND", "1")
    monkeypatch.delenv("MULLM_TEST_SPEND_CAP_USD", raising=False)
    monkeypatch.setattr(subprocess, "call", lambda args: calls.append(args) or 0)

    assert cli._run_live_benchmark("mullm-only", allow_spend=True, cap_usd=0.25) == 0

    assert os.environ["MULLM_TEST_SPEND_CAP_USD"] == "0.25"
    assert calls and calls[0][-1] == "--mullm-only"


@pytest.mark.asyncio
async def test_bench_run_requires_spend(monkeypatch):
    monkeypatch.delenv("MULLM_ALLOW_SPEND", raising=False)

    with pytest.raises(Exception, match="Live benchmark runs require"):
        await bench_api.bench_run({"mode": "humaneval", "spend": False})


@pytest.mark.asyncio
async def test_full_bench_returns_humaneval_lock_without_spend(tmp_path, monkeypatch):
    lock = tmp_path / "humaneval_full_lock.json"
    lock.write_text(
        """{
          "locked": true,
          "headline": "164/164 = 100% pass@1 at $0.00",
          "result": {
            "local": {"passed": 164, "total": 164, "pass_at_1": 1.0, "cost": 0.0}
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(bench_api, "HUMANEVAL_LOCK", lock)
    monkeypatch.delenv("MULLM_ALLOW_SPEND", raising=False)

    response = await bench_api.bench_run({"mode": "full"})

    assert response.status_code == 423


@pytest.mark.asyncio
async def test_run_stream_requires_spend(monkeypatch):
    monkeypatch.delenv("MULLM_ALLOW_SPEND", raising=False)

    with pytest.raises(Exception, match="stream reruns require"):
        await bench_api.bench_run_stream({"stream": "local", "spend": False})


@pytest.mark.asyncio
async def test_bench_last_returns_humaneval_lock(tmp_path, monkeypatch):
    lock = tmp_path / "humaneval_full_lock.json"
    lock.write_text(
        """{
          "locked": true,
          "locked_at": "2026-04-09",
          "session": 31,
          "headline": "164/164 = 100% pass@1 at $0.00",
          "result": {
            "local": {"passed": 164, "total": 164, "pass_at_1": 1.0, "cost": 0.0},
            "mullm": {"passed": 164, "total": 164, "pass_at_1": 1.0, "cost": 0.0}
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(bench_api, "HUMANEVAL_LOCK", lock)

    payload = await bench_api.bench_last()

    assert payload["result"]["benchmark"] == "humaneval"
    assert payload["result"]["local"]["passed"] == 164
    assert payload["result"]["streams"]["mullm"]["pass_at_1"] == 1.0
    assert payload["live_rerun"] is False


@pytest.mark.asyncio
async def test_bench_run_starts_spend_gated_job(tmp_path, monkeypatch):
    started = {}

    monkeypatch.setenv("MULLM_ALLOW_SPEND", "1")
    monkeypatch.setattr(bench_api, "BENCH_JOBS", tmp_path / "bench_jobs.jsonl")
    monkeypatch.setattr(bench_api, "BENCH_RESULTS", tmp_path / "bench_results")

    def fake_create_task(coro):
        started["task_created"] = True
        coro.close()

    monkeypatch.setattr(bench_api.asyncio, "create_task", fake_create_task)

    job = await bench_api.bench_run({"mode": "humaneval", "spend": True, "spend_cap": 0.01})

    assert job["status"] == "started"
    assert job["mode"] == "humaneval"
    assert job["force_tier"] == "local"
    assert job["limit"] == 164
    assert started["task_created"] is True


def test_humaneval_prefix_order_is_default(monkeypatch):
    from router.benchmarks.humaneval import PROBLEMS

    monkeypatch.delenv("MULLM_BENCH_SAMPLE", raising=False)

    selected = runner._select_humaneval_problems(PROBLEMS, 3)

    assert [p["task_id"] for p in selected] == ["HumanEval/0", "HumanEval/2", "HumanEval/3"]


def test_humaneval_explicit_task_id_selection():
    problems = [
        {"task_id": "HumanEval/0"},
        {"task_id": "HumanEval/70"},
        {"task_id": "HumanEval/163"},
    ]

    selected = runner._select_humaneval_task_ids(problems, ["HumanEval/70", "HumanEval/0"])

    assert [p["task_id"] for p in selected] == ["HumanEval/70", "HumanEval/0"]


def test_humaneval_explicit_task_id_selection_rejects_unknown():
    problems = [{"task_id": "HumanEval/0"}]

    with pytest.raises(ValueError, match="HumanEval/999"):
        runner._select_humaneval_task_ids(problems, ["HumanEval/999"])


def test_humaneval_strict_mode_calls_check(monkeypatch):
    monkeypatch.delenv("MULLM_BENCH_LEGACY_NO_CHECK_CALL", raising=False)

    test_code = "def check(candidate):\n    assert candidate([]) == []\n"

    prepared = runner._prepare_humaneval_test_code(test_code, "has_close_elements")

    assert "check(has_close_elements)" in prepared


def test_humaneval_legacy_mode_preserves_original_test_body(monkeypatch):
    monkeypatch.setenv("MULLM_BENCH_LEGACY_NO_CHECK_CALL", "1")

    test_code = "def check(candidate):\n    assert candidate([]) == []\n"
    prepared = runner._prepare_humaneval_test_code(test_code, "has_close_elements")

    assert prepared == test_code


def test_cli_apk_resolves_packaged_game_name():
    path = cli._resolve_game_html("crokinole2")

    assert path.name == "crokinole2.html"
    assert path.exists()


def test_cli_apk_slug_and_title_helpers(tmp_path):
    html = tmp_path / "demo.html"
    html.write_text("<!doctype html><title>Crokinole 2!</title>", encoding="utf-8")

    title = cli._extract_html_title(html.read_text(encoding="utf-8"), "Fallback")

    assert title == "Crokinole 2!"
    assert cli._safe_app_slug(title) == "crokinole2"
    assert isinstance(Path(cli._resolve_game_html(str(html))), Path)


@pytest.mark.asyncio
async def test_orchestrate_refuses_apply_without_self_update():
    args = argparse.Namespace(
        self_update=False,
        apply=True,
        server_url="http://127.0.0.1:6856",
        verify="",
        timeout=600,
        orchestrate="add a comment",
        dry_run=False,
        code=True,
        cost_optimize=False,
        no_tdd=False,
    )

    with pytest.raises(SystemExit, match="without --self-update"):
        await cli._orchestrate_from_cli(args)


@pytest.mark.asyncio
async def test_orchestrate_dry_run_plans_without_apply(capsys):
    args = argparse.Namespace(
        self_update=False,
        apply=False,
        server_url="http://127.0.0.1:6856",
        verify="",
        timeout=600,
        orchestrate="Add a tiny test",
        dry_run=True,
        code=True,
        cost_optimize=False,
        no_tdd=False,
    )

    assert await cli._orchestrate_from_cli(args) == 0
    assert '"dry_run": true' in capsys.readouterr().out
