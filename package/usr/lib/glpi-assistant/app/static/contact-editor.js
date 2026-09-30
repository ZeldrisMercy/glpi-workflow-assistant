'use strict';
(() => {
  const el=id=>document.getElementById(id), contract=ContactTemplate;
  let saved={}, profile={name:''}, profileStarted=false, active=null;
  const initial=el('wbMessage'), continuation=el('wbContinuationMessage');
  initial.value=contract.defaultMessage;
  continuation.value=contract.defaultContinuationMessage;
  const controls=document.createElement('div');controls.className='contact-editor-grid';
  const editor=document.createElement('div');editor.className='contact-template-edit';
  initial.parentElement.before(controls);editor.append(initial.parentElement);controls.append(editor);
  const toolbar=document.createElement('div');toolbar.className='token-toolbar';toolbar.id='wbMessageTokens';
  editor.prepend(toolbar);
  const help=document.createElement('p');help.className='small muted';
  help.textContent='Clique para inserir um campo na posição do cursor. Mantenha {chamado}: o número muda a cada contato. O atalho |/Chamado também é aceito.';editor.append(help);
  editor.insertAdjacentHTML('beforeend','<div class="actions"><button type="button" class="secondary compact" id="wbRestoreMessage">Usar mensagem sugerida</button></div>');
  controls.insertAdjacentHTML('beforeend','<aside class="contact-preview-pane"><span class="section-kicker">PRÉVIA DO MODELO</span><p class="muted small">Exemplo fictício · o chamado real será usado ao contatar.</p><div id="wbMessagePreview" class="message-preview"></div><p id="wbMessageValidation" role="status" class="small"></p></aside>');
  const contWrap=document.createElement('div');contWrap.className='contact-template-continuation';continuation.parentElement.before(contWrap);contWrap.append(continuation.parentElement);
  const contToolbar=document.createElement('div');contToolbar.className='token-toolbar';contToolbar.id='wbContinuationTokens';contWrap.prepend(contToolbar);
  contWrap.insertAdjacentHTML('beforeend','<p class="small muted">Modelo rápido para retomada de atendimento. O número e o assunto do chamado são preenchidos automaticamente.</p><div id="wbContinuationPreview" class="message-preview"></div><p id="wbContinuationValidation" role="status" class="small"></p><div class="actions"><button type="button" class="secondary compact" id="wbRestoreContinuation">Usar continuidade sugerida</button></div>');
  function tokens(root,target,onChange){
    Object.entries(contract.labels).forEach(([key,label])=>{
      const b=document.createElement('button');b.type='button';b.className='token-chip';b.textContent=label;b.title=`Inserir {${key}}`;
      b.addEventListener('click',()=>{target.setRangeText(`{${key}}`,target.selectionStart,target.selectionEnd,'end');target.focus();onChange();});root.append(b);
    });
  }
  tokens(toolbar,initial,updateDefault);
  tokens(contToolbar,continuation,updateDefault);
  function updateDefault(){
    try{
      el('wbMessagePreview').textContent=contract.render(initial.value,{chamado:123456,nome:'Marina',tecnico:el('wbContactName').value.trim()||profile.name||'Seu nome',assunto:'Acesso ao e-mail',empresa:'Empresa exemplo'},new Date(),el('wbTimezone').value);
      el('wbMessageValidation').textContent='Modelo válido · número preenchido automaticamente.';
      el('wbMessageValidation').className='small contact-valid';initial.setAttribute('aria-invalid','false');
    }catch(e){el('wbMessagePreview').textContent='Corrija o modelo para visualizar a mensagem.';el('wbMessageValidation').textContent=e.message;el('wbMessageValidation').className='small contact-error';initial.setAttribute('aria-invalid','true');}
    try{
      el('wbContinuationPreview').textContent=contract.render(continuation.value,{chamado:123456,nome:'Marina',tecnico:el('wbContactName').value.trim()||profile.name||'Seu nome',assunto:'Acesso ao e-mail',empresa:'Empresa exemplo'},new Date(),el('wbTimezone').value);
      el('wbContinuationValidation').textContent='Modelo de continuidade válido.';el('wbContinuationValidation').className='small contact-valid';continuation.setAttribute('aria-invalid','false');
    }catch(e){el('wbContinuationPreview').textContent='Corrija o modelo para visualizar a mensagem.';el('wbContinuationValidation').textContent=e.message;el('wbContinuationValidation').className='small contact-error';continuation.setAttribute('aria-invalid','true');}
  }
  initial.setAttribute('aria-describedby','wbMessageValidation');continuation.setAttribute('aria-describedby','wbContinuationValidation');
  [initial,continuation,el('wbContactName'),el('wbTimezone')].forEach(e=>e.addEventListener('input',updateDefault));
  el('wbRestoreMessage').onclick=()=>{initial.value=contract.defaultMessage;updateDefault();};
  el('wbRestoreContinuation').onclick=()=>{continuation.value=contract.defaultContinuationMessage;updateDefault();};
  async function loadProfile(){
    el('wbContactIdentity').textContent='Buscando seu nome no GLPI…';
    try{const r=await fetch('/api/workbench/contact-profile');if(!r.ok)throw Error();profile=await r.json();
      el('wbContactIdentity').textContent=profile.name?`Nome identificado no GLPI: ${profile.name}. Deixe o campo vazio para usá-lo.`:'Seu nome não está disponível na API. Preencha como deseja se apresentar.';
    }catch{profile={name:''};el('wbContactIdentity').textContent='Não foi possível consultar seu nome. Preencha como deseja se apresentar ou tente atualizar.';}
    updateDefault();if(active){if(!active.nameTouched)el('wbContactDisplayName').value=saved.contact_name||profile.name||'';updateContact();}
  }
  el('wbContactRefreshName').onclick=loadProfile;
  function settings(){return {contact_message:contract.validate(initial.value),continuation_message:contract.validate(continuation.value),contact_name:el('wbContactName').value.trim()};}
  function accept(settings,fill){
    saved={...settings};
    if(fill){initial.value=settings.contact_message||contract.defaultMessage;continuation.value=settings.continuation_message||contract.defaultContinuationMessage;el('wbContactName').value=settings.contact_name||'';updateDefault();}
    if(!profileStarted){profileStarted=true;loadProfile();}
  }
  function ensureDialog(){
    if(el('wbContactDialog'))return;
    const d=document.createElement('dialog');d.id='wbContactDialog';d.setAttribute('aria-labelledby','wbContactTitle');
    d.innerHTML='<form method="dialog"><button class="secondary wb-dialog-close" aria-label="Fechar">×</button></form><h2 id="wbContactTitle">Contatar pelo WhatsApp</h2><p id="wbContactContext" class="muted"></p><div class="contact-editor-grid"><section><label>Como você vai se apresentar<input id="wbContactDisplayName" maxlength="120" placeholder="Nome do técnico"></label><div id="wbContactTokens" class="token-toolbar"></div><label>Mensagem para este contato<textarea id="wbContactText" rows="6" maxlength="2000" aria-describedby="wbContactValidation"></textarea></label><p class="muted small">Edite à vontade e mantenha {chamado}. Esta edição vale só para este contato.</p></section><aside class="contact-preview-pane"><span class="section-kicker">MENSAGEM QUE VAI ABRIR</span><div id="wbContactPreview" class="message-preview"></div><p id="wbContactClock" class="muted small"></p></aside></div><p id="wbContactValidation" role="status"></p><div class="contact-dialog-footer"><span class="muted small">Revise e envie a mensagem no WhatsApp.</span><a id="wbContactGo" target="_blank" rel="noopener" aria-disabled="true">Abrir conversa</a></div>';
    document.body.append(d);
    el('wbContactGo').addEventListener('click',event=>{if(!updateContact()) {event.preventDefault();return;}event.preventDefault();void openConversation(el('wbContactGo').href).catch(error=>{el('wbContactValidation').textContent=error.message;});});
    tokens(el('wbContactTokens'),el('wbContactText'),updateContact);
    el('wbContactText').oninput=updateContact;el('wbContactDisplayName').oninput=()=>{active.nameTouched=true;updateContact();};
    el('wbContactGo').addEventListener('auxclick',e=>{if(!updateContact())e.preventDefault();});
    d.addEventListener('close',()=>{active=null;});
  }
  function updateContact(){
    if(!active)return false;
    try{
      const text=contract.render(el('wbContactText').value,{nome:active.name,tecnico:el('wbContactDisplayName').value.trim(),chamado:active.ticket.id,assunto:active.ticket.title,empresa:active.ticket.entity},new Date(),active.timezone);
      const u=new URL(active.url);
      if(u.protocol!=='https:'||u.hostname!=='wa.me'||!/^\/\d{8,15}$/.test(u.pathname))throw Error('Contato sem número de WhatsApp válido. Confira o cadastro no GLPI.');
      u.search='';u.hash='';u.searchParams.set('text',text);
      const direct=new URL('https://web.whatsapp.com/send');direct.searchParams.set('phone',u.pathname.slice(1));direct.searchParams.set('text',text);
      el('wbContactGo').href=direct.href;el('wbContactGo').setAttribute('aria-disabled','false');el('wbContactGo').tabIndex=0;
      el('wbContactPreview').textContent=text;
      el('wbContactClock').textContent=`Saudação pelo horário do contato · ${active.timezone}. Atualizada também ao abrir a conversa.`;
      el('wbContactValidation').textContent=`Chamado #${active.ticket.id} identificado automaticamente.`;el('wbContactValidation').className='small contact-valid';
      el('wbContactText').setAttribute('aria-invalid','false');return true;
    }catch(e){el('wbContactGo').removeAttribute('href');el('wbContactGo').setAttribute('aria-disabled','true');el('wbContactGo').tabIndex=-1;
      el('wbContactPreview').textContent='Corrija os campos para abrir a conversa.';el('wbContactValidation').textContent=e.message;el('wbContactValidation').className='small contact-error';el('wbContactText').setAttribute('aria-invalid','true');return false;}
  }
  function open(a,ticket){
    ensureDialog();active={ticket:{...ticket},name:a.dataset.name,url:a.dataset.wa||a.href,timezone:saved.timezone||'America/Sao_Paulo'};
    el('wbContactText').value=saved.contact_message||contract.defaultMessage;
    el('wbContactDisplayName').value=saved.contact_name||profile.name||'';
    el('wbContactContext').textContent=`#${ticket.id} · ${ticket.entity} · ${a.dataset.name} · ${a.dataset.phone}`;
    updateContact();el('wbContactDialog').showModal();
  }
  setInterval(()=>{if(active&&!document.hidden)updateContact();},30000);
  function messageFor(ticket,mode='first',contactName=''){
    const template=mode==='continuation'?(saved.continuation_message||contract.defaultContinuationMessage):(saved.contact_message||contract.defaultMessage);
    return contract.render(template,{nome:contactName||'Contato',tecnico:saved.contact_name||profile.name||'',chamado:ticket.id,assunto:ticket.title,empresa:ticket.entity},new Date(),saved.timezone||'America/Sao_Paulo');
  }
  let bridgeNavigationAvailable=false;
  const pingId=crypto.randomUUID();
  window.addEventListener('message',event=>{if(event.source===window&&event.origin===location.origin&&event.data?.type==='glpi-assistant:whatsapp-pong'&&event.data.requestId===pingId)bridgeNavigationAvailable=true;});
  window.postMessage({type:'glpi-assistant:whatsapp-ping',requestId:pingId},location.origin);
  async function openConversation(url) {
    if (!bridgeNavigationAvailable) {const tab=window.open(url,'glpi-assistant-whatsapp');if(tab)tab.opener=null;else throw Error('Abertura bloqueada pelo navegador. Atualize o Bridge e recarregue esta página.');return;}
    const requestId=crypto.randomUUID();
    const response=new Promise(resolve=>{
      const onMessage=event=>{
        if(event.source!==window||event.origin!==location.origin||event.data?.type!=='glpi-assistant:open-whatsapp-result'||event.data.requestId!==requestId)return;
        clearTimeout(timeout);window.removeEventListener('message',onMessage);resolve(event.data);
      };
      const timeout=setTimeout(()=>{window.removeEventListener('message',onMessage);resolve(null);},1200);
      window.addEventListener('message',onMessage);
    });
    window.postMessage({type:'glpi-assistant:open-whatsapp',requestId,url},location.origin);
    const result=await response;
    if(result?.ok)return;
    throw Error(result?.error||'Bridge não respondeu. Atualize a extensão e tente abrir novamente.');
  }
  function direct(a,ticket){
    const u=new URL(a.dataset.wa||a.href);
    if(u.protocol!=='https:'||u.hostname!=='wa.me'||!/^\/\d{8,15}$/.test(u.pathname))throw Error('Confira o telefone do contato.');
    const target=new URL('https://web.whatsapp.com/send');
    target.searchParams.set('phone',u.pathname.slice(1));
    // Navigation must not depend on the contact template or technician profile.
    // Drafting a message remains an explicit action in the message editor.
    void openConversation(target.href).catch(error=>{el('wbStatus').textContent=error.message;});
  }
  globalThis.ContactEditor={settings,accept,open,direct,updateDefault,messageFor};
})();
