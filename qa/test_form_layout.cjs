const {JSDOM}=require(process.env.JSDOM_PATH),fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const root=path.join(__dirname,'../package/usr/lib/glpi-assistant/app/static');
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://localhost:8765',runScripts:'outside-only'}),w=dom.window;
 // Respect the production stylesheet order, including the late queue stylesheet.
 for(const name of ['style.css','workspace.css','closure-queue.css']){let s=w.document.createElement('style');s.textContent=fs.readFileSync(path.join(root,name),'utf8');w.document.head.append(s);}
 w.executionBusy=false;w.normalizeText=x=>String(x);w.formatDuration=String;w.jsonOpts=x=>x;
 w.eval(fs.readFileSync(path.join(root,'closure-queue.js'),'utf8'));
 await w.ClosureQueue.receive({id:1,ticket_id:172263,closure:'[GLPI_ASSISTANT:172263]'});
 const q=s=>w.document.querySelector(s),css=s=>w.getComputedStyle(q(s));
 assert.equal(css('.queue-select-toggle').display,'flex');
 assert.equal(css('.queue-select-copy').flexDirection,'column');
 assert.equal(css('.queue-select-copy small').display,'block');
 assert.equal(css('.queue-select-toggle input').width,'18px');
 const checkbox=q('[data-selected]');const before=checkbox.checked;q('.queue-select-copy strong').click();assert.equal(checkbox.checked,!before);
 assert.equal(css('.queue-field').minWidth,'0px');
 assert.equal(q('[data-paste-image]').getAttribute('aria-label'),'Colar prints neste chamado');
 console.log('PASS: production cascade, label/help separation, checkbox dimensions and click, flexible fields, paste label');dom.window.close();
})().catch(e=>{console.error(e);process.exit(1)});
