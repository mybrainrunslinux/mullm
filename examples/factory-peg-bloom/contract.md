# Peg Bloom interface

All modules use browser-native ES modules. No dependencies or network services.
`puzzles.json` is an array of puzzle objects: `id`, `title`, `cells`, `start`, `goal`, `directions`, `solution`.
Cells are strings `"x,y"`. Directions are `[dx,dy]` unit vectors. A move is `[from,over,to]`: both from and over occupied, to empty, all on the board, consecutive equally spaced cells in an allowed direction. Each move removes exactly one peg. Solution is a list of these moves, independently verified before the build.

`engine.mjs` exports pure functions:
- `legalMoves(puzzle, pegs)` returns all legal move triples.
- `applyMove(puzzle, pegs, move)` returns a new occupied-cell array; throws on any illegal move; never mutates inputs.
- `isSolved(puzzle, pegs)` requires exact equality with the goal, not just matching counts.

`render.mjs` exports `renderBoard(puzzle, pegs, selected, targets)`.
It replaces children of `#board` with one button per board cell. Each button has `data-cell="x,y"`, `data-occupied="true"` or `"false"`, and an informative aria-label. Position cells by their x/y coordinates using CSS grid. Add classes `peg`, `goal`, `selected`, `target` as appropriate. Empty landing cells must remain clickable. Goals are visible even when empty. `targets` is an array of landing-cell IDs. Set grid dimensions from puzzle cells, with responsive square cells.

`app.mjs` imports those modules and fetches puzzles.json. Populate `#board-choice` with options whose value is puzzle.id. Selecting a puzzle resets its state. Delegate board clicks: clicking an occupied cell selects it; clicking a legal destination applies the selected jump. Keep previous peg arrays for undo. Buttons #restart and #undo work; #hint highlights/selects the next recorded solution move only if the current peg set matches a solution-prefix state. Otherwise show an honest restart suggestion. Update #counter as `Moves: N / M`, where M = start.length - goal.length. #status displays `Solved` only on exact goal equality. On completion, keep the final pegs visible with the goal styling. Use renderBoard after every state change.

`style.css` styles the provided semantic HTML, including responsive board, distinguishable pegs/empty holes/goal rings/selected/target states, keyboard focus, and the final glowing constellation. Avoid giant shadows that obscure cell boundaries.
