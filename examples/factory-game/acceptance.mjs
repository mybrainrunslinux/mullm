import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code = readFileSync('game.js', 'utf8');
// The pure gameplay API must be importable without a browser (guard DOM startup).
const game = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
assert.equal(game.collect(0), 1);
assert.equal(game.collect(99), 100);
assert.equal(game.restart(), 0);
const html = readFileSync('index.html', 'utf8');
assert.match(html, /canvas/i);
assert.match(html, /game\.js/);
assert.doesNotMatch(html + code, /https?:\/\//);
