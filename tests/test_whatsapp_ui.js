const assert=require('assert/strict');
const fs=require('fs');const vm=require('vm');
const elements=new Map();
function el(id){if(!elements.has(id))elements.set(id,{textContent:'',checked:false,disabled:false,hidden:true,classList:{contains:()=>true},replaceChildren(){},append(){},removeAttribute(){},click(){return this.onclick?.();}});return elements.get(id);}
const storage=new Map(), requests=[];
let releaseSend;
const ctx={document:{getElementById:el,hidden:false,createElement:()=>({}),body:{append(){}}},window:{addEventListener(){}},location:{hash:''},URL,crypto:{randomUUID:()=> '12345678-1234-4234-8234-123456789012'},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setInterval(){},setTimeout,console,
 fetch:async(path,options)=>{requests.push({path,options});if(path.endsWith('/resume')){await new Promise(r=>releaseSend=r);return {ok:true,json:async()=>({status:'aceito pelo WAHA',detail:'Aceito'})};}return {ok:true,json:async()=>({enabled:false,status:'WORKING',events:[]})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('package/usr/lib/glpi-assistant/app/static/whatsapp.js','utf8'),ctx);
(async()=>{
 const button=el('testButton');button.textContent='Retomar atendimento';
 const pending=ctx.WhatsAppContact.resume({id:7},button);
 assert.equal(button.disabled,true);
 await ctx.WhatsAppContact.resume({id:7},button);
 assert.equal(requests.filter(x=>x.path.endsWith('/resume')).length,1);
 releaseSend();await pending;
 assert.equal(button.textContent,'Envio aceito · entrega não verificada');
 assert.equal(button.disabled,false);
 const payload=JSON.parse(requests.find(x=>x.path.endsWith('/resume')).options.body);
 assert.equal(payload.ticket_id,7);assert.equal(payload.text,undefined);
 console.log('Retomada: um clique submete o modelo padrão; duplo clique concorrente bloqueado; resultado inline.');
})().catch(e=>{console.error(e);process.exitCode=1;});
