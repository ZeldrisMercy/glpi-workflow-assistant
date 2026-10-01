const fs=require('fs'),assert=require('node:assert/strict'),{JSDOM}=require(process.env.JSDOM_PATH||'jsdom');
const path=require('path'),root=path.join(__dirname,'../package/usr/lib/glpi-assistant/app/static');
(async()=>{
const d=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{runScripts:'outside-only',url:'http://localhost:8765'}),w=d.window;
let state='SCAN_QR_CODE',fail=false,held=null,hold=false,qrCalls=0;w.setInterval=()=>{};
w.URL.createObjectURL=()=> 'blob:synthetic-qr';w.URL.revokeObjectURL=()=>{};
w.fetch=async p=>{if(p.endsWith('/qr')){qrCalls++;if(hold)await new Promise(r=>held=r);return {ok:!fail,json:async()=>({detail:'QR indisponível'}),blob:async()=>new w.Blob(['fake PNG'])};}return {ok:true,json:async()=>({status:state,enabled:false,events:[]})};};
w.eval(fs.readFileSync(path.join(root,'whatsapp.js'),'utf8'));await new Promise(r=>setImmediate(r));
const q=s=>w.document.getElementById(s);
await q('waShowQR').onclick();assert.equal(q('waQR').hidden,false);
await q('waRefresh').onclick();assert.equal(qrCalls,2,'refresh fetches fresh QR');
state='FAILED';await q('waRefresh').onclick();assert.equal(q('waQR').hidden,true);assert.equal(q('waQR').getAttribute('src'),null);
state='SCAN_QR_CODE';await q('waShowQR').onclick();fail=true;await q('waShowQR').onclick();assert.equal(q('waQR').hidden,true);
fail=false;hold=true;const pending=q('waShowQR').onclick();await new Promise(r=>setImmediate(r));state='FAILED';await q('waRefresh').onclick();held();await pending;assert.equal(q('waQR').hidden,true,'late QR must not revive after FAILED');
d.window.close();console.log('PASS QR: renovação, limpeza em FAILED/erro e descarte de resposta atrasada');
})().catch(e=>{console.error(e);process.exitCode=1});
