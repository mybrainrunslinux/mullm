"""
muLLM CLI — works with or without the server running.

Usage:
    mullm "your question"              # send to server, or run inline
    mullm --serve                      # start server
    mullm --status                     # health check
    mullm --cost                       # session cost summary
    mullm --model MODEL "question"     # force model override
    mullm --tier TIER   "question"     # force tier override
    mullm --stream "question"          # streaming output (server must be running)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

_SERVER_URL = os.environ.get("MULLM_SERVER_URL", "https://127.0.0.1:6856")

# Session ID persisted for the lifetime of the process
_SESSION_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Rich / plain output helpers
# ---------------------------------------------------------------------------

def _has_rich() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


def _print_header(text: str):
    if _has_rich():
        from rich.console import Console
        Console().rule(f"[bold amber]{text}[/bold amber]")
    else:
        print(f"\n{'='*60}\n  {text}\n{'='*60}")


def _print_result(result: dict):
    tier    = result.get("tier", "?")
    model   = result.get("model_used", "?")
    cost    = result.get("cost", 0.0)
    latency = result.get("latency_ms", 0.0)
    response = result.get("response", "")
    cached  = result.get("cached", False)

    if _has_rich():
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        meta = f"[dim]tier={tier}  model={model}  cost=${cost:.6f}  latency={latency:.0f}ms"
        if cached:
            meta += "  [green](cached)[/green]"
        console.print(Panel(response, title="[bold green]muLLM[/bold green]", subtitle=meta))
    else:
        print(f"\n{response}\n")
        print(f"[tier={tier}  model={model}  cost=${cost:.6f}  latency={latency:.0f}ms{'  cached' if cached else ''}]")


def _print_error(msg: str):
    if _has_rich():
        from rich.console import Console
        Console().print(f"[bold red]Error:[/bold red] {msg}")
    else:
        print(f"Error: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Server communication
# ---------------------------------------------------------------------------

async def _server_query(content: str, session_id: str, model: str | None, tier: str | None) -> dict | None:
    """POST to /query on the running server. Returns None if server unreachable."""
    import httpx
    payload: dict = {"content": content, "session_id": session_id}
    if model:
        payload["model_override"] = model
    if tier:
        payload["tier_override"] = tier
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=False) as client:  # nosec B501 -- local self-signed muLLM server on 127.0.0.1
            resp = await client.post(f"{_SERVER_URL}/query", json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return None  # server not running — fall through to inline
    except Exception as exc:
        _print_error(f"Server error: {exc}")
        return None


async def _server_health() -> dict | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:  # nosec B501 -- local self-signed muLLM server on 127.0.0.1
            resp = await client.get(f"{_SERVER_URL}/health")
            return resp.json()
    except Exception:
        return None


async def _server_stream(content: str, session_id: str):
    """Stream output from server SSE endpoint."""
    import httpx
    params = {"content": content, "session_id": session_id}
    try:
        async with httpx.AsyncClient(timeout=120.0, verify=False) as client:  # nosec B501 -- local self-signed muLLM server on 127.0.0.1
            async with client.stream("GET", f"{_SERVER_URL}/query/stream", params=params) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload == "[DONE]":
                            print()
                            break
                        try:
                            chunk = json.loads(payload)
                            if "error" in chunk:
                                _print_error(chunk["error"])
                                break
                            print(chunk.get("chunk", ""), end="", flush=True)
                        except json.JSONDecodeError:
                            pass
    except Exception as exc:
        _print_error(f"Streaming error: {exc}")


# ---------------------------------------------------------------------------
# Inline pipeline (no server required)
# ---------------------------------------------------------------------------

async def _inline_query(content: str, session_id: str, model: str | None, tier: str | None) -> dict:
    """Run the pipeline directly without a server."""
    from router.models import QueryRequest, TierLabel
    from router.tiers import execute_pipeline

    tier_label = None
    if tier:
        try:
            tier_label = TierLabel(tier)
        except ValueError:
            _print_error(
                f"Unknown tier: {tier}. Valid: groundtruth, cache, local, "
                "cloud_cheap, cloud_full, cloud_power"
            )
            sys.exit(1)

    request = QueryRequest(
        content=content,
        session_id=session_id,
        tier_override=tier_label,
        model_override=model,
    )
    result = await execute_pipeline(request)
    return result.model_dump()


def _bench_archive_payload(name: str = "archive") -> dict:
    """Return archived benchmark data without starting live model/provider work."""
    from fastapi import HTTPException

    from router import bench_api

    if name in ("archive", "list"):
        return bench_api._archive_meta()  # archive-only; never spends money
    if name in ("last", "humaneval", "humaneval-lock"):
        payload = bench_api._humaneval_lock_payload()
        if payload is None:
            raise SystemExit("HumanEval lock artifact is not available") from None
        return payload
    try:
        filename = bench_api.ENDPOINT_FILES[name]
    except KeyError:
        valid = ", ".join(sorted(["archive", *bench_api.ENDPOINT_FILES]))
        raise SystemExit(f"Unknown benchmark '{name}'. Valid: {valid}") from None
    try:
        result = bench_api._load_json(filename)
    except HTTPException as exc:
        raise SystemExit(str(exc.detail)) from None
    return {"mode": "archive", "source": filename, "result": result}


def _run_live_benchmark(bench_name: str, allow_spend: bool, cap_usd: float) -> int:
    """Run local benchmark harnesses only after explicit spend consent."""
    if not allow_spend:
        raise SystemExit(
            "Live benchmark runs are disabled by default. Use --spend and set "
            "MULLM_ALLOW_SPEND=1 when cloud/provider calls are acceptable."
        )
    os.environ.setdefault("MULLM_ALLOW_SPEND", "1")
    os.environ.setdefault("MULLM_TEST_SPEND_CAP_USD", str(cap_usd))
    script = Path(__file__).resolve().parents[1] / "scripts" / "bench_runners.py"
    args = [sys.executable, str(script)]
    if bench_name == "mullm-only":
        args.append("--mullm-only")
    elif bench_name == "all":
        args.append("--all")
    elif bench_name not in ("auto", "default"):
        raise SystemExit("Live bench choices: auto, mullm-only, all")
    return subprocess.call(args)


def _safe_app_slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", "", text).strip() or "Game"
    return re.sub(r"\s+", "", cleaned.lower())[:24] or "game"


def _resolve_game_html(path_or_name: str) -> Path:
    raw = Path(path_or_name)
    candidates = [raw]
    if raw.suffix.lower() != ".html":
        candidates.extend([
            raw.with_suffix(".html"),
            Path("code") / "ready" / f"{path_or_name}.html",
            Path("code") / "ready" / f"{path_or_name.replace('_', '-')}.html",
        ])
    else:
        candidates.append(Path("code") / "ready" / raw.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise SystemExit(f"HTML game file not found: {path_or_name}")


def _android_sdk_dir() -> Path:
    for raw in (os.getenv("ANDROID_HOME"), os.getenv("ANDROID_SDK_ROOT"), str(Path.home() / "android-sdk")):
        if raw and Path(raw).exists():
            return Path(raw).resolve()
    raise SystemExit(
        "Android SDK not found. Set ANDROID_HOME or ANDROID_SDK_ROOT, "
        "or run the Android setup script before --apk."
    )


def _node_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for candidate in (Path("/usr/local/bin") / name, Path("/opt/homebrew/bin") / name):
        if candidate.exists():
            return str(candidate)
    raise SystemExit(f"{name} not found on PATH; install Node.js before --apk.")


def _extract_html_title(html: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    raw = match.group(1).strip() if match else fallback
    return re.sub(r"\s+", " ", raw).strip() or fallback


def _build_apk(html_file: str, output_dir: str | None = None, keep_project: bool = False) -> str:
    """Build a debug Android APK from a self-contained HTML game."""
    html_path = _resolve_game_html(html_file)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    app_name = _extract_html_title(html, html_path.stem.replace("-", " ").title())
    slug = _safe_app_slug(app_name)
    app_id = f"com.mullm.{slug}"
    sdk_dir = _android_sdk_dir()
    npm = _node_tool("npm")
    npx = _node_tool("npx")

    out_dir = Path(output_dir or "dist/apks").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    apk_dest = out_dir / f"{slug}-debug.apk"

    tmp = Path(tempfile.mkdtemp(prefix="mullm_apk_"))
    try:
        www = tmp / "www"
        www.mkdir()
        shutil.copy(html_path, www / "index.html")
        (tmp / "capacitor.config.json").write_text(
            json.dumps(
                {
                    "appId": app_id,
                    "appName": app_name,
                    "webDir": "www",
                    "server": {"androidScheme": "https"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (tmp / "package.json").write_text(
            json.dumps({"name": slug, "version": "1.0.0", "private": True}, indent=2),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "ANDROID_HOME": str(sdk_dir),
            "ANDROID_SDK_ROOT": str(sdk_dir),
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
        }

        def run(label: str, cmd: list[str], cwd: Path = tmp, timeout_s: int = 600) -> str:
            print(f"[apk] {label}...", file=sys.stderr, flush=True)
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or "") + (exc.stderr or "")
                raise SystemExit(
                    f"{label} timed out after {timeout_s}s:\n{output[-1200:]}"
                ) from exc
            output = proc.stdout + proc.stderr
            if proc.returncode != 0:
                raise SystemExit(f"{label} failed ({' '.join(cmd)}):\n{output[-1600:]}")
            return output

        run("install Capacitor Android dependencies", [npm, "install", "@capacitor/core", "@capacitor/cli", "@capacitor/android", "--save"], timeout_s=300)
        run("create Capacitor Android project", [npx, "cap", "add", "android"], timeout_s=180)
        (tmp / "android" / "local.properties").write_text(f"sdk.dir={sdk_dir}\n", encoding="utf-8")
        public = tmp / "android" / "app" / "src" / "main" / "assets" / "public"
        public.mkdir(parents=True, exist_ok=True)
        shutil.copy(www / "index.html", public / "index.html")
        gradlew = tmp / "android" / "gradlew"
        gradlew.chmod(0o755)
        run("assemble debug APK", ["./gradlew", "assembleDebug", "--no-daemon", "-q"], cwd=tmp / "android", timeout_s=600)
        built = tmp / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if not built.exists():
            raise SystemExit("Gradle completed but app-debug.apk was not produced.")
        shutil.copy(built, apk_dest)
        return str(apk_dest)
    finally:
        if keep_project:
            print(f"Capacitor project kept at {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


async def _orchestrate_from_cli(args: argparse.Namespace) -> int:
    """Run the repo orchestrator through a guarded CLI surface."""
    from router.orchestrator import Orchestrator

    if args.self_update and not args.apply:
        raise SystemExit("--self-update is only meaningful with --apply")
    if args.apply and not args.self_update:
        raise SystemExit("Refusing to apply code changes without --self-update")
    orch = Orchestrator(
        api_url=args.server_url,
        repo_root=os.getcwd(),
        verify_cmd=args.verify or "",
        task_timeout=args.timeout,
    )
    if args.orchestrate and Path(args.orchestrate).exists():
        plan = await orch.plan_from_file(args.orchestrate)
    else:
        plan = await orch.plan_from_tasks([args.orchestrate])
    if args.dry_run:
        print(json.dumps({
            "mode": "orchestrate",
            "dry_run": True,
            "tasks": [task.__dict__ for task in plan.tasks],
            "estimated_cost": plan.total_estimated_cost,
        }, indent=2))
        return 0
    results = await orch.execute(
        plan,
        code_mode=args.code,
        apply=args.apply,
        cost_optimize=args.cost_optimize,
        tdd=not args.no_tdd,
        bugfix_tdd=args.bugfix_tdd,
        verify_on_failure=True,
        task_file=args.orchestrate or "",
        onefile=args.onefile,
        target_file=args.target_file or "",
    )
    print(json.dumps(results, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Service installer
# ---------------------------------------------------------------------------

def _install_service() -> int:
    """Install muLLM as a persistent background service for the current OS."""
    import platform

    from router.config import _default_state_dir

    print("WARNING: this enables muLLM to start automatically at every login/startup.")
    print("Local inference may load a large GPU model and keep substantial VRAM, RAM, and power in use.")
    print("The background service will not open the setup browser.\n")

    python_bin = Path(sys.executable).resolve()
    system = platform.system()
    state_dir = _default_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    certs_dir = state_dir / "certs"
    ssl_cert = certs_dir / "server.crt"
    ssl_key = certs_dir / "server.key"
    has_https = ssl_cert.exists() and ssl_key.exists()

    if system == "Linux":
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_file = service_dir / "mullm.service"
        service_dir.mkdir(parents=True, exist_ok=True)

        env_lines = [
            "Environment=PYTHONUNBUFFERED=1",
            "Environment=MULLM_REMOTE_ACCESS=true",
            "Environment=MULLM_OPEN_BROWSER=0",
            f"Environment=MULLM_STATE_DIR={state_dir}",
        ]
        if has_https:
            env_lines += [
                f"Environment=MULLM_SSL_CERTFILE={ssl_cert}",
                f"Environment=MULLM_SSL_KEYFILE={ssl_key}",
            ]

        service_content = f"""[Unit]
