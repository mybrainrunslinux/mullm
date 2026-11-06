# Release and benchmark badges

README badges use live GitHub workflow results for CI, Security, and release
checks. The released-version
badge points to GitHub releases and does not imply that PyPI has a package.

- [CI](https://github.com/mybrainrunslinux/mullm/actions/workflows/ci.yml)
- [Security](https://github.com/mybrainrunslinux/mullm/actions/workflows/security.yml)
- [Release checks](https://github.com/mybrainrunslinux/mullm/actions/workflows/release-dry-run.yml)
- [Container](https://github.com/mybrainrunslinux/mullm/actions/workflows/container.yml)

Do not use static “zero CVEs” or “zero High” badges as current security evidence.
Benchmark badges describe the historical runs documented in README; they are
not a fresh benchmark of this candidate. The earlier proposed badge-preview and
JSON score endpoints are not shipped in this repository.
