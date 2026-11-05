# Software Factory mode

`mullm --factory factory.toml` runs a bounded software production job from a
committed specification. `--dry-run` validates and prints the contract without
starting inference or changing files. It supports games, web, desktop, mobile,
and service projects through their own executable build and acceptance commands.

The initial mode uses local inference and does not publish, merge, deploy, or
make cloud calls. It creates a named Git branch and separate worktree, generates
only allowlisted files, runs the operator's acceptance commands, and records
artifact SHA-256 hashes. A failed command, missing artifact, invalid model output,
or changed protected acceptance file makes the run fail. Failed worktrees and
logs remain available for diagnosis. No generated answer is accepted as evidence
that software works: actual commands decide acceptance.

## Start a game project

Copy `examples/factory-game/` into a new directory, initialize Git, and commit
its specification and acceptance files. Start muLLM with a working local model,
then run:

```bash
mullm --factory factory.toml --dry-run
mullm --factory factory.toml --server-url http://127.0.0.1:6856
```

For authenticated servers, set `MULLM_API_KEY`. The source project must be clean.
The result names the candidate worktree and branch. Evidence is stored in the
source repository's Git directory under `factory/<run-id>/report.json` and
`gate-*.log`. The game example checks a pure scoring/reset contract and packages
a ZIP. Add browser input, collision, restart, accessibility, performance, and
visual regression gates before treating it as a complete game quality bar.

## Configure the production contract

The TOML fields are `name`, `target`, `goals`, `business_rules`, `preferences`,
`tasks`, `writable_files`, `protected_files`, `artifacts`, and `gates`.
Each gate specifies a name, command as an argument array, and timeout.
Commands run without a shell; provider credentials are removed from their
environment. Put acceptance suites and build scripts in `protected_files`.
Model output cannot change them. Keep independent acceptance cases out of the
prompt; only the allowed source files and stated requirements are sent.

Use native gate commands for each product: browser automation for web and games,
emulator/device tests for mobile, packaging and installer checks for desktop,
and contract/migration/load tests for services. Commands execute on the operator's
machine; a Git worktree provides change isolation, not a hostile-code sandbox.
Use Podman-backed gate commands for untrusted projects. The current implementation
does not claim enterprise tenancy or an unattended deployment boundary.

## 1.0 and 1.1 autonomy criteria

For 1.0, a bounded factory run is implemented: specification, isolated candidate,
local generation, protected acceptance gates, artifact checks and durable evidence.
Its tested success state is **accepted candidate**, not production deployment.

A Level 5 target for 1.1 should be demonstrated on a defined workload with no
human intervention between approved goals and verified delivery. The required
engineering is concrete: disposable build sandboxes, budget reservations,
persistent resume/recovery, limited repair loops, dependency provenance and
SBOMs, signed artifacts, independent security/quality gates, staged deployment,
health-based rollback, tenant isolation, and policy-controlled promotion.
Business rules must specify allowed dependencies and licenses, data boundaries,
spend and runtime limits, platforms, quality thresholds, and rollback conditions.
Do not infer Level 5 capability from a successful code-generation demo.