Description=muLLM local LLM router ({"HTTPS" if has_https else "HTTP"} :6856)
After=network.target

[Service]
Type=simple
WorkingDirectory={state_dir}
ExecStart={python_bin} -m router.main
Restart=on-failure
RestartSec=5
{chr(10).join(env_lines)}

[Install]
WantedBy=default.target
"""
        service_file.write_text(service_content)
        print(f"Service file written: {service_file}")

        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)  # nosec B603, B607
            subprocess.run(["systemctl", "--user", "enable", "mullm"], check=True)  # nosec B603, B607
            print("Service enabled — muLLM will start automatically on every login.")
            print("WARNING: local inference may load a GPU model and consume substantial VRAM and power.")
            ans = input("Start now? [Y/n] ").strip().lower()
            if ans in ("", "y"):
                subprocess.run(["systemctl", "--user", "start", "mullm"], check=True)  # nosec B603, B607
                print("Service started.")
                print("  mullm --status   # check health")
        except subprocess.CalledProcessError as exc:
            print(f"systemctl error: {exc}")
            print("You can start manually: systemctl --user start mullm")

    elif system == "Darwin":
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        plist_file = agents_dir / "com.mullm.router.plist"
        agents_dir.mkdir(parents=True, exist_ok=True)

        env_block = "    <key>EnvironmentVariables</key>\n    <dict>\n"
        env_block += "      <key>PYTHONUNBUFFERED</key><string>1</string>\n"
        env_block += "      <key>MULLM_REMOTE_ACCESS</key><string>true</string>\n"
        env_block += "      <key>MULLM_OPEN_BROWSER</key><string>0</string>\n"
        env_block += f"      <key>MULLM_STATE_DIR</key><string>{state_dir}</string>\n"
        if has_https:
            env_block += f"      <key>MULLM_SSL_CERTFILE</key><string>{ssl_cert}</string>\n"
            env_block += f"      <key>MULLM_SSL_KEYFILE</key><string>{ssl_key}</string>\n"
        env_block += "    </dict>"

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mullm.router</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python_bin}</string>
    <string>-m</string>
    <string>router.main</string>
  </array>
  <key>WorkingDirectory</key><string>{state_dir}</string>
{env_block}
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{logs_dir / "mullm.log"}</string>
  <key>StandardErrorPath</key><string>{logs_dir / "mullm-err.log"}</string>
</dict>
</plist>
"""
        plist_file.write_text(plist_content)
        print(f"LaunchAgent plist written: {plist_file}")

        try:
            subprocess.run(["launchctl", "load", "-w", str(plist_file)], check=True)  # nosec B603, B607
            print("Service loaded — muLLM will start automatically on every login.")
            print("WARNING: local inference may load a GPU model and consume substantial VRAM and power.")
            ans = input("Start now? [Y/n] ").strip().lower()
            if ans in ("", "y"):
                subprocess.run(["launchctl", "start", "com.mullm.router"], check=True)  # nosec B603, B607
                print("Service started.")
        except subprocess.CalledProcessError as exc:
            print(f"launchctl error: {exc}")
            print(f"You can load manually: launchctl load -w {plist_file}")

    elif system == "Windows":
        scripts_dir = state_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        bat_file = scripts_dir / "start_mullm.bat"

        env_set = (
            "set PYTHONUNBUFFERED=1\r\n"
            "set MULLM_REMOTE_ACCESS=true\r\n"
            "set MULLM_OPEN_BROWSER=0\r\n"
            f"set MULLM_STATE_DIR={state_dir}\r\n"
        )
        if has_https:
            env_set += f"set MULLM_SSL_CERTFILE={ssl_cert}\r\nset MULLM_SSL_KEYFILE={ssl_key}\r\n"

        bat_content = f"@echo off\r\n{env_set}cd /d \"{state_dir}\"\r\n\"{python_bin}\" -m router.main\r\n"
        bat_file.write_text(bat_content)

        print(f"Startup script written: {bat_file}")
        print()
        print("To run on startup, add a Task Scheduler entry:")
        print("WARNING: this starts muLLM at every login; local models may use substantial GPU VRAM and power.")
        print("  1. Open Task Scheduler → Create Basic Task")
        print('  2. Trigger: "When I log on"')
        print(f'  3. Action: Start Program → "{bat_file}"')
        print()
        print("Or with NSSM (Non-Sucking Service Manager):")
        print(f'  nssm install mullm "{python_bin}" "-m" "router.main"')
        print(f'  nssm set mullm AppDirectory "{state_dir}"')
        print("  nssm start mullm")

    else:
        print(f"Unsupported platform: {system}")
        print("Manual service setup:")
        print(f"  Python: {python_bin}")
        print(f"  Command: {python_bin} -m router.main")
        print(f"  Working directory: {state_dir}")
        return 1

    protocol = "https" if has_https else "http"
    print(f"\nOnce running: {protocol}://localhost:6856/health")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="mullm",
        description="muLLM - local-first LLM router (port 6856)",
    )
    parser.add_argument("query", nargs="?", help="Question or prompt to route")
    parser.add_argument("--serve",   action="store_true", help="Start the muLLM server")
    parser.add_argument("--status",  action="store_true", help="Health check")
    parser.add_argument("--cost",    action="store_true", help="Show session cost summary")
    parser.add_argument("--model",   metavar="MODEL", help="Force model override")
    parser.add_argument("--tier",    metavar="TIER",  help="Force tier: local | cloud_cheap | cloud_full | cloud_power")
    parser.add_argument("--stream",  action="store_true", help="Stream output (requires server)")
    parser.add_argument("--session", metavar="ID", default=_SESSION_ID, help="Session ID")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--attribution-line", action="store_true",
                        help="Print Co-authored-by trailer (for use in git hooks / scripts)")
    parser.add_argument("--install-service", action="store_true",
                        help="Enable automatic startup at login (may keep a GPU model/VRAM active)")
    parser.add_argument("--install-git-hook", action="store_true",
                        help="Install prepare-commit-msg hook in current repo")
    parser.add_argument("--remove-git-hook", action="store_true",
                        help="Remove the mullm prepare-commit-msg hook")
    parser.add_argument("--bench", nargs="?", const="archive",
                        help="Show archived benchmark results by default; use --bench-run for live runs")
    parser.add_argument("--bench-run", nargs="?", const="auto",
                        help="Run a live benchmark harness; requires --spend and MULLM_ALLOW_SPEND=1")
    parser.add_argument("--apk", metavar="HTML", nargs="?", const="index.html",
                        help="Build a debug Android APK from an HTML game file")
    parser.add_argument("--apk-output-dir", default="dist/apks", help="Directory for APK output")
    parser.add_argument("--keep-apk-project", action="store_true", help="Keep temporary Capacitor project for debugging")
    parser.add_argument("--spend", action="store_true",
                        help="Allow spend-gated benchmark/provider tests")
    parser.add_argument("--spend-cap", type=float, default=1.0,
                        help="Hard cap hint for spend-gated runs")
    parser.add_argument("--orchestrate", metavar="TASK_OR_FILE",
                        help="Plan and execute a repo task or markdown task file")
    parser.add_argument("--code", action="store_true", help="Ask orchestrator for code patches")
    parser.add_argument("--apply", action="store_true", help="Apply orchestrator patches")
    parser.add_argument("--self-update", action="store_true",
                        help="Allow muLLM to modify this repo during orchestrate")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not execute")
    parser.add_argument("--verify", default="", help="Verification command for orchestrator")
    parser.add_argument("--timeout", type=int, default=600, help="Task timeout seconds")
    parser.add_argument("--cost-optimize", action="store_true", help="Prefer cheaper tiers")
    parser.add_argument("--no-tdd", action="store_true", help="Disable orchestrator TDD prompt mode")
    parser.add_argument("--bugfix-tdd", action="store_true",
                        help="Write a discriminating failing test first, verify it fails on bugged code, then fix")
    parser.add_argument("--server-url", default=_SERVER_URL, help="muLLM server URL for orchestrator")
    parser.add_argument("--onefile", action="store_true",
                        help="Consolidate all tasks into a single output file (required for new game builds)")
    parser.add_argument("--target-file", metavar="FILE",
                        help="Output file path for --onefile mode (e.g. code/ready/my-game.html)")

    args = parser.parse_args()

    if args.version:
        from router.config import settings
        print(f"muLLM v{settings.version}")
        return

    if args.attribution_line:
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(f"{_SERVER_URL}/api/attribution", timeout=3) as r: # nosec B310 -- hardcoded localhost URL, not user input
                data = json.loads(r.read())
            trailer = data.get("trailer")
            if trailer:
                print(trailer)
        except urllib.error.URLError:
            # Server not running — read settings directly
            from router.config import settings as _s
            mode = _s.COMMIT_ATTRIBUTION_MODE
            if mode != "never":
                print(f"Co-authored-by: {_s.COMMIT_ATTRIBUTION_NAME} <{_s.COMMIT_ATTRIBUTION_EMAIL}>")
        return

    if args.install_service:
        raise SystemExit(_install_service())

    if args.install_git_hook:
        import urllib.error
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/attribution/install-hook",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r: # nosec B310 -- hardcoded localhost URL, not user input
                data = json.loads(r.read())
            print(f"Hook installed: {data.get('path')}")
        except urllib.error.URLError:
            _print_error("muLLM server is not running (try: mullm --serve)")
            sys.exit(1)
        return

    if args.remove_git_hook:
        import urllib.error
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{_SERVER_URL}/api/attribution/install-hook",
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            with urllib.request.urlopen(req, timeout=5) as r: # nosec B310 -- hardcoded localhost URL, not user input
                data = json.loads(r.read())
            if data.get("removed"):
                print("Hook removed.")
            else:
                print(f"Nothing to remove: {data.get('reason')}")
        except urllib.error.URLError:
            _print_error("muLLM server is not running (try: mullm --serve)")
            sys.exit(1)
        return

    if args.bench:
        print(json.dumps(_bench_archive_payload(args.bench), indent=2))
        return

    if args.bench_run:
        if os.getenv("MULLM_ALLOW_SPEND") != "1":
            _print_error("Refusing live benchmark: set MULLM_ALLOW_SPEND=1 and pass --spend.")
            sys.exit(2)
        try:
            raise SystemExit(_run_live_benchmark(args.bench_run, args.spend, args.spend_cap))
        except SystemExit:
            raise

    if args.apk:
        apk_path = _build_apk(args.apk, output_dir=args.apk_output_dir, keep_project=args.keep_apk_project)
        print(apk_path)
        return

    if args.orchestrate:
        raise SystemExit(asyncio.run(_orchestrate_from_cli(args)))

    if args.serve:
        from router.main import serve
        serve()
        return

    if args.status:
        result = asyncio.run(_server_health())
        if result is None:
            _print_error("muLLM server is not running (try: mullm --serve)")
            sys.exit(1)
        if _has_rich():
            from rich.console import Console
            Console().print_json(json.dumps(result))
        else:
            print(json.dumps(result, indent=2))
        return

    if args.cost:
        # Cost requires server or local scorer
        result = asyncio.run(_server_health())
        if result is None:
            # Read from local scorer
            from router.scorer import get_all_session_summaries
            summaries = get_all_session_summaries()
            if not summaries:
                print("No session cost data available.")
            else:
                for sid, s in summaries.items():
                    print(f"Session {sid[:8]}…  cost=${s.total_cost:.6f}  queries={s.query_count}  status={s.budget_status}")
        else:
            import httpx
            try:
                resp = httpx.get(f"{_SERVER_URL}/api/dashboard", timeout=5.0)
                data = resp.json()
                print(f"Total queries: {data.get('total_queries', 0)}")
                print(f"Total cost:    ${data.get('total_cost', 0):.6f}")
                print(f"Cost reduction: {data.get('cost_reduction_pct', 0):.1f}%")
            except Exception as exc:
                _print_error(str(exc))
        return

    if not args.query:
        parser.print_help()
        return

    # ── Query mode ───────────────────────────────────────────────────────
    if args.stream:
        asyncio.run(_server_stream(args.query, args.session))
        return

    # Try server first; fall back to inline
    result = asyncio.run(_server_query(args.query, args.session, args.model, args.tier))
    if result is None:
        # Inline mode
        if _has_rich():
            from rich.console import Console
            Console().print("[dim]Server not running - executing inline pipeline...[/dim]")
        result = asyncio.run(_inline_query(args.query, args.session, args.model, args.tier))

    _print_result(result)


def main_09():
    """Entry point for the `mullm0.9` command — same CLI against the 0.9 server on port 16856.

    Explicit MULLM_SERVER_URL / MULLM_PORT environment variables still win.
    """
    global _SERVER_URL
    os.environ.setdefault("MULLM_SERVER_URL", "https://127.0.0.1:16856")
    os.environ.setdefault("MULLM_PORT", "16856")
    _SERVER_URL = os.environ["MULLM_SERVER_URL"]
    try:
        from router.config import settings as _s
        if _s.port == 6856:  # only override the stock default
            _s.port = 16856  # type: ignore[assignment]
    except Exception:
        pass
    main()


if __name__ == "__main__":
    main()
