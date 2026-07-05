# Groundtruth Review

The current groundtruth system is architecturally sound: categories are
registered as independent plugins, lookup is deterministic, and long technical
queries already have tests ensuring they fall through to model routing.

## Current Categories

Core:

- `arithmetic`
- `datetime`
- `http_status`
- `unit_conversion`
- `git_commands`
- `big_o`
- `big_o_ds`
- `ports`

Optional:

- `wcag`
- `live` / `weather` / `crypto`
- `gaming`
- `ue5`

## Risk Notes

Do not remove anything yet, but these deserve review:

- `force pull -> git fetch --all && git reset --hard origin/<branch>` is useful
  but destructive. Keep it only if the answer clearly warns before use.
- `discard changes -> git restore <file>` is also destructive. Same warning
  requirement.
- `datetime` timezone parsing only handles IANA-like names. Natural phrases like
  "Tokyo" are not safely resolved unless mapped explicitly.
- `unit_conversion` is intentionally narrow. That is good for false positives,
  but it means many safe coding/game units are missed.
- Port reverse lookup can match substrings in service descriptions. It is mostly
  safe because the query shape is narrow, but exact aliases would be cleaner.

## Suggested Additions

Coding:

- Python exception names: `KeyError`, `ImportError`, `ModuleNotFoundError`,
  `TypeError`, `ValueError`, `UnicodeDecodeError`.
- POSIX exit codes and signals beyond `137`, including `SIGKILL`, `SIGTERM`,
  `SIGSEGV`, `SIGBUS`, `SIGPIPE`.
- HTTP methods semantics: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`,
  `OPTIONS`.
- Common MIME types and file extensions for game/web assets: `.glb`, `.gltf`,
  `.ktx2`, `.basis`, `.wasm`, `.mjs`, `.ts`, `.tsx`.
- Git safety variants: "undo last commit keep changes", "revert public commit",
  "recover deleted file from git".

Game/WebGL:

- Three.js coordinate conventions: Y-up, radians, camera near/far, common Euler
  rotation order caveats.
- Three.js color/material quick facts: `MeshStandardMaterial`,
  `MeshBasicMaterial`, `sRGBColorSpace`, tone mapping.
- WebGL texture limits and power-of-two facts.
- Common physics formulas used in platformers/racing: distance under constant
  acceleration, jump velocity from desired height, stopping distance.
- Gamepad button/axis mapping basics for browser Gamepad API.

Assets/3D:

- GLTF/GLB unit convention: meters, right-handed/y-up conventions in common
  pipelines, embedded vs external buffers.
- Animation timing conversions: FPS to frame duration, 24/30/60/120 FPS.
- Polygon budget quick references for mobile/web/desktop tiers.
- Common texture channel packing: ORM/RMA, normal map orientation caveat.

Ops/Product:

- Default ports for Ollama, vLLM, LiteLLM, Joplin Web Clipper, ComfyUI, Redis,
  Postgres, MongoDB, Chroma, Qdrant.
- CORS/header quick facts for MCP/A2A/API proxy setup.
- License identifiers and SPDX one-liners for common OSS licenses.

