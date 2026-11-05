export function legalMoves(puzzle, pegs) {
  const pegSet = new Set(pegs);
  const cellsSet = new Set(puzzle.cells);
  const moves = [];
  for (const from of pegs) {
    const [fx, fy] = from.split(',').map(Number);
    for (const [dx, dy] of puzzle.directions) {
      const ox = fx + dx, oy = fy + dy;
      const over = `${ox},${oy}`;
      if (!cellsSet.has(over) || !pegSet.has(over)) continue;
      const tx = ox + dx, ty = oy + dy;
      const to = `${tx},${ty}`;
      if (!cellsSet.has(to) || pegSet.has(to)) continue;
      moves.push([from, over, to]);
    }
  }
  return moves;
}

export function applyMove(puzzle, pegs, move) {
  const legal = legalMoves(puzzle, pegs);
  if (!legal.some(m => m[0] === move[0] && m[1] === move[1] && m[2] === move[2])) {
    throw new Error('Invalid move');
  }
  const pegSet = new Set(pegs);
  const [from, over, to] = move;
  pegSet.delete(from);
  pegSet.delete(over);
  pegSet.add(to);
  return Array.from(pegSet);
}

export function isSolved(puzzle, pegs) {
  if (pegs.length !== puzzle.goal.length) return false;
  const pegSet = new Set(pegs);
  if (new Set(pegs).size !== pegs.length) return false;
  return puzzle.goal.every(g => pegSet.has(g));
}