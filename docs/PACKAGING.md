# muLLM Packaging Notes

## PyPI Name

Claim `mullm` on PyPI before public promotion, even if the first public install path is a
GitHub release wheel. Owning the name prevents confusion and gives users the normal command later:

```bash
python -m pip install mullm
```

Use TestPyPI first, then publish either a real prerelease or a minimal placeholder that points to
the signed GitHub release until the wheel is ready.

## Constraints

Pip supports remote constraints files:

```bash
python -m pip install mullm -c https://raw.githubusercontent.com/mybrainrunslinux/mullm/main/constraints.txt
```

Prefer immutable versioned URLs for reproducible installs:

```bash
python -m pip install mullm -c https://raw.githubusercontent.com/mybrainrunslinux/mullm/main/constraints.txt
```

Use a commit-specific raw GitHub URL when an immutable constraint set is required.

## Local Release Smoke

Before publishing a wheel or handing a build to a new user, run the fresh-install smoke:

```bash
bash scripts/release-smoke.sh
```

The script builds a wheel, creates a clean install venv, installs the wheel with `constraints.txt`
when present, starts the installed `mullm-server` on a temporary port with a temporary
`MULLM_STATE_DIR`, and probes the customer-facing surfaces:

- `mullm --version` and `mullm --help`
- `/health`
- `/setup`
- `/chat`
- `/swords` with Studio enabled
- bundled Three.js at `/static/three/three.module.js`
- a packaged ready game under `/code/ready/`
- deterministic groundtruth routing through `/query`

Useful options:

```bash
MULLM_RELEASE_SMOKE_PORT=18656 bash scripts/release-smoke.sh
MULLM_RELEASE_SMOKE_KEEP=1 bash scripts/release-smoke.sh
MULLM_RELEASE_SMOKE_DIR=/tmp/mullm-smoke bash scripts/release-smoke.sh
```

This smoke intentionally uses a temporary port and does not exercise local-model generation, Meshy,
or ComfyUI queueing. Those remain integration checks because they can consume VRAM, paid credits, or
large model downloads.

## Module Split

Default `mullm` should remain the router trust boundary: classifier, cache, groundtruth, privacy
logs, setup, chat, dashboard, and API compatibility.

Optional modules should be explicit:

- `mullm[code]` / `mullm-code`: orchestration and repo-writing workflows.
- `mullm[studio]` / `mullm-studio`: ComfyUI, image, video, 3D, audio, Dojo, games, and media assets.
- `mullm[bench]` / `mullm-bench`: PR-Gauntlet, muPatch, HumanEval, MultiPL-E, and heavy datasets.
- `mullm-enterprise`: policy packs, OIDC/SAML, immutable audit exports, quotas, and managed deploys.

Setup should never silently download Studio. It should show expected size, dependencies, URLs,
and a progress job after the user enables the module.
