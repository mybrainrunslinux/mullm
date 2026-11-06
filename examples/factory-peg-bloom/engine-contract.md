Export exactly these three functions from engine.mjs:
`legalMoves(puzzle, pegs)`, `applyMove(puzzle, pegs, move)`, `isSolved(puzzle, pegs)`.

`puzzle` is an OBJECT, NOT an array. Example:
{"cells":["0,0","1,0","2,0"],"directions":[[1,0],[-1,0]],"start":["0,0","1,0"],"goal":["2,0"]}
`pegs` is an ARRAY OF STRINGS: ["0,0","1,0"].
`move` is THREE STRINGS: ["0,0","1,0","2,0"].

For that example:
legalMoves(puzzle, puzzle.start) returns [["0,0","1,0","2,0"]].
applyMove(puzzle, puzzle.start, ["0,0","1,0","2,0"]) returns ["2,0"].
isSolved(puzzle, ["2,0"]) returns true; isSolved(puzzle, ["0,0"]) and isSolved(puzzle, ["2,0","2,0"]) return false.
All three move cells must be on puzzle.cells, from and over occupied, to empty, consecutive in one of puzzle.directions. Reject invalid moves. Do not mutate any argument. Parse coordinate strings into numbers for arithmetic; return strings.
