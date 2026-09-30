const {JSDOM}=require(process.env.JSDOM_PATH),fs=require('fs'),assert=require('assert');
(async()=>{
 const dom=new JSDOM('<html><body></body></html>',{url:'https://chatgpt.com/',runScripts:'outside-only'}),w=dom.window;
 w.browser={storage:{local:{get:async()=>({}),set:async()=>{},remove:async()=>{}}}};
 w.eval(fs.readFileSync('extension/evidence-plan.js','utf8'));w.eval(fs.readFileSync('extension/capture.js','utf8'));
 const input=w.document.createElement('input');input.type='file';w.document.body.append(input);
 await new Promise(r=>setTimeout(r,10));input.remove();
 Object.defineProperty(input,'files',{value:[new w.File(['proof'],'E01-proof.png',{type:'image/png'})]});input.dispatchEvent(new w.Event('change'));
 await new Promise(r=>setTimeout(r,30));
 let p=await w.glpiCapture.packetFor(172148,'[EVIDÊNCIA:E01]');assert.equal(p.images.length,1);
 const e=new w.Event('paste',{bubbles:true});Object.defineProperty(e,'clipboardData',{value:{items:[{kind:'file',getAsFile:()=>new w.File(['context'],'ticket.png',{type:'image/png'})}]}});w.document.body.dispatchEvent(e);
 await new Promise(r=>setTimeout(r,30));assert.equal(w.glpiCapture.stats().count,2);p=await w.glpiCapture.packetFor(172148,'[EVIDÊNCIA:E01]');assert.equal(p.images.length,1);
 w.history.pushState({},'', '/c/first');p=await w.glpiCapture.packetFor(172148,'[EVIDÊNCIA:E01]');assert.equal(p.images.length,1);
 p=await w.glpiCapture.packetFor(172148,'[EVIDÊNCIA:E02]\nEVIDENCIA_ARQUIVO: E02 | ticket.png',{multiTicket:true});assert.equal(p.images.length,0);
 p=await w.glpiCapture.packetFor(172148,'[EVIDÊNCIA:E02]\nEVIDENCIA_ARQUIVO: E02 | ticket.png');assert.equal(p.images.length,1);assert.equal(p.images[0].id,'E02');
 dom.window.close();console.log('PASS: detached input, clipboard items, capture before submit, first route, context exclusion');
})().catch(e=>{console.error(e);process.exit(1)});
