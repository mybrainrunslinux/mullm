#!/usr/bin/env python3
"""Spin up muLLM under three very different provider configs and compare routing.

  A  free-local   no cloud keys at all      — everything must resolve locally
  B  alt-cloud    Cerebras/DeepSeek/GLM only — no Anthropic/OpenAI/Google
  C  flagship     full key set               — Fable top tier + WITH RICE

Usage:  .venv/bin/python scripts/test_provider_configs.py [A B C]
Each config boots an isolated server (own port + state dir), runs the same
prompt battery, and prints a side-by-side of tier/model/cost/latency.
Costs are kept tiny (short prompts, word-capped answers).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

BATTERY = [
    ("groundtruth", {"content": "what is 17 * 23"}),
    ("local", {"content": "One catchy tagline for a steampunk gear-puzzle game. Under 15 words."}),
    ("cloud_full", {"content": "In under 60 words: when should a WebGL game prefer texture atlases over arrays?",
                     "force_tier": "cloud_full"}),
    ("cloud_power", {"content": "In under 60 words: biggest single risk when auto-rigging stylized characters?",
                      "force_tier": "cloud_power"}),
]

STRIP_ALWAYS = ["MULLM_CONFIG_PATH", "MULLM_ENV_FILE"]
BIG3 = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
        "MULLM_ANTHROPIC_API_KEY", "MULLM_OPENAI_API_KEY", "MULLM_GOOGLE_API_KEY"]
ALT = ["CEREBRAS_API_KEY", "DEEPSEEK_API_KEY", "GLM_API_KEY",
       "MULLM_CEREBRAS_API_KEY", "MULLM_DEEPSEEK_API_KEY", "MULLM_GLM_API_KEY"]


def load_env_file(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split("#")[0].strip().strip('"').strip("'")
    return out


def config_env(kind: str, port: int, state: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ALWAYS}
    dotenv = load_env_file(os.path.join(ROOT, ".env"))
    for k in BIG3 + ALT:
        env.pop(k, None)
    if kind == "A":
        pass  # no cloud keys at all
    elif kind == "B":
        for k in ALT:
            if dotenv.get(k):
                env[k] = dotenv[k]
        env["MULLM_PREFERRED_CLOUD_PROVIDER"] = "cerebras"
    elif kind == "C":
        env.update({k: v for k, v in dotenv.items() if k in BIG3 or k in ALT or k.endswith("API_KEY")})
    env.update({
        "MULLM_PORT": str(port),
        "MULLM_STATE_DIR": state,
        "MULLM_DEV_MODE": "true",
        "MULLM_AUTO_GENERATE_CERT": "false",   # plain http for the harness
        # local model comes from the machine's running config
        "CODE_MODEL": load_env_file(os.path.join(ROOT, ".env")).get("CODE_MODEL", "qwen3.6-35b-a3b-chat:latest"),
    })
    return env


def post(port: int, payload: dict, timeout: float = 240) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/query",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {"error": f"HTTP {e.code}", "detail": json.loads(e.read()).get("detail", "")}
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)[:120]}


def run_config(kind: str, label: str, port: int) -> list[dict]:
    state = tempfile.mkdtemp(prefix=f"mullm-cfg{kind}-")
    env = config_env(kind, port, state)
    env["PYTHONPATH"] = ROOT
    proc = subprocess.Popen([PY, "-m", "router.main"], cwd=state, env=env,
                            stdout=open(f"{state}/server.log", "w"), stderr=subprocess.STDOUT)
    rows = []
    try:
        for _ in range(40):
            time.sleep(1.5)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2, context=CTX)
                break
            except Exception:
                pass
        else:
            return [{"case": "boot", "error": "server did not start", "log": f"{state}/server.log"}]
        for case, payload in BATTERY:
            t0 = time.time()
            d = post(port, dict(payload))
            rows.append({
                "case": case,
                "tier": d.get("tier_used") or d.get("tier") or d.get("error", "?"),
                "model": (d.get("model_used") or d.get("detail") or "")[:46],
                "cost": d.get("cost", 0.0),
                "ms": round((time.time() - t0) * 1000),
                "answer": (d.get("response") or "")[:110].replace("\n", " "),
            })
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    return rows


def main() -> None:
    wanted = sys.argv[1:] or ["A", "B", "C"]
    labels = {"A": "free-local (no cloud keys)", "B": "alt-cloud (Cerebras-class only)", "C": "flagship (Fable + GPT + Gemini)"}
    port = 17901
    total_cost = 0.0
    for kind in wanted:
        print(f"\n=== Config {kind}: {labels[kind]} ===")
        if kind == "B" and not any(load_env_file(os.path.join(ROOT, '.env')).get(k) for k in ALT):
            print("  SKIPPED — no Cerebras/DeepSeek/GLM key in .env yet.")
            print("  Add e.g. CEREBRAS_API_KEY=... to .env and re-run: "
                  ".venv/bin/python scripts/test_provider_configs.py B")
            continue
        for row in run_config(kind, labels[kind], port):
            total_cost += row.get("cost", 0) or 0
            print(f"  [{row['case']:<11}] tier={row['tier']:<12} model={row['model']:<46} "
                  f"cost=${row.get('cost', 0):.4f} {row['ms']}ms")
            if row.get("answer"):
                print(f"               ↳ {row['answer']}")
        port += 1
    print(f"\nTotal cloud spend this run: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
