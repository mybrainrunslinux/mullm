import assert from 'node:assert/strict';

import {buildPlan} from './workflow.mjs';

import {readFileSync} from 'node:fs';

const input=JSON.parse(readFileSync('product.json','utf8')).defaults;
 const original=JSON.stringify(input);
 const out=buildPlan(input,[]);
 assert.equal(JSON.stringify(input),original);
 assert.equal(out.metrics.length,3);
assert(out.summary.length>10);
assert(out.sections.length>0);
assert(Array.isArray(out.warnings));

const x={name:'Test',audience:'Developers',objective:'Interviews',budget:100,days:10,channels:'Email, Search, Community'};
const p=buildPlan(x,[]);
assert.equal(p.allocation.length,3);
assert.equal(Math.round(p.allocation.reduce((s,a)=>s+a.amount,0)*100),10000);
assert(p.allocation.every(a=>a.amount>=0));
assert(p.milestones.every(m=>m.day>=1&&m.day<=10));
assert(p.summary.includes('Developers'));
assert(buildPlan({...x,budget:0},[]).warnings.length);
assert.equal(buildPlan({...x,channels:''},[]).allocation.length,0);
assert.equal(buildPlan({...x,channels:'Email, Email, Search'},[]).allocation.length,2,'Duplicate channel names must be deduplicated BEFORE budget allocation: Email, Email, Search means TWO channels');

console.log('PASS: domain calculations, input handling, evidence boundaries and immutable input');
