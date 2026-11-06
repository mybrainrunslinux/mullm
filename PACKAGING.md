# Packaging muLLM 1.0

The supported release path for **1.0.0** is a Python wheel; platform bundles require their own
platform checks before distribution. See [release readiness](docs/RELEASE_1_0.md).

## Build and verify a wheel

```bash
uv venv .release-venv
source .release-venv/bin/activate
uv pip install build twine
python -m build
python -m twine check dist/*
```

Install the candidate into a separate environment with `python -m pip install
/path/to/mullm-1.0.0-py3-none-any.whl`, then run `python -m pip check` and
`mullm --version`. No constraints file is required for a fresh core install.

The automated checks are:

```bash
bash scripts/release-smoke.sh
bash scripts/security-wheel-audit.sh
```

They build from this checkout and install without repository constraints. The
server smoke test uses temporary state, disables cloud inference, and checks
installed pages, APIs, and static assets. GitHub's release dry-run workflow
checks Python 3.11–3.15 on Linux, macOS, and Windows. Local results do not replace
a green matrix on the candidate commit.

## Included and excluded data

The wheel includes the `router` Python package, its HTML pages, static UI assets,
and declared groundtruth/game assets. Build metadata is defined in
`pyproject.toml`. It does not bundle the source repository's `config` package,
research paper, tests, `.env`, credentials, model weights, or runtime state.

Runtime data lives under the configured state directory, including
`semantic_cache.sqlite3` and `factory.sqlite3`. Factory reports and gate logs
also live in the project's Git directory. Keep these out of release artifacts.
The optional Kev.js runtime and model bundle are operator-provided directories,
not core-wheel dependencies.

ChromaDB is an optional extra with unresolved advisories as of 2026-11-05.
Do not publish a clean-core audit as an all-extras security claim.

## Containers and platform bundles

Use the maintained root `Dockerfile` with Podman:

```bash
podman build -t localhost/mullm:rc .
bash scripts/podman-smoke.sh
```

For persistent state, credentials, and networking, use
[Deployment](docs/DEPLOYMENT.md). The container contains the router; configure
local inference separately.

Existing platform build entry points are `packaging/linux/build_appimage.sh`,
`packaging/mac/build_dmg.sh`, and `packaging/windows/build_exe.bat`. They read the
project version. Build and test each on its target platform before calling its
installer supported. Earlier Tauri and USB packaging plans are not evidence of
working release artifacts.

## Publication

Establish PyPI ownership and trusted publishing, exercise TestPyPI, review the
built artifact, and obtain green security and release checks before tagging
1.0.0. Publish that exact reviewed artifact with provenance. This recovery pass
has not uploaded a package, created a release, or deployed the website.
