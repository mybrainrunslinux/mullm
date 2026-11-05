# Fieldwork: three business projects in parallel

This example supplies independent contracts for a campaign planner, competitor research workspace, and marketing research planner. Each project contains a shared, reusable presentation kit plus protected domain and browser acceptance tests. The model writes `workflow.mjs`.

The apps save drafts in browser-local storage, record source provenance and review status, keep a decision log, and export the workspace as JSON. They do not fetch market data or invent findings.

## Build the projects

Copy `campaign/`, `competitors/`, `research/`, and `workspace.toml` into a new workspace. Initialize and commit a separate Git repository inside each project. Install Playwright and Chromium in a tooling environment on `PATH`; Node.js is required for the domain checks.

```bash
mullm --factory-batch workspace.toml --dry-run
mullm --factory-batch workspace.toml --server-url https://127.0.0.1:6856
```

Each worker receives its own branch and worktree. The shared inference queue prevents the three model calls from occupying each other's request timeout budget. Checks and packaging run independently. Open `/factory` on the same server to see all projects and their pending human requests.

The example review links point to a local preview hub on port 8080. Set each `product-review` gate's `review_url` to the URL where its candidate is served before committing the manifest. Review the **candidate worktree**, not an older source copy. Accept only after the workflow is useful and clear; Reject preserves the evidence.

The `shared/` directory contains the presentation and browser-test sources used to create the three projects. Changes to shared files must be copied into the project directories before committing their specifications.

[Inspect the captured runs](../../docs/evidence/marketing/README.md) or serve `verified/` to explore the captured apps without inference.
