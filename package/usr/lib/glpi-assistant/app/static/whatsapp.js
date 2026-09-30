'use strict';
(() => {
  const el=id=>document.getElementById(id);
  let qrUrl=null, qrWanted=false, qrEpoch=0, qrLoading=false, lastState=null, toggling=false;
  function renderControls(){
    const d=lastState||{}, active=!!d.enabled, connected=d.status==='WORKING';
    el('waEnable').hidden=active;el('waPause').hidden=!active;
    el('waEnable').disabled=toggling||!connected||d.monitor_enabled===false;
    el('waPause').disabled=toggling;
    el('waEnable').textContent=toggling?'Retomando…':'Retomar envios';
    el('waPause').textContent=toggling?'Pausando…':'Pausar envios';
    el('waConnect').hidden=connected;el('waShowQR').hidden=connected;
    const badge=el('waAutomationBadge');
    badge.textContent=!lastState?'Consultando':!active?'Pausados':!connected||d.monitor_enabled===false?'Aguardando conexão/monitor':!d.baseline_ready?'Preparando referência':'Ativos';
    badge.dataset.state=active&&connected&&d.monitor_enabled!==false&&d.baseline_ready?'active':'paused';
  }
  async function request(path,method='GET',body){
    const response=await fetch('/api/whatsapp'+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json();if(!response.ok)throw Error(data.detail||'Não foi possível acessar o WhatsApp.');return data;
  }
  function clearQR(){qrEpoch++;if(qrUrl)URL.revokeObjectURL(qrUrl);qrUrl=null;el('waQR').removeAttribute('src');el('waQR').hidden=true;}
  async function refresh(){
    let data;
    try{data=await request('');}catch(error){clearQR();throw error;}
    const labels={NEEDS_SESSION:'Pronto para conectar',UNAVAILABLE:'Serviço indisponível',WORKING:'Conectado',STARTING:'Iniciando',SCAN_QR_CODE:'Aguardando QR Code',STOPPED:'Parado',FAILED:'Falha na sessão'};
    el('waStatus').textContent=(labels[data.status]||data.status)+(data.connected_account?' · '+data.connected_account.replace(/@.*$/,''):'')+(data.detail?' — '+data.detail:'');
    lastState=data;renderControls();
    el('waAutomationStatus').textContent=(data.automation_detail||'Confira o estado da automação.')+(data.baseline_at?' Referência: '+new Date(data.baseline_at*1000).toLocaleString('pt-BR')+'.':'');
    if(data.status!=='SCAN_QR_CODE')clearQR();
    if(['WORKING','FAILED','STOPPED','UNAVAILABLE','NEEDS_SESSION'].includes(data.status))qrWanted=false;
    if(data.status==='FAILED')el('waNote').textContent='A sessão falhou. O QR anterior foi descartado. Clique em Conectar WhatsApp para reiniciar a sessão.';
    if(data.status==='SCAN_QR_CODE'&&qrWanted&&!qrLoading)await loadQR();
    const root=el('waHistory');root.replaceChildren();
    for(const item of data.events){
      const delivered=['DEVICE','READ','PLAYED'].includes(item.delivery_name);
      const row=document.createElement('article');row.className='wa-event';
      const top=document.createElement('div');top.className='wa-event-heading';
      const title=document.createElement('strong');title.textContent='#'+item.ticket_id;
      const badge=document.createElement('span');badge.className='wa-badge';badge.dataset.state=delivered?'active':item.status==='resultado incerto'?'warning':'paused';
      badge.textContent=delivered?'Entregue':item.status==='aceito pelo WAHA'?'Aguardando entrega':item.status;
      top.append(title,badge);
      const meta=document.createElement('p');meta.className='small muted';meta.textContent=[item.initial?'Primeiro contato':'Retomada',new Date(item.at*1000).toLocaleString('pt-BR'),item.phone].filter(Boolean).join(' · ');
      const detail=document.createElement('p');detail.className='small';detail.textContent=(item.detail||'')+(item.error_code?' ('+item.error_code+')':'');
      row.append(top,meta,detail);root.append(row);
      if(item.initial&&item.status==='aceito pelo WAHA'&&!['DEVICE','READ','PLAYED'].includes(item.delivery_name)){
        const check=document.createElement('button');check.type='button';check.className='secondary';check.textContent='Verificar entrega';
        check.onclick=async()=>{check.disabled=true;try{const r=await request('/delivery/'+item.ticket_id,'POST');el('waNote').textContent=r.detail;await refresh();}catch(e){el('waNote').textContent=e.message;}finally{check.disabled=false;}};
        row.append(check);
      }
    }
    el('waHistoryCount').textContent=String(data.events.length);
    if(!data.events.length){const empty=document.createElement('p');empty.className='wa-empty';empty.textContent='Nenhum contato registrado. As próximas tentativas aparecerão aqui.';root.append(empty);}
  }
  function action(id,fn){el(id).onclick=async()=>{el(id).disabled=true;try{await fn();}catch(e){el('waNote').textContent=e.message;}finally{el(id).disabled=false;}};}
  action('waRefresh',refresh);
  action('waConnect',async()=>{
    clearQR();qrWanted=true;
    await request('/connect','POST');el('waNote').textContent='Preparando QR Code…';
    for(let i=0;i<12;i++){
      const status=await request('');
      if(status.status==='WORKING'){await refresh();el('waNote').textContent='WhatsApp conectado. Confira o número e ative a automação quando desejar.';return;}
      if(status.status==='SCAN_QR_CODE'){await loadQR();return;}
      if(status.status==='FAILED'){qrWanted=false;clearQR();throw Error('A sessão falhou ao conectar. Nenhuma mensagem foi enviada.');}
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
    el('waNote').textContent='A sessão ainda está iniciando. Use Mostrar QR Code em alguns instantes.';
  });
  async function loadQR(){
    if(qrLoading)return;
    qrLoading=true;const epoch=qrEpoch;
    try{
      const response=await fetch('/api/whatsapp/qr',{cache:'no-store'});
      if(!response.ok){const data=await response.json();throw Error(data.detail);}
      const blob=await response.blob();
      if(epoch!==qrEpoch||!qrWanted)return;
      if(qrUrl)URL.revokeObjectURL(qrUrl);
      qrUrl=URL.createObjectURL(blob);el('waQR').src=qrUrl;el('waQR').hidden=false;
      el('waNote').textContent='No celular: Aparelhos conectados → Conectar aparelho. O QR é atualizado enquanto esta tela está aberta.';
    }catch(error){if(epoch===qrEpoch)clearQR();throw error;}
    finally{qrLoading=false;}
  }
  action('waShowQR',async()=>{clearQR();qrWanted=true;await loadQR();});
  async function toggle(enabled){
    if(toggling)return;toggling=true;renderControls();
    try{
      await request('/settings','PUT',{enabled});
      el('waNote').textContent=enabled?'Envios retomados. A fila existente foi excluída; somente novas atribuições posteriores podem gerar contato.':'Envios pausados. Mensagens já submetidas não podem ser canceladas.';
      await refresh();
    }catch(e){el('waNote').textContent=e.message;}
    finally{toggling=false;renderControls();}
  }
  el('waEnable').onclick=()=>toggle(true);
  el('waPause').onclick=()=>toggle(false);
  const busy=new Set();
  async function resume(ticket,button,text){
    if(!ticket||busy.has(ticket.id))return;
    busy.add(ticket.id);button.disabled=true;const previous=button.textContent;button.textContent='Enviando…';
    // Keep the same request ID if the browser loses the server response.
    const feedback=button.parentElement?.querySelector('[data-contact-result]')||el('wbStatus');
    const storageKey='wa-resume-'+ticket.id;
    let requestId=sessionStorage.getItem(storageKey);
    if(!requestId){requestId=crypto.randomUUID();sessionStorage.setItem(storageKey,requestId);}
    try{
      const result=await request('/resume','POST',{ticket_id:ticket.id,request_id:requestId,...(text!==undefined?{text}: {})});
      const accepted=result.status==='aceito pelo WAHA';
      button.textContent=accepted?'Envio aceito · entrega não verificada':'Conferir envio';
      feedback.textContent=`#${ticket.id} · ${result.status}. ${result.detail}`;
      if(accepted)sessionStorage.removeItem(storageKey);
      // An uncertain attempt remains associated with its request ID: no blind retry.
    }catch(e){button.textContent=previous;feedback.textContent=e.message;}
    finally{busy.delete(ticket.id);button.disabled=false;}
  }
  function edit(ticket,button){
    if(!ticket||busy.has(ticket.id))return;
    let dialog=el('waResumeDialog');
    if(!dialog){
      dialog=document.createElement('dialog');dialog.id='waResumeDialog';dialog.setAttribute('aria-labelledby','waResumeTitle');
      dialog.innerHTML='<form method="dialog"><button class="secondary wb-dialog-close" aria-label="Fechar">×</button></form><h2 id="waResumeTitle">Personalizar retomada</h2><p id="waResumeContext"></p><label>Mensagem para este atendimento<textarea id="waResumeText" rows="6" maxlength="4000"></textarea></label><p class="small muted">A edição vale só para este envio. Para mudar o padrão, use as preferências da Minha central.</p><button type="button" id="waResumeSend">Enviar retomada</button>';
      document.body.append(dialog);
    }
    try{
      el('waResumeContext').textContent=`#${ticket.id} · ${ticket.title}`;
      el('waResumeText').value=ContactEditor.messageFor(ticket,'continuation',ticket.contacts?.[0]?.name||'');
      el('waResumeSend').onclick=()=>{const text=el('waResumeText').value.trim();if(!text.includes('#'+ticket.id)){el('waResumeContext').textContent='Mantenha #'+ticket.id+' na mensagem.';return;}dialog.close();resume(ticket,button,text);};
      dialog.showModal();
    }catch(e){el('wbStatus').textContent=e.message;}
  }
  globalThis.WhatsAppContact={resume,edit};
  window.addEventListener('hashchange',()=>{if(location.hash==='#bridge-ia')refresh().catch(e=>{el('waNote').textContent=e.message;});else {qrWanted=false;clearQR();}});
  let refreshing=false;
  setInterval(async()=>{if(refreshing||document.hidden||el('bridge-ia').classList.contains('wb-off'))return;refreshing=true;try{await refresh();}catch{}finally{refreshing=false;}},8000);
  refresh().catch(e=>{el('waNote').textContent=e.message;});
})();
