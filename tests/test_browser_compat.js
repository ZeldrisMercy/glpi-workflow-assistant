'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{
 const code=fs.readFileSync('extension/browser-compat.js','utf8');
 let listener;const native={storage:{},runtime:{onMessage:{addListener(fn){listener=fn},removeListener(){}},sendMessage:async()=>({__glpiBridgeError:'failure'})},tabs:{}};
 const context={chrome:native};vm.createContext(context);vm.runInContext(code,context);assert.equal(context.browser,native);
 let reply;context.browser.runtime.onMessage.addListener(()=>Promise.resolve({ok:true}));assert.equal(listener({}, {},v=>reply=v),true);await new Promise(r=>setImmediate(r));assert.equal(reply.ok,true);
 context.browser.runtime.onMessage.addListener(()=>Promise.reject(Error('bad')));assert.equal(listener({}, {},v=>reply=v),true);await new Promise(r=>setImmediate(r));assert.equal(reply.__glpiBridgeError,'bad');
 await assert.rejects(context.browser.runtime.sendMessage({}),/failure/);
 const firefox={runtime:{}};const ff={browser:firefox,chrome:{}};vm.createContext(ff);vm.runInContext(code,ff);assert.equal(ff.browser,firefox);
 const manifest=JSON.parse(fs.readFileSync('extension/manifest.json'));
 assert.equal(manifest.content_scripts[0].js[0],'browser-compat.js');assert.equal(manifest.background.scripts[0],'browser-compat.js');
 console.log('Browser compatibility: Firefox preserved; Chromium async replies, channel lifetime and errors verified.');
})().catch(e=>{console.error(e);process.exit(1)});
