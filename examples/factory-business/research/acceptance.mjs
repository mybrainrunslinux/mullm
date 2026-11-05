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

const x={name:'Test',audience:'Developers',hypothesis:'Maybe X',method:'Interviews',participants:8,days:14,decision:'Choose next test'};
const p=buildPlan(x,[]);
assert(p.questions.length>=4);
assert(p.questions.every(q=>!q.includes(x.audience)&&!q.includes(x.method)),'Questions should address real work, not mechanically insert an audience label or method name');
assert(p.questions.every(q=>typeof q==='string'&&q.endsWith('?')));
assert.equal(p.schedule.length,4,'The plan should contain four clear phases, not one repetitive item per day');
assert(p.schedule.every(s=>s.day>=1&&s.day<=14));
assert.equal(p.evidence_count,0);
assert.equal(buildPlan(x,[{claim:'Observed'}]).evidence_count,1);
assert(buildPlan({...x,participants:0},[]).warnings.length);
assert.deepEqual(buildPlan({...x,days:0},[]).schedule,[]);

console.log('PASS: domain calculations, input handling, evidence boundaries and immutable input');
