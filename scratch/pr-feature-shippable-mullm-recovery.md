# PR: Recover shippable muLLM package, Studio assets, and Sword Dojo

## Summary

This branch seeds the clean `wonton-mullm` repository from the advanced muLLM tree and makes the package installable from a wheel without relying on source-tree runtime state.

Commit: `868b48b Recover shippable muLLM package`

Key changes:

- Moves source vector-cache code from top-level `cache/` to `router/vector_cache.py`; leaves `cache/` as ignored runtime state only.
- Routes default runtime state/cache/log paths to `MULLM_STATE_DIR` or the OS user state directory instead of package directories.
- Packages HTML pages, ready games, local static assets, and `router/code/ready/*` so installed wheels serve `/setup`, `/chat`, `/games`, and packaged games.
- Vendors Three.js r185 locally under `router/static/three`, including current controls/loaders/exporters/environment helpers and r185 generator modules for terrain/city/forest/tree work.
- Updates `/swords` to use local Three assets, normalize generated/imported sword tips to local `+Y`, estimate imported GLB tip direction, and replace the old stab/slash flourishes with blade-axis-aware thrust and cut poses.
- Updates Meshy adapter payloads for Meshy 6/latest defaults, low-poly mode, target-polycount remesh options, PBR refine, and texture prompts.
- Refreshes ComfyUI route tests to include checkpoint discovery before queueing image/video workflows.
- Adds `/api/comfyui/models` plus setup-page rendering for checkpoints, LoRAs, VAEs, diffusion models, preferred SDXL checkpoint, and counts.
- Widens the setup page desktop content column from the old 600px cap to 1120px, and 1240px on very wide screens, while preserving mobile full-width behavior.
- Makes explicit `force_tier` escalation authoritative: forced local/cloud/cache requests bypass groundtruth/weather zero-tier resolvers so Escalate can produce a genuinely higher-tier answer after a groundtruth hit.
- Makes the CLI/service path package-safe: default SQLite storage and generated service state now use `MULLM_STATE_DIR` or the OS user state directory rather than `./cache` or site-packages.
- Aligns packaged Linux/macOS/Windows startup launchers with the installed `mullm-server` entry point while keeping legacy `mullm1-server` fallbacks where wrapper scripts can support them.
- Makes semantic cache secure-by-default: fresh installs use dependency-free SQLite cosine search under the muLLM state directory, ChromaDB is moved to the opt-in `mullm[vector-cache]` extra while its current advisory has no fixed version, and privacy/cache endpoints work against the configured backend.
- Adds Python 3.13 to package metadata and CI, tightens security workflow commands, and makes terrain/image runtime dependencies explicit so `pip install mullm` starts from a clean venv.

## Evidence

Automated checks run:

```text
python -m pytest tests/test_games_routes.py tests/test_packaging_release.py tests/test_backend.py tests/test_router.py tests/test_storage.py tests/test_module_catalog.py tests/test_cli_dispatch.py tests/test_page_registry.py tests/test_provider_selector.py tests/test_routes_page.py tests/test_meshy.py tests/test_comfyui_api.py tests/test_groundtruth_mode.py -q
101 passed, 3 skipped, 28 warnings

python -m pytest tests/test_games_routes.py tests/test_packaging_release.py tests/test_backend.py tests/test_router.py tests/test_storage.py tests/test_module_catalog.py tests/test_cli_dispatch.py tests/test_page_registry.py tests/test_provider_selector.py tests/test_routes_page.py tests/test_meshy.py tests/test_comfyui_api.py -q
94 passed, 5 skipped, 28 warnings

python -m pytest tests/test_routes_page.py -q
6 passed

python -m pytest tests/test_groundtruth_mode.py -q
4 passed

python -m pytest tests/test_router.py tests/test_routes_page.py -q
20 passed, 28 warnings

python -m pytest tests/test_meshy.py tests/test_comfyui_api.py tests/test_games_routes.py tests/test_packaging_release.py -q
41 passed

ruff check router/config.py router/main.py router/vector_cache.py router/tiers.py router/intent.py router/benchmarks/runner.py router/benchmarks/swebench.py router/realtime.py router/cli.py router/storage.py router/meshy.py router/comfyui_api.py tests/test_packaging_release.py tests/test_backend.py tests/test_router.py tests/test_games_routes.py tests/test_meshy.py tests/test_comfyui_api.py tests/test_cli_dispatch.py tests/test_storage.py tests/test_routes_page.py pyproject.toml
All checks passed

ruff check router/config.py router/main.py router/vector_cache.py router/tiers.py router/intent.py router/benchmarks/runner.py router/benchmarks/swebench.py router/realtime.py router/cli.py router/storage.py router/meshy.py router/comfyui_api.py tests/test_packaging_release.py tests/test_backend.py tests/test_router.py tests/test_games_routes.py tests/test_meshy.py tests/test_comfyui_api.py tests/test_cli_dispatch.py tests/test_storage.py tests/test_routes_page.py tests/test_groundtruth_mode.py pyproject.toml
All checks passed

ruff check router/tiers.py tests/test_groundtruth_mode.py
All checks passed

ruff check router/meshy.py tests/test_meshy.py tests/test_comfyui_api.py tests/test_games_routes.py pyproject.toml
All checks passed

python -m build --wheel
Successfully built mullm-1.0.0-py3-none-any.whl

bash scripts/release-smoke.sh
Fresh wheel install and installed-server smoke passed:
{"base_url":"http://127.0.0.1:8727","health":"ok","setup":"ok","chat":"ok","swords":"ok","groundtruth_category":"css_facts","model_used":"groundtruth-lut"}

systemd-analyze verify packaging/linux/mullm.service
passed

python -m pytest tests/test_packaging_release.py tests/test_module_catalog.py -q
8 passed

python3 -m pytest tests/test_cache_sqlite.py tests/test_cache_redis.py tests/test_packaging_release.py tests/test_module_catalog.py tests/test_groundtruth_mode.py -q
20 passed

ruff check router/cache.py router/config.py router/main.py router/cli.py tests/test_cache_sqlite.py tests/test_cache_redis.py tests/test_packaging_release.py pyproject.toml
All checks passed

python3 -m bandit -c pyproject.toml -r router -lll
No high-severity issues identified

python3 -m pip_audit -r constraints.txt --strict --desc
No known vulnerabilities found

bash scripts/release-smoke.sh
Fresh wheel install and installed-server smoke passed:
{"base_url":"http://127.0.0.1:62719","chat":"ok","groundtruth_category":"css_facts","health":"ok","model_used":"groundtruth-lut","setup":"ok","swords":"ok"}
Runtime state included:
semantic_cache.sqlite3

bash scripts/release-smoke.sh
Fresh wheel install and installed-server smoke passed with the hardened cache probe:
{"base_url":"http://127.0.0.1:29179","cache":"ok","chat":"ok","groundtruth_category":"css_facts","health":"ok","model_used":"groundtruth-lut","setup":"ok","swords":"ok"}
Runtime state included:
semantic_cache.sqlite3
```

