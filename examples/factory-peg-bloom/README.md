# Peg Bloom: a small software factory experiment

A peg-solitaire game with three board shapes and 13-, 24-, and 26-jump solutions. The larger boards finish as a five-peg constellation. Each jump removes one peg, so the starting and finishing peg counts independently determine the required number of moves.

The root files supply the **specification and test harness**. Factory writes `engine.mjs`, `render.mjs`, `app.mjs`, and `style.css` in an isolated worktree. `wooden/` is an optional supplied presentation component; `verified/` contains the captured, playable wooden edition, including the locally generated engine and controller. Its provenance file identifies those contributions.

## Run it

Start muLLM with a working local model. Use a context size and task size appropriate to that model; every `/query` call retains the server deadline.

Copy this directory into a new project directory. From that copy:

```bash
uv venv
uv pip install --python .venv/bin/python playwright
.venv/bin/python -m playwright install chromium
export PATH="$PWD/.venv/bin:$PATH"
git init
git add .
git commit -m "Define Peg Bloom specification and acceptance"
mullm --factory factory.toml --dry-run
mullm --factory factory.toml --server-url https://127.0.0.1:6856
```

Node.js must also be available for the rules tests. Keep `.venv/`, `dist/`, and `__pycache__/` ignored by Git. On Windows, activate the virtual environment instead of the POSIX `export` command.

Open `/factory` on the same muLLM server to observe the run, and `/unblock` when it requests a decision. A failed attempt does not accept the game. Inspect the failure before choosing Retry or Stop.

When the product-review card appears, use the **candidate worktree path shown in Factory** to start its preview in a separate terminal:

```bash
cd <candidate-worktree>
python3 -m http.server 8080 --bind 127.0.0.1
```

Open `http://127.0.0.1:8080`, try the workflow below, and answer the review card. Set the manifest's review URL before committing if using another port. The packaged game is `dist/peg-bloom.zip`; acceptance requires the human review as well as automated checks.

To play the captured wooden edition without generation, serve `verified/` with the same static-server command. The optional `wooden/` files replace the presentation files alongside an engine, controller and `puzzles.json` implementing the supplied contract.

## Play and verify

1. Choose First Light, Cross Blossom, or Diamond Bloom.
2. Select an occupied peg, then a highlighted empty landing hole.
3. Try Hint, Undo, and Restart. A hint follows the recorded solution only when the board matches one of its prefix states.
4. Finish with exactly the glowing goal cells occupied. A matching peg count in the wrong shape is not a win.

First Light allows horizontal, vertical and down-right/up-left diagonal jumps on its triangular grid. The cross and diamond boards allow horizontal and vertical jumps.

`acceptance.mjs` compares every recorded state with an independently implemented legal-move oracle, rejects illegal moves, checks immutability and exact goal equality, and verifies all 63 jumps. `browser_acceptance.py` clicks through the actual game, checks controls and state after each move, tests mobile fit and visible peg distinction, and rejects browser errors and external network requests.

The deterministic puzzle fixtures were constructed backward from their goals. Their forward witnesses are independently verified by the acceptance harness. This proves those instances are solvable; it does not establish uniqueness or human difficulty.

[Inspect the captured development history and generated result](../../docs/evidence/peg-bloom/README.md).
