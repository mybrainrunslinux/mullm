# Install and E2E Test

Recommended local path for release testing:

```bash
bash scripts/e2e-install-setup-run.sh
```

This creates `.venv-mullm1-e2e`, builds the wheel, installs it with
`constraints.txt`, starts `mullm-server` on `127.0.0.1:16857`, probes health,
setup, page registry, provider catalog, classifier, and the `mullm1` CLI, then
shuts down the server process it started.

The refactor also installs `mullm1` and `mullm1-server` entry points so an
existing old `mullm` CLI can remain usable while this tree is tested.

Developer venv:

```bash
bash scripts/install-venv.sh --dev --editable
source .venv-mullm1/bin/activate
bash scripts/quick-gate.sh
```

Container smoke:

```bash
bash scripts/podman-smoke.sh
```

The Podman script uses the exact container name `mullm1-smoke` by default and
only removes that container name during cleanup.
