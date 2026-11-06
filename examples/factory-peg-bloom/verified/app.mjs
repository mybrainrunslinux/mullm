import { legalMoves, applyMove, isSolved } from './engine.mjs';
import { renderBoard } from './render.mjs';

let puzzles = [];
let currentPuzzle = null;
let pegs = [];
let history = [];
let selected = null;
let moveCount = 0;

async function init() {
  const res = await fetch('puzzles.json');
  puzzles = await res.json();
  const choice = document.getElementById('board-choice');
  puzzles.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.title;
    choice.appendChild(opt);
  });
  choice.addEventListener('change', () => loadPuzzle(choice.value));
  document.getElementById('board').addEventListener('click', handleClick);
  document.getElementById('undo').addEventListener('click', undo);
  document.getElementById('restart').addEventListener('click', restart);
  document.getElementById('hint').addEventListener('click', hint);
  loadPuzzle(puzzles[0].id);
}

function loadPuzzle(id) {
  currentPuzzle = puzzles.find(p => p.id === id);
  pegs = [...currentPuzzle.start];
  history = [];
  selected = null;
  moveCount = 0;
  updateUI();
}

function handleClick(e) {
  const btn = e.target.closest('button[data-cell]');
  if (!btn) return;
  const cell = btn.dataset.cell;
  const pegSet = new Set(pegs);

  if (selected !== null) {
    const moves = legalMoves(currentPuzzle, pegs);
    const target = moves.find(m => m[0] === selected && m[2] === cell);
    if (target) {
      history.push([...pegs]);
      pegs = applyMove(currentPuzzle, pegs, target);
      moveCount++;
      selected = null;
      updateUI();
      return;
    }
  }

  if (pegSet.has(cell)) {
    selected = (selected === cell) ? null : cell;
  } else {
    selected = null;
  }
  updateUI();
}

function undo() {
  if (history.length === 0) return;
  pegs = history.pop();
  moveCount--;
  selected = null;
  updateUI();
}

function restart() {
  pegs = [...currentPuzzle.start];
  history = [];
  selected = null;
  moveCount = 0;
  updateUI();
}

function updateUI() {
  const targets = selected ? legalMoves(currentPuzzle, pegs).filter(m => m[0] === selected).map(m => m[2]) : [];
  renderBoard(currentPuzzle, pegs, selected, targets);
  const total = currentPuzzle.start.length - currentPuzzle.goal.length;
  document.getElementById('counter').textContent = `Moves: ${moveCount} / ${total}`;
  const solved = isSolved(currentPuzzle, pegs);
  document.getElementById('status').textContent = solved ? 'Solved' : '';
}

function hint() {
  if (!currentPuzzle) return;
  const sol = currentPuzzle.solution;
  let replayPegs = [...currentPuzzle.start];

  for (let i = 0; i < sol.length; i++) {
    const currentPegSet = new Set(pegs);
    const replayPegSet = new Set(replayPegs);

    if (currentPegSet.size === replayPegSet.size &&
        [...currentPegSet].every(p => replayPegSet.has(p))) {
      selected = sol[i][0];
      updateUI();
      return;
    }

    try {
      replayPegs = applyMove(currentPuzzle, replayPegs, sol[i]);
    } catch (e) {
      break;
    }
  }

  document.getElementById('status').textContent = 'Hint: Restart to see the path.';
}

init();