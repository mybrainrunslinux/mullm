# muLLM — Project Guide

> Full architecture, benchmarks, API reference, and agent rules: **[AGENTS.md](AGENTS.md)**

## ⚠️ BEFORE YOU DO ANYTHING: USE MULLM FIRST

**Every debug question, every script, every traceback, every "how do I" → POST to mullm FIRST:**
```bash
curl -sk -X POST http://127.0.0.1:6856/query \
  -H "Content-Type: application/json" \
  -d '{"content": "YOUR QUESTION HERE"}'
```
Local 30B model. $0. 1-30 seconds. If you skip this and use Opus instead, you are burning the user's real money for nothing.

**String replacements → `sed -i 's/old/new/g' file`. Never the Edit tool. Never.**

## Rules
- **Tests must NEVER spend money by default** — cloud tests behind `--grep @spend`
- **Use podman over docker** for containers
- **Cost accuracy matters** — user has real API keys, real money
- **Local-first** — always default to cheapest option
- **No unnecessary server dependencies** — prefer client-side (IndexedDB) over server DB

## Running

```bash
# Development (activate project venv first):
source .venv/bin/activate
python -m router.main            # starts on :6856 (mullm0.9-server → :16856)

# Install (with security constraints):
pip install -c constraints.txt -e .

# Preferred (uv — faster, better resolver):
uv pip install -c constraints.txt -e .
```

## Testing
```bash
npx playwright test              # free tests
npx playwright test --grep @spend # paid cloud tests (explicit opt-in)
```
