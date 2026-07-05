# muLLM — Pre-Launch Distribution Guide

How to get muLLM into testers' hands before going public, and how to ship it
when you're ready.

---

## Distribution Levels

Four stages from "just you" to "the world". Move through them in order.

| Level | Who Can Install | How | When |
|-------|----------------|-----|------|
| 0 | You only | `pip install -e .` from git | Now — daily dev |
| 1 | Private beta (up to ~50) | TestPyPI + GitHub releases | Ready when tests pass |
| 2 | Closed beta | GitHub releases (private or unlisted) | After Level 1 shakeout |
| 3 | Public launch | PyPI + public GitHub | After Level 2 shakeout |

---

## Level 0 — Local dev install (right now)

No PyPI needed. Works from the repo.

```bash
# From the mullm repo root:
source .venv/bin/activate
pip install -e .           # editable install, live-reloads router changes
mullm --serve              # starts on http://localhost:6856
```

To share with a single trusted person on the same machine:

```bash
pip install git+https://github.com/stolmar/mullm.git
mullm --serve
```

---

## Level 1 — TestPyPI (private beta, ~50 testers)

TestPyPI is PyPI's staging environment. Packages are world-readable but
no one finds them unless you share the URL.

### Publish to TestPyPI

```bash
# Install build tools (once)
pip install build twine

# Build source dist + wheel
python -m build
# Creates: dist/mullm-0.9.9.tar.gz  and  dist/mullm-0.9.9-py3-none-any.whl

# Upload to TestPyPI (create account at https://test.pypi.org first)
twine upload --repository testpypi dist/*
# Prompts for TestPyPI username/password (or use API token)
```

**Using an API token (recommended):**

```bash
# ~/.pypirc
[testpypi]
  username = __token__
  password = pypi-...your-testpypi-token...
```

Then `twine upload --repository testpypi dist/*` uses the token silently.

### Install from TestPyPI (share this with testers)

```bash
pip install \
  --extra-index-url https://test.pypi.org/simple/ \
  mullm==0.9.9
mullm --serve
```

The `--extra-index-url` flag falls back to real PyPI for dependencies
(like fastapi, httpx, etc.) that aren't on TestPyPI.

---

## Level 2 — GitHub Release wheel (closed beta)

No PyPI account required. Attach the `.whl` to a GitHub release and share
the direct URL. This works even from a private repo (logged-in users only).

### Create a GitHub release

```bash
# Tag the release
git tag v0.9.9
git push origin v0.9.9

# Create release via GitHub CLI (adjust repo path if needed)
gh release create v0.9.9 \
  --title "muLLM v0.9.9 — private beta" \
  --notes "Pre-release beta. Do not share this URL publicly." \
  dist/mullm-0.9.9-py3-none-any.whl \
  dist/mullm-0.9.9.tar.gz
```

### Install from GitHub release (share this URL with testers)

```bash
pip install \
  https://github.com/stolmar/mullm/releases/download/v0.9.9/mullm-0.9.9-py3-none-any.whl
mullm --serve
```

---

## Level 3 — PyPI public launch

When you're ready for Hacker News / Product Hunt / public GitHub:

### Publish to real PyPI

```bash
twine upload dist/*
# Uses ~/.pypirc [pypi] section, or prompts for credentials
```

### Install from PyPI (what users run)

```bash
pip install mullm
mullm --serve
```

That's it. If `pyproject.toml` and dependencies are correct, this just works.

---

## What to test on each platform

Run through this checklist on each target before moving to the next level.

### 1. Basic smoke test (all platforms)

```bash
# Fresh environment — no mullm installed
python3 -m venv /tmp/mullm-test && source /tmp/mullm-test/bin/activate
pip install mullm==0.9.9           # or TestPyPI variant
mullm --version                    # should print: muLLM v0.9.9
mullm --serve &                    # starts server
sleep 3
curl -s http://localhost:6856/health | python3 -m json.tool
# Should return: {"status": "ok", ...}
```

### 2. Full feature checklist

After `mullm --serve`, open `http://localhost:6856` and verify:

