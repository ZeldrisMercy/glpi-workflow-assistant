'use strict';
const assert=require('assert');
const {plan}=require('../extension/evidence-plan.js');

function f(key,id='auto'){return {key,id,role:id==='auto'?'evidence':undefined,data:`data-${key}`};}

let r=plan(['E01','E02','E03','E04','E05'],[f('a'),f('b'),f('c'),f('d')]);
assert.deepEqual(r.assigned.map(x=>x.id),['E01','E02','E03','E04']);
assert.deepEqual(r.remaining,['E05']);
assert.equal(r.pending,true);
assert.equal(r.ambiguous,false);

r=plan(['E01','E02'],[f('a'),f('b'),f('context')]);
assert.equal(r.assigned.length,0,'arquivos em excesso não devem ser adivinhados');
assert.equal(r.ambiguous,true);

r=plan(['E01','E02','E03'],[f('explicit','E03'),f('a'),f('b')]);
assert.deepEqual(r.assigned.map(x=>x.id),['E03','E01','E02']);
assert.equal(r.pending,false);

r=plan(['E01','E02'],[f('a','E01'),f('dup','E01'),f('b')]);
assert.equal(r.ambiguous,true,'E-ID duplicado deve permanecer sinalizado');
assert.deepEqual(r.assigned.map(x=>x.id),['E01']);
console.log('Bridge 2.3.0 evidence planner: parcial ordenado, excesso conservador e duplicidade cobertos.');

r=plan(['E01'],[{key:'glpi-screen',id:'',data:'context'}]);
assert.equal(r.assigned.length,0,'Contexto não pode virar E01');
r=plan(['E01'],[{key:'first-prompt',id:'auto',data:'unclassified'}]);
assert.equal(r.assigned.length,0,'Imagem não identificada não é prova mesmo com contagem exata');
r=plan(['E01'],[{key:'context',id:'',data:'context'},f('proof','E01')]);
assert.equal(r.assigned[0].file.key,'proof');
