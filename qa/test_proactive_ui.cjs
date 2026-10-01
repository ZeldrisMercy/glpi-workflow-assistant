const assert=require('assert'),fs=require('fs');
const {JSDOM}=require(process.env.JSDOM_PATH);
const dom=new JSDOM('<section id="proativos"></section>',{url:'http://127.0.0.1:8765',runScripts:'outside-only'}),w=dom.window;
let current=[1,2].map(n=>({id:'u:P0'+n,draft:{draft_ref:'P0'+n,title:'Inventário '+n,entity:'Aurora Labs (example)',category:'Documentação',priority:3,tasks:[],target:'active',evidence:[]},prompt_timestamp:'2026-09-30T00:12:22-03:00',images:{}}));
const calls=[];
w.api=async(url,opts)=>{const data=opts.body?JSON.parse(opts.body):null;calls.push({url,data});if(url.endsWith('/drafts'))return {items:JSON.parse(JSON.stringify(current))};if(url.endsWith('/plan'))return {plan_id:data.id,digest:'digest',pending_fields:[],resolved:{entity:{id:7,name:'Aurora Labs (example)'}}};if(url.endsWith('/execute')){const n=data.plan_id.endsWith('1')?1:2;if(n===1){current=current.filter(x=>x.id!==data.plan_id);return {status:'completed',ticket_id:100,url:'https://glpi.test/front/ticket.form.php?id=100'};}return {status:'partial',ticket_id:101,error:'Verifique a etapa pendente'};}throw Error(url);};
w.eval(fs.readFileSync(__dirname+'/../package/usr/lib/glpi-assistant/app/static/proactive.js','utf8'));
(async()=>{await w.Proactive.refresh();assert.equal(w.document.querySelectorAll('[data-proactive-row]').length,2);
 const input=w.document.querySelector('[data-field="title"]');input.value='Título ajustado';input.dispatchEvent(new w.Event('input'));await w.Proactive.refresh();assert.equal(w.document.querySelector('[data-field="title"]').value,'Título ajustado');
 const all=w.document.querySelector('#prAll');all.checked=true;all.dispatchEvent(new w.Event('change'));
 await w.document.querySelector('#prReview').onclick();assert(!w.document.querySelector('#prCreate').disabled);assert(w.document.querySelector('.pr-resolved').textContent.includes('Aurora Labs (example)'));
 // Editing invalidates review before any creation.
 const field=w.document.querySelector('[data-field="category"]');field.value='Nova categoria';field.dispatchEvent(new w.Event('input'));assert(w.document.querySelector('#prCreate').disabled);
 await w.document.querySelector('#prReview').onclick();await w.document.querySelector('#prCreate').onclick();assert.equal(w.document.querySelectorAll('[data-proactive-row]').length,1);assert(w.document.querySelector('#prStatus a'));assert(w.document.querySelector('#prStatus').textContent.includes('etapa pendente'));
 assert.equal(calls.filter(x=>x.url.endsWith('/execute')).length,2);w.close();console.log('PASS proactive UI: batch, edit invalidation, retained drafts, partial result and GLPI receipt');
})().catch(e=>{console.error(e);process.exit(1)});
