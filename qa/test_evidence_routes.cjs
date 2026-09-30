const assert=require('assert'),{route}=require('../extension/evidence-plan.js');
const files=[{ref:'A01',key:'ctx',id:'',role:'context'},{ref:'A02',key:'x',id:'auto'},{ref:'A03',key:'y',id:'auto'}];
const packet=(ticket,ref)=>({ticket_id:ticket,closure:`[EVIDÊNCIA:E01]\nEVIDENCIA_ANEXO: E01 | ${ref}`});
let r=route([packet(123,'A02'),packet(456,'A03')],files);assert.deepEqual(r.assignments.map(x=>[x.ticket,x.key]),[[123,'x'],[456,'y']]);
r=route([packet(123,'A02'),packet(456,'A02')],files);assert.equal(r.assignments.length,0);
r=route([packet(123,'A01')],files);assert.equal(r.assignments.length,0);
r=route([packet(123,'A99')],files);assert.equal(r.assignments.length,0);
r=route([packet(456,'A02')],[{...files[1],ticket_id:123}]);assert.equal(r.assignments.length,0);
console.log('PASS: ordered origins across tickets, duplicate claims, context, absent origin, existing ticket binding');