- [ ] Chat sends a message and receives a response
- [ ] Tier bar shows which model was used (Local / Cloud)
- [ ] Dashboard loads at `/dashboard` with real data (not SIM)
- [ ] `/setup` wizard completes all 5 steps
- [ ] Switching backends works (e.g. Ollama → llama.cpp)
- [ ] `mullm --status` returns healthy JSON
- [ ] `mullm --cost` shows session cost summary

### 3. Per-platform GPU path verification

| Platform | GPU path | Verify |
|----------|----------|--------|
| Mac M1/M2/M3/M4 (Apple Silicon) | MLX | `python3 -c "import mlx; print('MLX ok')"` |
| Mac Intel | llama-cpp Metal | `python3 -c "import llama_cpp; print('llama-cpp ok')"` |
| Windows 11 + NVIDIA | CUDA PyTorch | `python3 -c "import torch; print(torch.cuda.is_available())"` |
| Windows 11 CPU only | llama-cpp CPU | `python3 -c "import llama_cpp; print('llama-cpp ok')"` |
| Linux + NVIDIA | Ollama (CUDA) or ExLlamaV2 | `ollama run qwen3:9b "hello"` |
| Linux CPU only | Ollama CPU | `ollama run qwen3:9b "hello"` |

---

## Platform-specific install test commands

Copy-paste these on a clean machine for each distribution level.

### Mac (Apple Silicon — M1 through M4)

```bash
# Verify: arm64 machine, Python 3.11+
python3 --version        # 3.11.x or 3.12.x
uname -m                 # arm64

# Level 1 (TestPyPI)
pip install --extra-index-url https://test.pypi.org/simple/ mullm==0.9.9
pip install mlx-lm       # Apple Silicon ML backend
mullm --serve

# Level 2 (GitHub release)
pip install https://github.com/stolmar/mullm/releases/download/v0.9.9/mullm-0.9.9-py3-none-any.whl
pip install mlx-lm
mullm --serve

# Level 3 (PyPI)
pip install mullm
pip install mlx-lm
mullm --serve
```

### Mac Intel

```bash
# Verify: x86_64 machine
uname -m                 # x86_64

pip install mullm==0.9.9
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python
mullm --serve
```

### Windows 11 — NVIDIA GPU

```powershell
# In PowerShell or CMD (Python 3.11+ required)
pip install mullm==0.9.9
pip install torch==2.7.0 torchvision torchaudio `
    --index-url https://download.pytorch.org/whl/cu128
mullm --serve
```

### Windows 11 — CPU only

```powershell
pip install mullm==0.9.9
pip install llama-cpp-python
mullm --serve
```

### Linux x86_64 — NVIDIA GPU

```bash
pip install mullm==0.9.9
# Ollama handles GPU automatically if CUDA drivers are installed
ollama pull qwen3:9b
mullm --serve
```

### Linux x86_64 — CPU only

```bash
pip install mullm==0.9.9
ollama pull qwen3:9b     # Ollama runs CPU by default if no GPU
mullm --serve
```

---

## GitHub Actions — multi-platform CI builds

For Level 2+, use GitHub Actions to build platform packages automatically
when you push a tag. This replaces manual build on each machine.

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*.*.*"]

jobs:

  # ── Python package (all platforms) ────────────────────────────────────────
  build-wheel:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install build
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with: { name: dist, path: dist/ }

  # ── Mac .dmg ──────────────────────────────────────────────────────────────
  build-mac:
    runs-on: macos-latest
    needs: build-wheel
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - run: brew install create-dmg
      - run: pip install pyinstaller
      - run: bash packaging/mac/build_dmg.sh
      - uses: actions/upload-artifact@v4
        with:
          name: mac-dmg
          path: "*.dmg"

  # ── Windows .exe ──────────────────────────────────────────────────────────
  build-windows:
    runs-on: windows-latest
    needs: build-wheel
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - run: pip install pyinstaller
      - run: packaging\windows\build_exe.bat
      - uses: actions/upload-artifact@v4
        with:
          name: windows-exe
          path: dist\muLLM.exe

  # ── Linux AppImage ────────────────────────────────────────────────────────
  build-linux:
    runs-on: ubuntu-latest
    needs: build-wheel
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - name: Install appimagetool
        run: |
          wget -q -O /usr/local/bin/appimagetool \
            https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
          chmod +x /usr/local/bin/appimagetool
      - run: bash packaging/linux/build_appimage.sh
      - uses: actions/upload-artifact@v4
        with:
          name: linux-appimage
          path: "*.AppImage"

  # ── GitHub Release ────────────────────────────────────────────────────────
  release:
    runs-on: ubuntu-latest
    needs: [build-wheel, build-mac, build-windows, build-linux]
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v4
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/*.whl
            dist/*.tar.gz
            mac-dmg/*.dmg
            windows-exe/muLLM.exe
            linux-appimage/*.AppImage
          draft: true    # Review before publishing
          generate_release_notes: true

  # ── PyPI publish (Level 3 only — uncomment when ready) ───────────────────
  # publish-pypi:
  #   runs-on: ubuntu-latest
  #   needs: release
  #   environment: pypi    # Requires PyPI environment in GitHub repo settings
  #   permissions:
  #     id-token: write    # For OIDC trusted publishing
  #   steps:
  #     - uses: actions/download-artifact@v4
  #       with: { name: dist, path: dist/ }
  #     - uses: pypa/gh-action-pypi-publish@release/v1
```

