const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const src=fs.readFileSync(require('node:path').join(__dirname,'../extension/background.js'),'utf8');
const fn=src.slice(src.indexOf('async function openExistingWhatsapp('),src.indexOf('async function captureGlpi()'));
const calls=[];let tabs=[{id:18,windowId:3,url:'https://web.whatsapp.com/',cookieStoreId:'personal'},{id:19,windowId:7,url:'https://web.whatsapp.com/',cookieStoreId:'work'}];
const browser={tabs:{query:async()=>tabs,update:async(...args)=>calls.push(['update',...args]),create:async(...args)=>{calls.push(['create',...args]);tabs.push({id:21,...args[0]});}},windows:{update:async(...args)=>calls.push(['focus',...args])}};
const ctx={URL,browser};vm.createContext(ctx);vm.runInContext(fn,ctx);
(async()=>{
 const sender={tab:{url:'http://127.0.0.1:8765/#central',windowId:7,cookieStoreId:'work'}};
 const target='https://web.whatsapp.com/send?phone=5531999998888&text=Chamado%20%23123';
 assert.equal((await ctx.openExistingWhatsapp(target,sender)).reused,true);
 assert.equal(calls[0][0],'update');assert.equal(calls[0][1],19);assert.equal(calls.length,1);
 await assert.rejects(ctx.openExistingWhatsapp(target,{tab:{url:'https://evil.test/',windowId:7}}));
 await assert.rejects(ctx.openExistingWhatsapp('https://web.whatsapp.com/send?phone=123&text=Oi',sender));
 tabs=[];calls.length=0;assert.equal((await ctx.openExistingWhatsapp(target,sender)).reused,false);assert.equal(calls[0][0],'create');
 tabs=[];calls.length=0;await Promise.all([ctx.openExistingWhatsapp(target,sender),ctx.openExistingWhatsapp(target,sender)]);assert.equal(calls.filter(x=>x[0]==='create').length,1);assert.equal(calls.filter(x=>x[0]==='update').length,1);
 console.log('PASS: WhatsApp existing tab reused in same browser container, no duplicate, untrusted origin blocked, absent tab created');
})().catch(e=>{console.error(e);process.exitCode=1;});
