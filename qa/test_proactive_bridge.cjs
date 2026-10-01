const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../extension/content.js','utf8');
const fragment=source.slice(source.indexOf('  function parseSinglePacket('),source.indexOf('  // Isolated-world diagnostic hook'));
const c={provider:{id:'chatgpt',label:'ChatGPT'},normalizeText:x=>x};vm.createContext(c);vm.runInContext(fragment,c);
const raw={schema_version:1,operation:'create_proactive',draft_ref:'P01',tasks:[{id:'T01',content:'feito'}],evidence:[]};
const packets=c.extractBridgePackets('[GLPI_PROACTIVE]'+JSON.stringify([raw,{...raw,draft_ref:'P02'}])+'[/GLPI_PROACTIVE]');
assert.equal(packets.length,2);assert.equal(packets[0].operation,'create_proactive');assert.equal(packets[1].draft_ref,'P02');
console.log('PASS proactive Bridge parser');
