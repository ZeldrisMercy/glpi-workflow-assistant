'use strict';
const vm=require('vm'),fs=require('fs'),assert=require('assert');
class Node {
 constructor(){this.style={};this.children=[];this.isConnected=true;this.nodes=new Map();}
 append(...n){this.children.push(...n)}
 attachShadow(){return new Node()}
 getElementById(k){if(!this.nodes.has(k))this.nodes.set(k,new Node());return this.nodes.get(k)}
 querySelector(k){return this.getElementById(k)}
 replaceChildren(){this.children=[]}
 addEventListener(){}
 setAttribute(){}
}
(async()=>{
 const handlers={};let resolveStorage;
 const doc={documentElement:new Node(),createElement:()=>new Node(),querySelectorAll:()=>[],addEventListener:(name,fn)=>handlers[name]=fn};
 const c={document:doc,window:{addEventListener(){}},location:{origin:'https://chatgpt.com',pathname:'/'},URL,Map,Set,Promise,Date,
   HTMLInputElement:Node,Element:Node,setInterval:()=>0,setTimeout:()=>0,clearTimeout(){},
   browser:{storage:{local:{get:()=>new Promise(r=>resolveStorage=r),set:async()=>{},remove:async()=>{}}}},
   FileReader:class {readAsDataURL(file){this.result='data:image/png;base64,'+file.bytes;this.onload()}},
   GLPiEvidencePlan:require('../extension/evidence-plan.js')};
 vm.createContext(c);vm.runInContext(fs.readFileSync('extension/capture.js','utf8'),c);
 const file={name:'E01-proof.png',type:'image/png',size:20,lastModified:1,bytes:'FIRST'};
 handlers.paste({clipboardData:{files:[file]}});
 resolveStorage({captureState22:{page:'https://chatgpt.com/',files:[{key:'context',name:'ticket.png',id:'',type:'image/png',data:'CONTEXT',size:20}]}});
 const result=await c.glpiCapture.packetFor(1,'[EVIDÊNCIA:E01]');
 assert.equal(result.images.length,1);assert.equal(result.images[0].data,'FIRST');
 c.location.pathname='/c/new-conversation';
 const migrated=await c.glpiCapture.packetFor(1,'[EVIDÊNCIA:E01]');
 assert.equal(migrated.images[0].data,'FIRST');
 assert.equal(c.glpiCapture.stats().count,2);
 console.log('First prompt: storage race, original bytes, route promotion and context exclusion verified.');
})().catch(e=>{console.error(e);process.exit(1)});
