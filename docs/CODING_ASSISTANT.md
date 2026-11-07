# muLLM coding assistant and harness

The coding harness is included in `pip install mullm`. Use the `mullm` command;
there is no separate `mullm-code` executable or `[code]` extra to install.
Version 1.0.1 fixes a missing optional HTTP-client dependency in clean core installs.

## Start the inference server

In one terminal, activate your muLLM environment and run:

```bash
mullm
```

`mullm-server` and `mullm --serve` start the same server. It opens setup on first
use, or Chat when already configured. The local default is
`http://127.0.0.1:6856`, with no certificate setup. Configure a local runner or
provider keys there. Keep this terminal running while using the harness from a
second terminal with the same environment activated.

To require local inference, start the server with `DISABLE_CLOUD=1` (PowerShell:
`$env:DISABLE_CLOUD = "1"`). Local-only mode needs a working local model. A
keys-only Mac should pass **`--tier cloud_cheap`** or **`--tier cloud_full`** to
`--orchestrate`; without an override, coding tasks normally prefer local models.
Cloud tasks consume API credits and obey the server's budget/privacy settings.

## Ask a coding question

```bash
mullm "Explain Python generators with a small example"
```

This routes a question; it does not edit repository files. An explicit cloud call
can use `--tier cloud_cheap` and `--model MODEL_ID`. The plain query command can
also run its pipeline inline when no server is available. The repository harness
below uses the running server.

## Plan work in a repository

Change to the project you want to work on. The harness indexes that directory and
uses its context files. Start with a plan, which makes no inference call:

```bash
mullm --orchestrate "Fix the greeting in greet.py" --dry-run
mullm --orchestrate BUGS.md --dry-run
```

Task files such as `BUGS.md`, `REQUESTS.md`, and `TODO.md` can contain multiple
tasks. Planning reports target files and estimated routing tiers.

## Generate, apply, and verify changes

Generate proposed patches without writing them:

```bash
mullm --orchestrate "Fix the greeting in greet.py" --code
```

Apply patches in a working branch or disposable checkout, with your own acceptance
command:

```bash
mullm --orchestrate BUGS.md --code --apply --self-update --verify "python -m pytest tests/"
```

On a keys-only Mac, for example:

```bash
mullm --orchestrate BUGS.md --tier cloud_cheap --code --apply --self-update --verify "python -m pytest tests/"
```

The current CLI requires **both `--apply` and `--self-update` for any repository
writes**. Despite its name, `--self-update` is the write opt-in for the selected
working directory, not a pip upgrade command. Review changes with `git diff`.

TDD mode is on by default. `--no-tdd` skips generated test/spec preparation;
your `--verify` command still runs. `--bugfix-tdd` requests a failing test before
repair. `--timeout 600` controls the harness task timeout; individual server queries
still have their own deadline. `--server-url URL` selects another configured server.

Each result reports status, applied patches, cost, and verification when run.
A nonzero CLI exit indicates failed/incomplete work or failed verification.
Generation success alone is not an acceptance result. The CLI does not guarantee
rollback of every failed edit; inspect the working tree before keeping changes.

## Factory projects

For a project with a fixed acceptance contract, isolated candidate worktrees,
artifacts, and visual task progress, use [Software Factory](SOFTWARE_FACTORY.md):

```bash
mullm --factory-init csv-json --factory-dir my-converter
cd my-converter
mullm --factory factory.toml
```

Open `/factory` to inspect published runs. Only runs that publish Factory events
appear there; `--orchestrate` output is currently terminal-based. Required human
decisions and optional timed choices are part of the Factory workflow.
