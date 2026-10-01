const {JSDOM}=require(process.env.JSDOM_PATH || 'jsdom');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'../package/usr/lib/glpi-assistant/app/static');
async function scenario(counts,failAt=null,finishFails=false){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://localhost:8765',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.confirm=()=>true;w.executionBusy=false;w.normalizeText=x=>String(x);w.formatDuration=x=>String(x);w.jsonOpts=x=>({json:x});
 const sent=[];let finalized=0;
 w.finishAfterFormalization=async()=>{finalized++;if(finishFails)throw Error('Solução não confirmada');};
 w.api=async(url,opts)=>{
  if(url==='/api/plan'){const id=opts.json.ticket_id;return {ticket:{id,title:'Teste'},required_evidence_ids:[],parsed:{evidence_ids:[]},operations:[],task_count:counts[id-100],has_actionable_operations:true,plan_id:String(id)};}
  if(url==='/api/execute'){const id=Number(opts.body.get('ticket_id'));sent.push(id);if(id===failAt)return {ok:false,verified_task_count:1,expected_task_count:counts[id-100],errors:[{message:'Falha parcial'}]};return {ok:true,verified_task_count:counts[id-100],expected_task_count:counts[id-100],errors:[]};}
  throw Error('unexpected '+url);
 };
 w.eval(fs.readFileSync(path.join(root,'batch-receipt.js'),'utf8'));
 w.eval(fs.readFileSync(path.join(root,'closure-queue.js'),'utf8'));
 for(let i=0;i<counts.length;i++)await w.ClosureQueue.receive({id:i+1,ticket_id:100+i,closure:`[GLPI_ASSISTANT:${100+i}]\nTarefas de teste`});
 const q=s=>w.document.querySelector(s);
 for(const panel of w.document.querySelectorAll('.closure-pane')){panel.querySelector('[data-selected]').checked=true;if(finishFails){panel.querySelector('[data-target]').value='solve';panel.querySelector('[data-solution]').value='Solução validada de teste';}}
 await q('[data-review]').onclick();assert.equal(q('[data-apply]').disabled,false);
 await q('[data-apply]').onclick();
 return {w,dom,q,sent,finalized};
}
(async()=>{
 let r=await scenario([1,3,7]);assert.deepEqual(r.sent,[100,101,102]);assert.equal(r.w.document.querySelectorAll('.closure-pane').length,0);assert(r.q('#batchReceipt').open);assert.equal(r.q('#batchReceiptTitle').textContent,'Envio confirmado');assert.equal(r.w.document.querySelectorAll('.receipt-result').length,3);
 r.q('.receipt-footer button').click();assert.equal(r.w.document.querySelectorAll('.closure-pane').length,1);assert.equal(r.q('#batchReceipt').open,false);r.dom.window.close();console.log('PASS: 1, 3 e 7 tarefas removidas; comprovante e novo chamado');
 r=await scenario([2,5,1],101);assert.deepEqual(r.sent,[100,101]);assert.equal(r.w.document.querySelectorAll('.closure-pane').length,2);assert.equal(r.q('#batchReceiptTitle').textContent,'Lote interrompido');assert.equal(r.w.document.querySelectorAll('.receipt-result.attention').length,1);
 const pending=r.w.document.querySelectorAll('.receipt-next-list button');assert.equal(pending.length,2);pending[1].click();assert.equal(r.q('.closure-pane:not([hidden]) [data-ticket]').value,'102');assert.deepEqual(r.sent,[100,101]);r.dom.window.close();console.log('PASS: falha parcial preserva abas e não envia o restante; navegação sem reenvio');
 r=await scenario([5],null,true);assert.equal(r.w.document.querySelectorAll('.closure-pane').length,1);assert.equal(r.finalized,1);r.w.ClosureQueue.reconcile([1]);assert.equal(r.w.document.querySelectorAll('.closure-pane').length,1,'task receipt must not discard failed finalization');assert.equal(r.q('#batchReceiptTitle').textContent,'Lote interrompido');r.dom.window.close();console.log('PASS: falha na conclusão preserva a aba após tarefas confirmadas');
 // Untrusted server strings must stay text, never markup.
 const d=new JSDOM('<body></body>',{runScripts:'outside-only'});d.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};d.window.eval(fs.readFileSync(path.join(root,'batch-receipt.js'),'utf8'));
 d.window.BatchReceipt.show({outcomes:[{id:1,ok:false,detail:'<img src=x onerror=alert(1)>'}],pending:[],selectPending(){},createDraft(){}});assert.equal(d.window.document.querySelector('img'),null);d.window.close();console.log('PASS: conteúdo do comprovante tratado como texto');
})().catch(e=>{console.error(e);process.exitCode=1;});
