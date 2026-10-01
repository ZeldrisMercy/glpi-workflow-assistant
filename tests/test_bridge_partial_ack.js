const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const path=require('node:path');
const event={addListener:()=>{}};
const imageData='iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB';
const store={
  bridgeToken:'test-only',
  settings:{openIfClosed:false,autoSend:true,focusOnSend:false,evidenceRetentionHours:12},
  captureState22:{page:'https://chatgpt.com/c/1',updated_at:Date.now(),files:[{key:'a',name:'shot.png',size:24,type:'image/png',data:imageData,id:'E01',ticket_id:901743,created_at:Date.now()}]},
};
const local={
  get:async(keys)=>{if(keys==null)return {...store};if(typeof keys==='string')return {[keys]:store[keys]};if(Array.isArray(keys))return Object.fromEntries(keys.map(k=>[k,store[k]]));const out={};for(const [k,v] of Object.entries(keys||{}))out[k]=store[k]===undefined?v:store[k];return out;},
  set:async(values)=>Object.assign(store,values||{}),
  remove:async(keys)=>{for(const k of (Array.isArray(keys)?keys:[keys]))delete store[k];},
};
let call=0;
const context={Headers,AbortController,setTimeout,clearTimeout,URL,console,Response,
  fetch:async(url,options)=>{call++;const body=JSON.parse(options.body);const ready=call>1;return new Response(JSON.stringify({ok:true,evidence_ready:ready,missing_evidence_ids:ready?[]:['E02'],handoff:{id:7,task_count:2,evidence_ready:ready,missing_evidence_ids:ready?[]:['E02']}}),{status:200,headers:{'Content-Type':'application/json'}});},
  browser:{runtime:{id:'bridge-test',getManifest:()=>({version:'2.3.0'}),onMessage:event,onInstalled:event,onStartup:event},storage:{local},action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{},setTitle:async()=>{}},tabs:{query:async()=>[],onUpdated:event},scripting:{executeScript:async()=>{}},permissions:{contains:async()=>false},alarms:{onAlarm:event,create:()=>{}}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension/background.js'),'utf8'),context);
(async()=>{
  await context.sendHandoff({ticket_id:901743,closure:'[GLPI_ASSISTANT:901743]\n[TAREFA:T02]\n[EVIDÊNCIA:E01]\n[EVIDÊNCIA:E02]\n[/TAREFA]',task_count:1,images:[{id:'E01',data:imageData}]},{manual:true});
  assert.ok(store.captureState22?.files?.length===1,'ACK parcial deve preservar o print capturado');
  assert.equal(store.lastSend.evidence_pending,true);
  await context.sendHandoff({ticket_id:901743,closure:'[GLPI_ASSISTANT:901743]\n[TAREFA:T02]\n[EVIDÊNCIA:E01]\n[EVIDÊNCIA:E02]\n[/TAREFA]',task_count:1,images:[{id:'E01',data:imageData},{id:'E02',data:imageData+'x'}]},{manual:true});
  assert.equal(store.captureState22,undefined,'ACK completo pode limpar evidências entregues');
  console.log('Bridge 2.4.1: ACK parcial preserva prints; ACK completo limpa.');
})().catch(e=>{console.error(e);process.exitCode=1;});