---

## TestPyPI → PyPI promotion workflow

Don't upload to real PyPI directly from your laptop. The safe flow:

```
1. python -m build                       # build dist/
2. twine check dist/*                    # validate metadata
3. twine upload --repository testpypi dist/*  # upload to test
4. pip install --extra-index-url https://test.pypi.org/simple/ mullm==0.9.9
5. Test everything (checklist above)
6. twine upload dist/*                   # promote to real PyPI
```

Or use GitHub Actions' `pypa/gh-action-pypi-publish` with OIDC trusted
publishing — no PyPI API token to manage.

---

## Distribution format comparison

| Format | Pros | Cons | Use for |
|--------|------|------|---------|
| `pip install mullm` | Universal, auto-updates | Requires Python | Developers, power users |
| Mac .dmg (PyInstaller) | Zero-terminal install | Requires notarization | Non-technical Mac users |
| Windows .exe (PyInstaller) | Zero-terminal install | Requires code signing | Non-technical Windows users |
| Linux .AppImage | One file, portable | Large (~200MB) | Linux desktop users |
| Tauri .app/.exe/.AppImage | Native shell, small binary | Requires Rust toolchain | Future: polished desktop UX |
| Docker/Podman | Reproducible, server deploy | Requires container runtime | Servers, CI, enterprise |

Note: The PyInstaller builds (Mac/Windows) and AppImage are the fast path
to zero-terminal installation. The Tauri build documented in PACKAGING.md
is the long-term primary desktop target but requires a Rust toolchain and
more setup time.

---

## Private asset checklist before any distribution

Before tagging a release or uploading to any PyPI, run:

```bash
python3 scripts/strip_private_assets.py
```

And verify these files are NOT in the dist:

```
.env                              # API keys
cache/data/scoring_log.jsonl      # your query history
cache/data/semantic_cache.sqlite3 # default semantic cache
cache/data/chromadb/              # optional ChromaDB cache, when enabled
sessions.jsonl                    # session badge data
models/routing-classifier/        # trained weights (>1GB)
```

The `.gitignore` already excludes these, but double-check before a public
release with:

```bash
tar -tzf dist/mullm-0.9.9.tar.gz | grep -E '(\.env|scoring_log|semantic_cache|chromadb)'
# Should print nothing
```

---

## Version note

`pyproject.toml` currently sets `version = "1.0.0"`. For a pre-launch /
beta release, bump it down to `0.9.9` before building:

```bash
sed -i 's/version = "1.0.0"/version = "0.9.9"/' pyproject.toml
```

Or use `0.9.9` for the beta and `1.0.0` for the HN/public launch — your
call. Either way, keep `pyproject.toml`, `router/config.py`, and the
launcher scripts in sync.

---

*muLLM helped review this document. Cost: $0.00.*
