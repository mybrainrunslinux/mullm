# muLLM Testing Gates

## Commit Gate

Install the local hook:

```bash
bash scripts/install-hooks.sh
```

Every commit runs:

- `scripts/quick-gate.sh`
- Ruff critical lint checks
- Python compile checks
- focused unit tests for storage, chat safety, compliance, cache, classifier, routing, orchestration, provider policy, resource policy, and sandbox policy
- high-severity Bandit scan on the critical router modules
- browser critical path smoke via Python Playwright against a temporary local muLLM server

The browser smoke intentionally checks the chat UI, bundled static libraries, sample-card behavior, no surprise web search, no fake spend ticker, and a basic send flow.

## Full Gate

Run the longer free test suite:

```bash
bash scripts/full-gate.sh
```

This includes the commit gate, broad pytest coverage, and full-stack integration tests with cloud disabled.

## Release Smoke

Before publishing or sharing a wheel, verify the customer install path:

```bash
bash scripts/release-smoke.sh
```

This gate builds a wheel, installs it into a fresh venv, starts the installed server on a temporary
port with a temporary `MULLM_STATE_DIR`, and probes `/health`, `/setup`, `/chat`, `/swords`, bundled
Three.js, a packaged ready game, and a deterministic groundtruth `/query`. It avoids paid providers,
ComfyUI queueing, Meshy, and local-model generation so it can run without spending credits or loading
a second large model.

## Spend-Gated Tests

Paid provider tests never run by default. To run them, both the flag and the explicit environment approval are required:

```bash
MULLM_ALLOW_SPEND=1 MULLM_TEST_SPEND_CAP_USD=1.00 bash scripts/full-gate.sh --spend
```

Provider tests must continue to estimate cost before starting work and bail out before crossing the configured cap. Tests that can make real provider calls must use the `spend` pytest marker.

## Multi-Instance Resource Policy

Use separate config or environment per service/container:

```bash
MULLM_VRAM_LIMIT_GB=24 mullm-server
MULLM_PORT=26864 MULLM_VRAM_LIMIT_GB=8 mullm-server
```

The live status endpoint is:

```text
GET /api/resource-policy
```

It currently reports VRAM/cache policy. Enforcement should be wired into backend selection and model-loading paths as those adapters mature.
