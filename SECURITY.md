# Security Policy

## Reporting Vulnerabilities

**Do not open a public GitHub issue for security vulnerabilities.**

Email: security@mullm.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected versions (check `GET /health` for current version)
- Potential impact

We aim to respond within 72 hours and provide a fix or mitigation plan within 14 days.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x | Supported at release; optional extras audited separately |
| Latest on `main` | Yes |
| < 1.0 | No |

muLLM 1.0.x and the latest `main` branch receive security fixes. Older pre-1.0 development
branches are not supported.

On 2026-11-05, a fresh core wheel installation without `constraints.txt` passed
pip-audit. This is a dated result, not a permanent zero-CVE guarantee. A separate
optional integration audit found four distinct unresolved advisories for
ChromaDB 1.5.9: PYSEC-2026-311, PYSEC-2026-3813, PYSEC-2026-3814, and
PYSEC-2026-3815 (the auditor reported five rows, including a duplicate).
ChromaDB stays opt-in; SQLite is the core default. The optional constraints file
cannot fix these unresolved advisories. Browser model assets and GPU/TTS extras
need their own audits and are not covered by the core result.

## Dependency Vulnerability Scanning

Dependencies and source are scanned using GitHub Actions:

- Bandit for high-severity Python security checks on `router/`
- pip-audit for pinned dependency constraints and resolved wheel-installed dependencies
- Semgrep OSS rules for Python, default security rules, and secrets
- Grype filesystem scan with a high-severity cutoff

### Run locally

```bash
python -m venv .security-venv
. .security-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -c constraints.txt -e ".[security]"
python -m bandit -c pyproject.toml -r router -lll
python -m pip_audit -r constraints.txt --strict --desc
bash scripts/security-wheel-audit.sh
```

The CI workflow (`.github/workflows/security.yml`) runs on every push to `main`, pull requests to
`main`, and weekly. Grype fails builds on high or critical findings.

## Disclosure Policy

- We follow responsible disclosure.
- Reporters are credited in release notes unless they prefer anonymity.
- We do not pursue legal action against researchers acting in good faith.
