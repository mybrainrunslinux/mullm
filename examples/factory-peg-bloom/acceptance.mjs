import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {legalMoves,applyMove,isSolved} from './engine.mjs';
const puzzles=JSON.parse(readFileSync('puzzles.json','utf8'));
const key=m=>JSON.stringify(m), eq=(a,b)=>key([...a].sort())===key([...b].sort());
function oracle(p,pegs) {
 const occupied=new Set(pegs), board=new Set(p.cells), moves=[];
 for(const from of p.cells) for(const [dx,dy] of p.directions) {
  const [x,y]=from.split(',').map(Number), over=`${x+dx},${y+dy}`, to=`${x+2*dx},${y+2*dy}`;
  if(board.has(over)&&board.has(to)&&occupied.has(from)&&occupied.has(over)&&!occupied.has(to)) moves.push([from,over,to]);
 }
 return moves;
}
let jumps=0, states=0;
for(const p of puzzles) {
 assert.equal(new Set(p.cells).size,p.cells.length);
 assert.equal(p.start.length-p.goal.length,p.solution.length);
 let pegs=[...p.start];
 for(const move of p.solution) {
  const before=key(pegs), puzzleBefore=key(p);
  const expected=oracle(p,pegs);
  assert.deepEqual(legalMoves(p,pegs).map(key).sort(),expected.map(key).sort(),`${p.id}: all legal moves must match the independent oracle`);
  assert(expected.some(m=>key(m)===key(move)),`${p.id}: invalid fixture witness`);
  assert.equal(isSolved(p,pegs),eq(pegs,p.goal));
  assert.throws(()=>applyMove(p,pegs,['-9,-9','-8,-9','-7,-9']));
  assert.throws(()=>applyMove(p,pegs,[move[0],move[0],move[2]]));
  const next=applyMove(p,pegs,move);
  assert.notEqual(next,pegs);
  assert.equal(key(pegs),before,'must not mutate peg input');
  assert.equal(key(p),puzzleBefore,'must not mutate puzzle');
  assert(eq(next,pegs.filter(c=>c!==move[0]&&c!==move[1]).concat(move[2])));
  assert.equal(next.length,pegs.length-1);
  pegs=next; jumps++; states++;
 }
 assert(isSolved(p,pegs)); assert(isSolved(p,[...pegs].reverse()));
 const wrong=[...p.goal]; wrong[0]=p.cells.find(c=>!p.goal.includes(c));
 assert(!isSolved(p,wrong),'same count with wrong shape is not solved');
 assert(!isSolved(p,[...p.goal,p.goal[0]]),'duplicate pegs are invalid');
 console.log(`${p.id}: ${p.cells.length} cells; ${p.solution.length} legal jumps; exact finishing shape verified`);
}
assert(puzzles.some(p=>p.solution.length>=24));
assert.equal(new Set(puzzles.map(p=>p.cells.length)).size,puzzles.length);
console.log(`PASS: ${jumps} jumps, ${states} states, three board shapes, immutable transitions and illegal-move rejection`);
