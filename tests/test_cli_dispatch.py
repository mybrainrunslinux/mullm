"""Unit tests for mullm_cli dispatch logic — no server required."""
import argparse
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_args(**kwargs):
    """Build a minimal args namespace mimicking argparse output."""
    defaults = dict(
        content=[],
        dashboard=False,
        classify=False,
        health=False,
        perf=False,
        index=False,
        plan=None,
        orchestrate=None,
        stream=False,
        split=False,
        dry_run=False,
        code=False,
        apply=False,
        file="",
        fast=False,
        cost_optimize=False,
        no_tdd=False,
        git_commit=False,
        feature_branches=0,
        resume=False,
        apk=None,
        serve=False,
        serve_port=8181,
        verify="",
        timeout=600,
        powerup=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestApkServeDispatch(unittest.TestCase):
    """--apk/--serve must NOT fire before --orchestrate runs."""

    def _run_dispatch(self, args, apk_mock, serve_mock):
        """Simulate the dispatch block in main() after arg parsing."""
        # Replicate the dispatch guard from mullm_cli.py
        if not getattr(args, "orchestrate", None):
            apk_result = None
            if getattr(args, "apk", None) is not None:
                apk_result = apk_mock(args.apk)
                if not getattr(args, "serve", False):
                    return "apk_only"
            if getattr(args, "serve", False):
                serve_mock(apk_result, port=getattr(args, "serve_port", 8181))
                return "serve_only"
        return "continue"

    def test_apk_standalone_fires(self):
        args = _make_args(apk="game.html")
        apk_mock = MagicMock(return_value="/home/peter/Game-debug.apk")
        serve_mock = MagicMock()
        result = self._run_dispatch(args, apk_mock, serve_mock)
        apk_mock.assert_called_once_with("game.html")
        serve_mock.assert_not_called()
        self.assertEqual(result, "apk_only")

    def test_serve_standalone_fires(self):
        args = _make_args(serve=True)
        apk_mock = MagicMock()
        serve_mock = MagicMock()
        result = self._run_dispatch(args, apk_mock, serve_mock)
        serve_mock.assert_called_once_with(None, port=8181)
        self.assertEqual(result, "serve_only")

    def test_apk_with_orchestrate_skips_standalone(self):
        """--apk --serve combined with --orchestrate must NOT run standalone dispatch."""
        args = _make_args(orchestrate="GAME.md", apk="index.html", serve=True)
        apk_mock = MagicMock()
        serve_mock = MagicMock()
        result = self._run_dispatch(args, apk_mock, serve_mock)
        apk_mock.assert_not_called()
        serve_mock.assert_not_called()
        self.assertEqual(result, "continue")

    def test_serve_with_orchestrate_skips_standalone(self):
        args = _make_args(orchestrate="GAME.md", serve=True)
        apk_mock = MagicMock()
        serve_mock = MagicMock()
        result = self._run_dispatch(args, apk_mock, serve_mock)
        serve_mock.assert_not_called()
        self.assertEqual(result, "continue")


class TestResumeFlag(unittest.TestCase):
    def test_resume_default_false(self):
        args = _make_args()
        self.assertFalse(getattr(args, "resume", False))

    def test_resume_set(self):
        args = _make_args(resume=True)
        self.assertTrue(args.resume)


class TestCmdServeApkMap(unittest.TestCase):
    """Regression: apk_map must be a plain dict comprehension, not {{...}} set literal."""

    def test_apk_map_is_dict_comprehension(self):
        import inspect

        import mullm_cli
        source = inspect.getsource(mullm_cli.cmd_serve)
        self.assertIn(
            "apk_map = {p.name: p for p in apks}",
            source,
            "apk_map uses {{...}} (set literal) — causes TypeError: unhashable type: 'dict'",
        )


class TestServiceInstall(unittest.TestCase):
    def test_linux_service_uses_runtime_state_not_package_dir(self):
        import router.cli as cli

        with (
            patch("router.cli.Path.home") as home_mock,
            patch("router.cli.sys.executable", "/tmp/venv/bin/python"),
            patch.dict(os.environ, {}, clear=True),
            patch("platform.system", return_value="Linux"),
            patch("subprocess.run") as run_mock,
            patch("builtins.input", return_value="n"),
        ):
            tmp_home = Path(self._testMethodName).resolve()
            tmp_home.mkdir(exist_ok=True)
            self.addCleanup(lambda: __import__("shutil").rmtree(tmp_home, ignore_errors=True))
            state_dir = tmp_home / "state"
            os.environ["MULLM_STATE_DIR"] = str(state_dir)
            home_mock.return_value = tmp_home

            result = cli._install_service()

        self.assertEqual(result, 0)
        service_file = tmp_home / ".config" / "systemd" / "user" / "mullm.service"
        service = service_file.read_text(encoding="utf-8")
        self.assertIn(f"WorkingDirectory={state_dir}", service)
        self.assertIn(f"Environment=MULLM_STATE_DIR={state_dir}", service)
        self.assertIn("ExecStart=/tmp/venv/bin/python -m router.main", service)
        self.assertNotIn("site-packages", service)
        run_mock.assert_any_call(["systemctl", "--user", "daemon-reload"], check=True)


if __name__ == "__main__":
    unittest.main()
