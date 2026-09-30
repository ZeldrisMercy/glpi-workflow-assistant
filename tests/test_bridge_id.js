const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const path=require('node:path');
const sent=[];
const event={addListener:()=>{}};
const store={bridgeToken:'test-only',settings:{openIfClosed:false,autoSend:true,focusOnSend:false}};
const local={
  get:async(keys)=>{
    if(keys==null)return {...store};
    if(typeof keys==='string')return {[keys]:store[keys]};
    if(Array.isArray(keys))return Object.fromEntries(keys.map(k=>[k,store[k]]));
    const out={};for(const [k,v] of Object.entries(keys||{}))out[k]=store[k]===undefined?v:store[k];return out;
  },
  set:async(values)=>{Object.assign(store,values||{});},
  remove:async(keys)=>{for(const k of (Array.isArray(keys)?keys:[keys]))delete store[k];},
};
const context={Headers,AbortController,setTimeout,clearTimeout,URL,console,Response,
  fetch:async(url,options)=>{sent.push(JSON.parse(options.body));return new Response(JSON.stringify({ok:true,handoff:{id:1,task_count:1}}),{status:200,headers:{'Content-Type':'application/json'}});},
  browser:{runtime:{id:'bridge-test',getManifest:()=>({version:'2.3.0'}),onMessage:event,onInstalled:event,onStartup:event},
    storage:{local},
    action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{},setTitle:async()=>{}},
    tabs:{query:async()=>[],onUpdated:event},
    scripting:{executeScript:async()=>{}},permissions:{contains:async()=>false},
    alarms:{onAlarm:event,create:()=>{}}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension/background.js'),'utf8'),context);
(async()=>{
  await context.sendHandoff({closure:'[GLPI_ASSISTANT : 901159 ]\n[TAREFA:T01]',task_count:1}, {manual:true});
  assert.equal(sent[0].ticket_id,901159);
  assert.equal(sent[0].version,2,'Bridge 2.3.0 deve usar protocolo HTTP 2 aceito pelo Assistant');
  assert.equal((store.bridgeOutbox22||[]).length,0,'ACK deve remover pacote da outbox');
  await assert.rejects(context.sendHandoff({ticket_id:170424,closure:'[GLPI_ASSISTANT:901159]'}, {manual:true}),/divergem/);
  await assert.rejects(context.sendHandoff({closure:'Texto sem número'}, {manual:true}),/Número ausente/);
  assert.equal(sent.length,1);
  console.log('Bridge: recuperação do número, ACK/outbox, conflito e ausência verificados.');
})().catch(e=>{console.error(e);process.exitCode=1;});
