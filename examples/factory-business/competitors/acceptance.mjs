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

const x={name:'Test',audience:'Teams',competitors:`Northstar
Wayfinder
Northstar`,focus:'Pricing'};
const s=[{owner:'Northstar',claim:'Observed claim',url:'https://example.com/a',reviewed:true},{owner:'northstar',claim:'Unreviewed claim',url:'https://example.com/b',reviewed:false},{owner:'Other',claim:'Not theirs',url:'https://example.com/c',reviewed:true}];
const p=buildPlan(x,s);
assert.equal(p.comparisons.length,2,'Duplicate company names must be collapsed BEFORE building comparisons: Northstar, Wayfinder, Northstar means TWO companies');
assert.equal(p.comparisons[0].evidence_count,2);
assert.equal(p.comparisons[0].reviewed_count,1);
assert.deepEqual(p.comparisons[0].claims,['Observed claim','Unreviewed claim']);
assert.deepEqual(p.comparisons[1].claims,[]);
assert(p.warnings.length);
assert.deepEqual(buildPlan(x,[]).comparisons.map(c=>c.claims),[[],[]]);

console.log('PASS: domain calculations, input handling, evidence boundaries and immutable input');
