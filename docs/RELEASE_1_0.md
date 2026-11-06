# 1.0 release record

PR #15 is merged. This follow-up combines the reviewed Factory interface with
current model transports, optional browser classification, durable optional
choices, notification adapters, and a packaged autonomous utility starter.

The three marketing prototypes have been manually exercised at a basic level by
the maintainer. That establishes working prototype flows, not production app
qualification. Their original captured reports are retained as historical evidence.

## Publication

Configure the `mullm` PyPI pending publisher for owner `mybrainrunslinux`, repository
`mullm`, workflow `publish.yml`, environment `pypi`. TestPyPI uses a separate
publisher and environment `testpypi`. Both GitHub environments exist. Trusted
publishing requires no long-lived upload token in the repository.

The manual Publish workflow accepts a reviewed version tag on main, checks its
metadata, builds distributions, audits the installed core, and installs the same
wheel on Linux, macOS, and Windows before upload. Start with TestPyPI, then PyPI.
The package does not require a separate constraints download.

Follow [the upgrade checklist](UPGRADING.md) after publication, including restored
configuration, restart, version/port checks, a remote API call, and Windows local
inference. The Mac test is keys-only; MLX is not required.

## Evidence policy

Keep contracts, tests, compact provenance summaries, artifact hashes, and selected
documentation screenshots in Git. Large run logs, response transcripts, ZIPs,
and tours can live in release/CI artifacts with durable links and retention.
The existing case-study evidence is preserved; raw evidence is excluded from
package distributions. No new raw model transcripts are committed in this release.

## Scope

The CSV-to-JSON starter demonstrates one bounded autonomous delivery from approved
contract through verified package. Failed checks remain failures. Broader quality
claims require more workloads. Required human gates remain available for products
whose acceptance criteria need human judgment.

Core dependency audits are separate from optional extras. ChromaDB advisories
remain unresolved and the extra stays opt-in. Browser Kev model weights and real
notification destinations require their own qualification. Worker state is visible
after interruption; automatic resumption of a crashed worker is not implemented.

## Verification on the integration branch

- Python 3.15.2: 528 passed, 53 skipped, 4 expected failures, 40 passing subtests.
- Fresh core wheel: dependency check, CLI, installed server/UI/API smoke passed
  without constraints. Core pip-audit reported no known vulnerabilities.
- Rootless Podman build and authenticated HTTPS/query smoke passed.
- Chromium Factory/Unblock checks passed for literal untrusted text, decisions,
  clarification, deep links, and candidate previews.
- Live GPT-6 Astra and Claude Fable 5.1 calls both returned READY under the
  requested model IDs; combined reported cost $0.00078.
- CSV utility: one accepted local run in 7.147 seconds; artifact SHA-256
  `40656976cb4df15775a992d2456fa0fd1f73ad33991c3d5cec77d9df3b008f40`.
  Earlier failed contracts remain rejected; this is one scoped demonstration.

Hosted checks must pass on the final commit before tagging/upload. This record
is local validation, not a claim that PyPI publication or personal Windows/Mac
acceptance has already happened.

## Older automation PRs

- #7 (setup-python v7): incorporated across workflows here.
- #9 (pin CodeQL 4.37.4): the existing v4 major reference already tracks its
  updates; pinning an older patch is not required for this release.
- #11 (15 runtime upgrades): its OpenTelemetry 1.44 pins are superseded by the
  current coherent 1.45.1 constraints. Broad major-version widening for cloud
  SDKs, Transformers, Redis, and Torch needs separate compatibility work; it is
  not required for the clean core install or Python 3.15 verification above.