Fresh installed-wheel CLI and HTTP smoke with `MULLM_ENABLE_STUDIO=true`:

```text
mullm --version
muLLM v1.0.0

MULLM_STATE_DIR=<tmp>/state python -c "from router.storage import get_storage; ..."
cache_dir <tmp>/state/cache/data
db_exists True
backend sqlite

/setup 200 147686
/chat 200 497154
/swords 200 92248
/api/comfyui/status 200 850
/api/comfyui/models 200
/static/three/three.core.js 200 1443059
/code/ready/bamboo-village.html 200 24235

Runtime files created under <tmp>/state/cache/data:
access_log.jsonl
certs/mullm.crt
certs/mullm.key
mullm.db
```

Fresh installed-wheel browser smoke for `/swords`:

```json
{"buttons":3,"canvasBox":{"x":0,"y":0,"width":1280,"height":800}}
```

The browser smoke verified:

- `/swords` loads from the installed wheel.
- Canvas renders full viewport.
- Procedural/static sword buttons are present.
- The page uses `/static/three/three.module.js`.
- The sword-tip heuristic is present in loaded HTML.

Live user-service smoke after retargeting `mullm.service` to the wheel build:

```text
systemctl --user is-active mullm.service comfyui-mullm.service
active
active

curl -sk https://127.0.0.1:6856/health
{"status":"ok","version":"1.0.0","port":6856,"mode":"dev",...}

curl -sk https://127.0.0.1:6856/api/comfyui/models
running: true
preferred_checkpoint: sd_xl_base_1.0.safetensors
checkpoints: 3
loras: Hyper-SDXL-4steps-lora, Touch-of-Grain-SDXL, Touch-of-Realism-SDXL, lightx2v_I2V...
vaes: 5
diffusion_models: 7
```

Live escalation/groundtruth launch-blocker regression:

```text
curl -sk https://127.0.0.1:6856/query \
  -H 'Content-Type: application/json' \
  -d '{"content":"What is the difference between margin and padding in CSS?","source":"web","force_tier":"local","skip_cache":true}'

tier: local
tier_used: local
model_used: qwen3-coder:30b
groundtruth_category: null
cached: false
```

Before this fix, the same forced-local request returned `tier: groundtruth` and
`groundtruth_category: css_facts`, causing the chat Escalate button to repeat
the same groundtruth answer.

Live `/setup` package check after the desktop-width quickfix:

```text
--setup-content-max:1120px
@media(min-width:1440px){:root{--setup-content-max:1240px}}
.card max-width:var(--setup-content-max)
.mode-tabs max-width:var(--setup-content-max)
```

## Notes

- `/swords` remains a Studio page. In regular mode it is intentionally gated by `page_registry`; installed-wheel smoke used `MULLM_ENABLE_STUDIO=true`.
- Local ComfyUI is running as user service `comfyui-mullm.service` at `http://127.0.0.1:8188`.
  - Install used for validation: `/opt/comfyui`.
  - Visible checkpoint examples: `sd_xl_base_1.0.safetensors`, `sd_xl_turbo_1.0_fp16.safetensors`.
  - Visible LoRA examples: `Touch-of-Realism-SDXL.safetensors`, `Touch-of-Grain-SDXL.safetensors`, `Hyper-SDXL-4steps-lora.safetensors`.
  - muLLM `/api/comfyui/status` and `/api/comfyui/models` returned `running: true` against this live process.
- The user-level `mullm.service` was backed up under `scratch/service-backups/` and retargeted to the installed wheel command:
  - `ExecStart=/home/peter/TODO/dev/wonton-mullm/.venv-wheel-run/bin/mullm-server`
  - `MULLM_STATE_DIR=/home/peter/TODO/dev/wonton-mullm/scratch/runtime-state`
  - HTTPS remains on `https://127.0.0.1:6856/setup` using the previous cert paths.
- Meshy changes are dry-run/mocked; no live Meshy call was made and no API key was required.
- Official Three.js r185 release was checked on June 30, 2026. The npm package includes example generator modules for city, forest, terrain, and tree generation; this PR vendors those modules as foundations but does not claim a complete world editor yet.
- ChromaDB remains available for users who explicitly install `mullm[vector-cache]` and set `MULLM_SEMANTIC_CACHE_BACKEND=chroma`; the default backend is now SQLite because current `pip-audit` metadata reports `PYSEC-2026-311` against ChromaDB 1.x with no fixed version.
