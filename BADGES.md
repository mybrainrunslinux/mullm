# Badge Plan

Preview page:

- `badges/preview/index.html`

Recommended public README badges once GitHub Actions is live:

```markdown
[![CI](https://github.com/0101technology/mullm/actions/workflows/ci.yml/badge.svg)](https://github.com/0101technology/mullm/actions/workflows/ci.yml)
[![Security](https://github.com/0101technology/mullm/actions/workflows/security.yml/badge.svg)](https://github.com/0101technology/mullm/actions/workflows/security.yml)
[![Container](https://github.com/0101technology/mullm/actions/workflows/container.yml/badge.svg)](https://github.com/0101technology/mullm/actions/workflows/container.yml)
![PR-Gauntlet](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/0101technology/mullm/main/badges/benchmarks/pr-gauntlet.json)
![muPatch](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/0101technology/mullm/main/badges/benchmarks/mupatch.json)
```

The benchmark badges are intentionally JSON endpoints so PR-Gauntlet and
muPatch runs can update score, pass count, cost, and color without changing the
README by hand.
