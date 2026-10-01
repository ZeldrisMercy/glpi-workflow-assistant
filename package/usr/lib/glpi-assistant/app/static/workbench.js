'use strict';
(() => {
  const el = id => document.getElementById(id);
  const safe = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const request = async (path, options={}) => {
    const r = await fetch(path, options);
    const text = await r.text(); let data;
    try { data = JSON.parse(text); } catch { throw Error(`Resposta inválida (${r.status})`); }
    if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    return data;
  };
  const json = data => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const date = ts => ts ? new Date(ts*1000).toLocaleString('pt-BR') : 'Sem registro';
  const age = ts => { const h=Math.max(0,(Date.now()/1000-ts)/3600); return h<1 ? `${Math.floor(h*60)} min` : h<48 ? `${Math.floor(h)} h` : `${Math.floor(h/24)} dias`; };
  const run = (id, fn, output='wbStatus') => { el(id).onclick=async()=>{ el(id).disabled=true; try { await fn(); } catch(e){ el(output).textContent=e.message; } finally{el(id).disabled=false;} }; };
  let state={items:[]}, filter='new', selected=new Set(), expanded=new Set(), solutionPlan=null, templatePlan=null, templateFiles=[], templateTicket=0;
  let templateAfterAction=null, templateRevision=0;
  let templateLoadRevision=0;
  window.resetWorkbenchEditor = () => {
    templateLoadRevision++; templateRevision++;
    templatePlan=null; templateAfterAction=null; templateFiles=[]; templateTicket=0;
    el('wbTemplateTasks').querySelectorAll('img').forEach(i=>URL.revokeObjectURL(i.src));
    el('wbTemplateTasks').replaceChildren();
    el('wbTemplateTicket').value=''; el('wbTemplateResult').textContent='Carregue as tarefas do próximo chamado.';
    el('wbTemplateReview').disabled=true; el('wbTemplateApply').disabled=true;
    el('wbTemplateAfterMode').value='tasks'; el('wbTemplateAfterSolution').value='';
    el('wbExistingBanner')?.remove();
  };
  el('wbTemplateTasks').insertAdjacentHTML('beforebegin','<p class="small"><strong>1. Selecione as tarefas verificadas. 2. Associe os prints e marque a conclusão real.</strong> Incluir uma tarefa na atualização não marca a verificação como realizada. O resultado de cada tarefa será confirmado antes de fechar o chamado.</p>');
  el('wbTemplateResult').insertAdjacentHTML('beforebegin','<details open><summary>3. Resultado após registrar tarefas e evidências</summary><label>Resultado<select id="wbTemplateAfterMode"><option value="tasks">Somente atualizar tarefas</option><option value="solve">Atualizar tarefas e solucionar</option><option value="close">Atualizar tarefas e fechar</option></select></label><label>Solução confirmada<textarea id="wbTemplateAfterSolution" placeholder="Resultado das verificações realmente realizadas"></textarea></label></details>');
  ['wbTemplateAfterMode','wbTemplateAfterSolution'].forEach(id=>el(id).addEventListener('input',invalidateTemplate));
  function statusName(n){return ({1:'Novo',2:'Atribuído',3:'Planejado',4:'Pendente',5:'Solucionado',6:'Fechado'})[n]||'Sem status';}
  function filterSelect(select){
    const input=document.createElement('input');input.type='search';input.placeholder='Digite para localizar a empresa';input.setAttribute('aria-label','Pesquisar empresa');select.before(input);
    const apply=()=>{const q=input.value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();[...select.options].forEach(o=>o.hidden=!!o.value&&!o.text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().includes(q));};
    input.oninput=apply;new MutationObserver(apply).observe(select,{childList:true});
  }
  filterSelect(el('wbRefEntity'));
  async function loadEntities(){try{const d=await request('/api/workbench/entities');const prior=el('wbRefEntity').value;el('wbRefEntity').innerHTML='<option value="">Selecione uma empresa</option>'+d.items.map(x=>`<option value="${x.id}">${safe(x.name)}</option>`).join('');el('wbRefEntity').value=prior;}catch(e){el('wbRefNote').textContent='Não foi possível listar empresas. Informe um chamado para usar sua empresa. '+e.message;}}
  async function openTicketIn(id,destination){
    if(bridgeDraftIsDirty()&&!confirm('Trocar de chamado e limpar o rascunho atual?'))return;
    el('ticketId').value=id;await loadTicket();if(!currentTicket||Number(currentTicket.id)!==Number(id)){el('wbAdminCurrent').textContent='Não foi possível carregar o chamado. Confira o número e a conexão.';return;}route(destination);
  }
  function openContact(a){
    const ticket=state.items.find(x=>x.id===+a.dataset.contact);if(!ticket)return;
    try { if(a.dataset.editContact)ContactEditor.open(a,ticket);else ContactEditor.direct(a,ticket); } catch(e){el('wbStatus').textContent=e.message;}
  }
  async function copyText(value){
    const text=String(value||'');
    if(!text)throw Error('Nada para copiar.');
    if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);return;}
    const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();
    if(!document.execCommand('copy')){area.remove();throw Error('Não foi possível copiar automaticamente.');}
    area.remove();
  }
  function flashCopy(button,label='Copiado ✓'){
    const old=button.textContent;button.textContent=label;button.classList.add('is-copied');setTimeout(()=>{button.textContent=old;button.classList.remove('is-copied');},1300);
  }
  const nav=document.querySelector('.workspace-nav');
  nav.insertAdjacentHTML('beforeend','<a href="#referencias"><span class="nav-index">↗</span><span><strong>Base da empresa</strong><small>Pesquisa e recorrências</small></span></a>');
  nav.insertBefore(nav.querySelector('[href="#referencias"]'),nav.querySelector('[href="#bridge-ia"]'));
  const icons={central:'M3 10l9-7 9 7v10H3z M9 20v-7h6v7',operacao:'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',referencias:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6','bridge-ia':'M3 5h18v12H9l-5 4v-4H3z M7 9h10 M7 13h6',administracao:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6'};
  icons['minha-fila']='M8 6h13 M8 12h13 M8 18h13 M3 6h1 M3 12h1 M3 18h1';
  icons.encerrados='M5 3h14v18H5z M8 12l3 3 5-6';
  icons.proativos='M12 4v16 M4 12h16';
  nav.querySelectorAll('a').forEach(a=>{a.querySelector('.nav-index').innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[a.hash.slice(1)]}"></path></svg>`;});
  function route(id) {
    if(id==='evidencias')id='operacao';
    const valid=['proativos','central','minha-fila','encerrados','operacao','evidencias','bridge-ia','administracao','referencias'];
    if (!valid.includes(id)) return;
    document.querySelectorAll('#workspace > .workspace-section').forEach(s=>s.classList.toggle('wb-off',s.id!==id));
    nav.querySelectorAll('a').forEach(a=>{a.classList.toggle('active',a.hash==='#'+id);if(a.hash==='#'+id)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    if(id==='administracao' && !el('wbAdminRecent').children.length)setTimeout(()=>el('wbAdminRefresh').click(),0);
    if(id==='referencias' && el('wbRefEntity').options.length===1)loadEntities();
    history.replaceState(null,'','#'+id);
    window.scrollTo({top:0,behavior:'instant'});
    window.MyTickets?.activate(id);
    if(id==='proativos')window.Proactive?.refresh();
  }
  nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();route(a.hash.slice(1));}));
  window.addEventListener('hashchange',()=>route(location.hash.slice(1)));
  route(['proativos','central','minha-fila','encerrados','operacao','evidencias','bridge-ia','administracao','referencias'].includes(location.hash.slice(1))?location.hash.slice(1):'central');
  function render() {
    const all=state.items||[], recent=all.filter(x=>!x.baseline), stale=all.filter(x=>x.stale);
    el('wbMetrics').innerHTML=[[recent.length,'Novas atribuições','Detectadas após a primeira consulta','new'],[stale.length,'Precisam de retorno','Sem atualização sua no período','stale'],[all.length,'Em acompanhamento','Atribuídos e ainda ativos','active']].map(([n,t,s,tone])=>`<div class="wb-metric" data-tone="${tone}"><div class="wb-metric-number">${n}</div><div><strong>${t}</strong><span>${s}</span></div></div>`).join('');
    document.querySelectorAll('[data-wb-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.wbFilter===filter)));
    const q=el('wbQuery').value.toLocaleLowerCase(), company=el('wbEntity').value;
    let rows=(filter==='new'?recent:filter==='stale'?stale:all).filter(x=>(!company||String(x.entity_id)===company)&&`${x.id} ${x.title} ${x.entity} ${x.category} ${x.description||''}`.toLocaleLowerCase().includes(q));
    rows.sort((a,b)=>el('wbSort').value==='new'?b.seen_at-a.seen_at:el('wbSort').value==='priority'?b.priority-a.priority:b.stale_hours-a.stale_hours);
    const decodeDescription=value=>{const box=document.createElement('textarea');box.innerHTML=String(value||'');return box.value.replace(/\s+(\d+\)\s+)/g,'\n$1').replace(/\s*>\s*/g,' › ').replace(/[ \t]+/g,' ').trim();};
    const displayContactName=name=>{const words=String(name||'').trim().replace(/\s+/g,' ').split(' ').filter(Boolean);if(!words.length)return 'Contato';if(words.length%2===0){const half=words.length/2;if(words.slice(0,half).join(' ').toLocaleLowerCase()===words.slice(half).join(' ').toLocaleLowerCase())words.splice(half);}const joined=words.join(' ');return joined.length<=24?joined:(words.length>2?`${words[0]} ${words[words.length-1]}`:joined.slice(0,24));};
    const compactEntity=value=>{const parts=String(value||'').split(/\s*(?:>|›)\s*/).map(x=>x.trim()).filter(Boolean);if(!parts.length)return 'Entidade não informada';const short=parts.slice(-2).join(' · ');return short.length>72?parts[parts.length-1]:short;};
    const contactButton=(x,c,compact=false)=>c?.whatsapp?`<button type="button" class="wb-contact${compact?' quick':''}" data-wa="${safe(c.whatsapp)}" data-contact="${x.id}" data-phone="${safe(c.phone)}" data-name="${safe(c.name)}" title="Abrir conversa com ${safe(c.phone)}">Abrir conversa · ${safe(displayContactName(c.name))}</button>${compact?'':`<button type="button" class="secondary compact" data-edit-contact="true" data-wa="${safe(c.whatsapp)}" data-contact="${x.id}" data-phone="${safe(c.phone)}" data-name="${safe(c.name)}">Editar mensagem</button>`}`:`<span class="wb-contact-missing${compact?' quick':''}">${c?`${safe(displayContactName(c.name))} · sem telefone`:'Sem contato'}</span>`;
    const contactLabel=c=>c.phone_source==='descricao'?'Descrição · contato principal':c.priority==='secundario'?'Solicitante · contato secundário':'Solicitante · contato principal';
    const contactButtons=x=>(x.contacts||[]).map(c=>`<div class="wb-contact-entry"><small>${contactLabel(c)}</small><span>${safe(c.phone||'Telefone não informado')}</span>${contactButton(x,c)}</div>`).join('')||'<span class="wb-contact-missing">Sem contato cadastrado</span>';
    const primaryContact=x=>{const c=(x.contacts||[])[0];return `<div class="wb-primary-contact"><small>${c?contactLabel(c):'Contato do atendimento'}</small>${c?.phone?`<span>${safe(c.phone)}</span>`:''}${contactButton(x,c,true)}${c?.ambiguous?`<small class="contact-warning">${safe(c.contact_issue||'Confira o destinatário antes de enviar.')}</small>`:''}</div>`;};
    const quickCopyMenu=x=>`<details class="wb-copy-menu"><summary title="Copiar mensagem pronta">Mensagem <span aria-hidden="true">⌄</span></summary><div class="wb-copy-popover"><button type="button" data-copy-message="first" data-ticket="${x.id}">Copiar 1º contato</button><button type="button" data-copy-message="continuation" data-ticket="${x.id}">Copiar continuidade</button></div></details>`;
    el('wbRows').innerHTML=rows.length?rows.map(x=>{const open=expanded.has(x.id);const description=decodeDescription(x.description)||'O chamado não possui descrição textual disponível para prévia.';return `<article class="wb-ticket-card ${x.stale?'stale':''}${open?' is-open':''}" data-ticket="${x.id}">
      <div class="wb-row">
        <label class="wb-ticket-select" title="Selecionar #${x.id} para conclusão em lote"><input type="checkbox" data-select="${x.id}" aria-label="Selecionar chamado ${x.id}" ${selected.has(x.id)?'checked':''}><span aria-hidden="true"></span></label>
        <div class="wb-row-main">
          <div class="wb-title-line"><h3><a href="${safe(x.url)}" target="_blank" rel="noopener" title="Abrir chamado #${x.id} diretamente no GLPI"><span class="wb-ticket-id">#${x.id}</span><span class="wb-ticket-title">${safe(x.title)}</span></a></h3></div>
          <div class="wb-row-meta"><span class="wb-company-name" title="${safe(x.entity)}">${safe(compactEntity(x.entity))}</span><span class="wb-category-chip">${safe(x.category||'Sem categoria')}</span></div>
          <div class="wb-row-status"><span>${x.baseline?'Já estava na sua fila':`Atribuído há ${age(x.seen_at)}`}</span><span class="wb-t01-state ${String(x.initial||'').toLowerCase().includes('criad')?'ok':'pending'}">T01 · ${safe(x.initial||'—')}</span></div>
        </div>
        <div class="wb-row-activity"><span class="wb-activity-label">Minha atualização</span><strong>${x.last_own_update?`há ${age(x.last_own_update)}`:'Sem registro'}</strong><span class="wb-activity-general">Atividade geral<br>${safe(x.last_any_update||'—')}</span></div>
        <div class="wb-row-quick"><div class="wb-quick-primary">${primaryContact(x)}<button type="button" class="white-action wb-formalize" data-open="${x.id}"><svg class="action-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h10l3 3v15H4V3h3z M8 10h8 M8 14h8 M8 18h5"/></svg>Formalizar</button></div><div class="wb-quick-links"><button type="button" class="wb-copy-link" data-resume="${x.id}" ${(x.contacts||[]).some(c=>c.priority==='principal'&&c.ambiguous)?'disabled':''} title="Enviar agora a mensagem de continuidade pelo WhatsApp">Enviar retorno</button><button type="button" class="wb-copy-link" data-resume-edit="${x.id}" ${(x.contacts||[]).some(c=>c.priority==='principal'&&c.ambiguous)?'disabled':''} title="Personalizar a mensagem de continuidade antes do envio">Editar retorno</button>${quickCopyMenu(x)}<button type="button" class="wb-copy-link" data-copy-link="${x.id}" title="Copiar link do chamado">⧉ Link</button><button type="button" class="wb-inspect-toggle" data-inspect="${x.id}" aria-expanded="${open}"><span>${open?'Ocultar inspeção':'Inspecionar'}</span><strong aria-hidden="true">⌄</strong></button><a class="wb-compact-glpi" href="${safe(x.url)}" target="_blank" rel="noopener">Abrir GLPI ↗</a></div></div>
      </div>
      <div class="wb-ticket-inspection${open?'':' hidden'}" data-inspection="${x.id}">
        <div class="wb-ticket-brief"><div class="section-kicker">SOLICITAÇÃO INICIAL</div><p>${safe(description)}</p><div class="wb-ticket-facts"><span>Status <strong>${safe(statusName(+x.status))}</strong></span><span>Prioridade <strong>${safe(x.priority||'—')}</strong></span><span>Categoria <strong>${safe(x.category||'Sem categoria')}</strong></span><span>T01 <strong>${safe(x.initial||'—')}</strong></span></div></div>
        <div class="wb-ticket-contact-context"><div class="section-kicker">CONTATOS</div><div class="wb-contact-stack">${contactButtons(x)}</div><p class="micro">Abrir conversa abre o WhatsApp Web. Enviar retorno envia a mensagem padrão diretamente.</p></div>
        <div class="wb-inspection-actions"><button class="secondary" data-ref="${x.id}">Pesquisar recorrências</button><a class="wb-direct-link" href="${safe(x.url)}" target="_blank" rel="noopener">Abrir no GLPI ↗</a></div>
      </div>
    </article>`}).join(''):`<div class="wb-empty">${state.errors?.length?'Não foi possível ler os chamados desta consulta. Veja as falhas acima.':'Nenhum chamado neste filtro. Consulte Minha fila para ver os atribuídos da base inicial.'}</div>`;
    el('wbRows').querySelectorAll('[data-inspect]').forEach(button=>button.onclick=()=>{const id=+button.dataset.inspect;const card=button.closest('.wb-ticket-card');const panel=card?.querySelector('[data-inspection]');const willOpen=!expanded.has(id);willOpen?expanded.add(id):expanded.delete(id);card?.classList.toggle('is-open',willOpen);panel?.classList.toggle('hidden',!willOpen);button.setAttribute('aria-expanded',String(willOpen));button.querySelector('span').textContent=willOpen?'Ocultar inspeção':'Inspecionar';});
    el('wbRows').querySelectorAll('[data-select]').forEach(b=>{b.onchange=()=>{b.checked?selected.add(+b.dataset.select):selected.delete(+b.dataset.select);renderBatch();};});
    el('wbRows').querySelectorAll('[data-open]').forEach(b=>b.onclick=async()=>{if(bridgeDraftIsDirty()&&!confirm('Trocar de chamado e limpar o rascunho atual?'))return;el('ticketId').value=b.dataset.open;await loadTicket();route('operacao');});
    el('wbRows').querySelectorAll('[data-ref]').forEach(b=>b.onclick=()=>{el('wbRefTicket').value=b.dataset.ref;el('wbTemplateTicket').value=b.dataset.ref;route('referencias');el('wbFind').click();});
    el('wbRows').querySelectorAll('[data-resume]').forEach(button=>button.onclick=()=>WhatsAppContact.resume(state.items.find(x=>x.id===+button.dataset.resume),button));
    el('wbRows').querySelectorAll('[data-resume-edit]').forEach(button=>button.onclick=()=>WhatsAppContact.edit(state.items.find(x=>x.id===+button.dataset.resumeEdit),button));
    el('wbRows').querySelectorAll('[data-contact]').forEach(a=>a.onclick=e=>{e.preventDefault();openContact(a);});
    el('wbRows').querySelectorAll('[data-copy-message]').forEach(button=>button.onclick=async e=>{e.preventDefault();const ticket=state.items.find(x=>x.id===+button.dataset.ticket);if(!ticket)return;try{const contact=(ticket.contacts||[])[0];const text=ContactEditor.messageFor(ticket,button.dataset.copyMessage,contact?.name||'');await copyText(text);flashCopy(button,button.dataset.copyMessage==='continuation'?'Continuidade copiada ✓':'Mensagem copiada ✓');button.closest('details')?.removeAttribute('open');}catch(error){el('wbStatus').textContent=error.message;}});
    el('wbRows').querySelectorAll('[data-copy-link]').forEach(button=>button.onclick=async e=>{e.preventDefault();const ticket=state.items.find(x=>x.id===+button.dataset.copyLink);if(!ticket)return;try{await copyText(ticket.url);flashCopy(button,'Link copiado ✓');button.closest('details')?.removeAttribute('open');}catch(error){el('wbStatus').textContent=error.message;}});
    renderBatch();
  }
  function renderBatch(){el('wbBatch').classList.toggle('hidden',!selected.size);el('wbSelected').textContent=`${selected.size} chamado(s) selecionado(s)`;}
  function accept(data, fill=false){
    state=data; const ids=new Set((state.items||[]).map(x=>x.id));selected=new Set([...selected].filter(id=>ids.has(id)));
    const prior=el('wbEntity').value;
    const entities=new Map((state.items||[]).map(x=>[x.entity_id,x.entity]));
    el('wbEntity').innerHTML='<option value="">Todas</option>'+[...entities].map(([id,name])=>`<option value="${id}">${safe(name)}</option>`).join('');el('wbEntity').value=prior;
    if(fill&&data.settings){const s=data.settings;el('wbEnabled').checked=s.enabled;el('wbAuto').checked=s.auto_initial;el('wbInitialTemplate').value=s.initial_reply_template||'';el('wbHours').value=s.stale_hours;el('wbInterval').value=s.interval;el('wbTimezone').value=s.timezone;el('wbCountry').value=s.country_code;}
    if(data.settings){ContactEditor.accept(data.settings,fill);el('wbInitialToggle').disabled=false;el('wbInitialToggle').textContent=data.settings.auto_initial?'Pausar criação de T01':'Retomar criação de T01';}
    const autoNotice=el('wbAutoInitialNotice');
    if(autoNotice) autoNotice.classList.toggle('hidden', data.settings?.auto_initial !== false);
    const attempt=data.last_attempt&&!data.last_sync?` Tentativa em ${date(data.last_attempt)}.`:'';
    el('wbStatus').textContent=`${data.last_sync?'Última consulta: '+date(data.last_sync):'A fila ainda não foi carregada.'}${attempt}${data.settings?.enabled?' · Consulta automática ativa':' · Consulta automática desativada'}${data.monitor_error?' · Falha: '+data.monitor_error:''}${data.warnings?.length?' · '+data.warnings.length+' dados complementares indisponíveis (chamados preservados).':''}${data.errors?.length?' · Falhas: '+data.errors.map(e=>`#${e.ticket_id}: ${e.error}`).join('; '):''}`;render();
  }
  document.querySelectorAll('[data-wb-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.wbFilter;render();});
  ['wbQuery','wbEntity','wbSort'].forEach(id=>el(id).oninput=render);
  el('wbGoToQueue').onclick=()=>route('minha-fila');
  el('wbClear').onclick=()=>{selected.clear();render();};
  run('wbSync',async()=>{el('wbStatus').textContent='Consultando atribuições e histórico no GLPI…';accept(await request('/api/workbench/sync',{method:'POST'}));});
  document.querySelectorAll('[data-t01-token]').forEach(button=>button.onclick=()=>{
    const input=el('wbInitialTemplate');input.focus();input.setRangeText('{'+button.dataset.t01Token+'}',input.selectionStart,input.selectionEnd,'end');input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  run('wbInitialToggle',async()=>{
    const enabled=!state.settings.auto_initial;
    const result=await request('/api/workbench/settings',{...json({auto_initial:enabled}),method:'PUT'});
    state.settings=result.settings;el('wbAuto').checked=enabled;
    el('wbInitialToggle').textContent=enabled?'Pausar criação de T01':'Retomar criação de T01';
    el('wbAutoInitialNotice').classList.toggle('hidden',enabled);
    el('wbInitialStatus').textContent=enabled?'Criação retomada; atribuições pendentes elegíveis podem receber T01.':'Criação pausada. Respostas já criadas e confirmações de entrega são preservadas.';
  },'wbInitialStatus');
  run('wbSave',async()=>{const payload={enabled:el('wbEnabled').checked,auto_initial:el('wbAuto').checked,initial_reply_template:el('wbInitialTemplate').value,stale_hours:+el('wbHours').value,interval:+el('wbInterval').value,timezone:el('wbTimezone').value,country_code:el('wbCountry').value,...ContactEditor.settings()};await request('/api/workbench/settings',{...json(payload),method:'PUT'});ContactEditor.accept(payload,true);el('wbSettingsStatus').textContent='Preferências salvas. A mensagem será usada nos próximos contatos.';},'wbSettingsStatus');
  async function openSolutions(items){
    solutionPlan=null;el('wbApplySolutions').disabled=true;el('wbOk').checked=false;el('wbSolutionResult').textContent='';
    el('wbSolutions').innerHTML=items.map(x=>`<label>#${x.id} · ${safe(x.title)}<textarea data-solution="${x.id}" placeholder="Descreva a solução efetivamente aplicada e a validação realizada."></textarea></label>`).join('');
    el('wbDialog').showModal();
  }
  el('wbPrepare').onclick=()=>{if(selected.size>20){el('wbStatus').textContent='Selecione até 20 chamados por lote.';return;}openSolutions((state.items||[]).filter(x=>selected.has(x.id)));};
  window.prepareWorkbenchSolutions=openSolutions;
  window.openWorkbenchTicket=openTicketIn;
  el('wbFinishCurrent').onclick=async()=>{
    if(!currentTicket){setWorkflowStatus('Carregue um chamado antes de concluir.','error');return;}
    if(el('closure').value.trim()){
      await runDryRun({manual:true});
      if(!currentPlan){setWorkflowStatus('Revise o texto e as evidências antes de concluir.','error');return;}
      if(currentPlan.has_actionable_operations){
        el('wbAfterMode').value='close';
        el('wbAfterMode').closest('details')?.setAttribute('open','');
        el('wbAfterSolution').focus();
        el('executeBtn').textContent='Registrar tarefas e fechar';
        setWorkflowStatus('Preencha a solução e clique em Registrar tarefas e fechar. O tempo e os anexos serão registrados antes da conclusão.','muted');
        return;
      }
    }
    openSolutions([currentTicket]);
  };
  el('wbAfterMode').addEventListener('change',()=>{el('executeBtn').textContent=el('wbAfterMode').value==='close'?'Registrar tarefas e fechar':el('wbAfterMode').value==='solve'?'Registrar tarefas e solucionar':'Aplicar no GLPI';});
  el('wbDialog').addEventListener('input',()=>{solutionPlan=null;el('wbApplySolutions').disabled=true;});
  run('wbReviewSolutions',async()=>{
    if(!el('wbOk').checked)throw Error('Confirme que revisou os atendimentos.');
    const items=[...document.querySelectorAll('[data-solution]')].map(x=>({ticket_id:+x.dataset.solution,content:x.value}));
    solutionPlan=await request('/api/workbench/solution/plan',json({items,target:el('wbTarget').value}));
    el('wbSolutionResult').textContent=solutionPlan.items.map(x=>`#${x.ticket_id} · ${x.title}\n${x.status===5?'Já solucionado; preservará a solução existente.':x.content}\nTempo registrado em tarefas: ${x.recorded_seconds||0} s.${!x.recorded_seconds?' Se o GLPI exigir duração, registre o tempo real antes de aplicar.':''}\nDestino: ${solutionPlan.target==='close'?'Fechado':'Solucionado'}`).join('\n\n');el('wbApplySolutions').disabled=false;
  },'wbSolutionResult');
  el('wbApplySolutions').onclick=async()=>{
    if(!solutionPlan)return;const p=solutionPlan;solutionPlan=null;el('wbApplySolutions').disabled=true;el('wbReviewSolutions').disabled=true;
    try{const result=await request('/api/workbench/solution/apply',json({plan_id:p.plan_id}));el('wbSolutionResult').textContent=JSON.stringify(result,null,2);if(result.ok)selected.clear();}catch(e){el('wbSolutionResult').textContent=e.message+'\nConsulte o GLPI antes de repetir.';}finally{el('wbReviewSolutions').disabled=false;}
  };
  run('wbHistoryBtn',async()=>{const data=await request('/api/workbench/history');el('wbHistory').innerHTML=data.items.map(x=>`<article class="activity-row"><div><strong>${x.target==='existing_tasks'?'Tarefas e anexos':x.target==='close'?'Fechamento':'Solução'} ${x.ticket_id?'· chamado #'+x.ticket_id:''}</strong><p class="muted">${date(x.at)}</p>${(x.results||[]).map(r=>`<p>${r.ticket_id?'Chamado #'+r.ticket_id+' · ':''}${r.task_id?'Tarefa #'+r.task_id+' · ':''}${r.ok?'Concluído':'Falha: '+safe(r.error||'Verifique no GLPI')}</p>`).join('')}</div></article>`).join('')||'<p>Ainda não há aplicações registradas.</p>';},'wbHistory');
  el('wbStatus').insertAdjacentHTML('afterend','<details><summary>Diagnosticar falha de consulta</summary><label>Chamado com erro<input id="wbDiagnosticTicket" type="number" min="1"></label><button id="wbDiagnosticRun" class="secondary">Verificar acesso aos dados</button><pre id="wbDiagnosticResult" style="white-space:pre-wrap;max-height:260px;overflow:auto"></pre></details>');
  run('wbDiagnosticRun',async()=>{const id=Number(el('wbDiagnosticTicket').value);if(!Number.isSafeInteger(id)||id<=0)throw Error('Informe o número do chamado');el('wbDiagnosticResult').textContent=JSON.stringify(await request('/api/workbench/diagnostics/'+id),null,2);},'wbDiagnosticResult');
  let searchRevision=0, refNext=null, refRows=new Map(), refScanned=0, refCategories=new Map(), refAppend=false, refController=null;
  el('wbRefs').insertAdjacentHTML('afterend','<button id="wbRefMore" type="button" class="secondary" hidden>Carregar mais resultados</button>');
  el('wbRefMore').onclick=()=>{refAppend=true;el('wbFind').click();};
  async function loadCategories(){
    const entity=el('wbRefEntity').value,ticket=el('wbRefTicket').value;
    if(entity===''&&!Number(ticket))return;
    const query=new URLSearchParams({entity_id:entity===''?-1:entity,ticket_id:ticket||0});
    try{const d=await request('/api/workbench/categories?'+query);if(el('wbRefEntity').value!==entity||el('wbRefTicket').value!==ticket)return;el('wbRefCategory').innerHTML='<option value="0">Todas as categorias</option>'+d.items.map(x=>`<option value="${x.id}">${safe(x.name)}</option>`).join('');}catch(e){if(el('wbRefEntity').value===entity&&el('wbRefTicket').value===ticket)el('wbRefNote').textContent='Categorias indisponíveis: '+e.message;}
  }
  ['wbRefTicket','wbRefEntity','wbRefQuery','wbRefStatus','wbRefCategory','wbRefDays'].forEach(id=>el(id).addEventListener('input',()=>{searchRevision++;refController?.abort();el('wbRefMore').hidden=true;}));
  el('wbRefEntity').addEventListener('change',()=>{el('wbRefTicket').value='';el('wbRefCategory').innerHTML='<option value="0">Todas as categorias</option>';loadCategories();});
  el('wbRefTicket').addEventListener('input',()=>{el('wbRefEntity').value='';el('wbRefCategory').innerHTML='<option value="0">Todas as categorias</option>';});
  el('wbRefTicket').addEventListener('change',loadCategories);
  run('wbFind',async()=>{
    const revision=searchRevision;
    const append=refAppend;refAppend=false;if(!append){refNext=0;refRows.clear();refCategories.clear();refScanned=0;}
    refController=new AbortController();
    const id=+el('wbRefTicket').value,entity=el('wbRefEntity').value;
    if(!id&&entity==='')throw Error('Selecione uma empresa ou informe um chamado.');
    el('wbRefNote').textContent='Consultando assunto, descrição e tarefas no GLPI…';
    const qs=new URLSearchParams({ticket_id:id,entity_id:entity===''?-1:entity,q:el('wbRefQuery').value,status:el('wbRefStatus').value,category:el('wbRefCategory').value,days:el('wbRefDays').value,offset:refNext||0});
    const data=await request(`/api/workbench/company-search?${qs}`,{signal:refController.signal});
    if(revision!==searchRevision){el('wbRefNote').textContent='Filtros alterados durante a busca. Pesquise novamente.';return;}
    data.items.forEach(x=>refRows.set(x.id,x));refScanned+=data.scanned;refNext=data.next_offset??null;el('wbRefMore').hidden=refNext===null;
    data.categories.forEach(x=>{const prev=refCategories.get(x.id);refCategories.set(x.id,{...x,count:(prev?.count||0)+x.count});});
    data.items=[...refRows.values()];data.categories=[...refCategories.values()];
    el('wbRefNote').textContent=`${data.items.length} resultado(s) · ${refScanned} chamados consultados. ${data.scope}${data.truncated?' Há mais chamados fora desta amostra.':''}${data.errors?.length?' '+data.errors.length+' chamado(s) com falha na consulta.':''}`;
    const prior=el('wbRefCategory').value;
    data.categories.filter(c=>c.id).forEach(c=>{if(![...el('wbRefCategory').options].some(o=>+o.value===c.id))el('wbRefCategory').insertAdjacentHTML('beforeend',`<option value="${c.id}">${safe(c.name)}</option>`);});el('wbRefCategory').value=prior;
    el('wbCategories').innerHTML='<span>Categorias mais frequentes nesta amostra:</span>'+data.categories.filter(c=>c.id).slice(0,8).map(c=>`<button data-category="${c.id}" aria-pressed="${String(c.id)===prior}">${safe(c.name)} · ${c.count}</button>`).join('');
    el('wbCategories').querySelectorAll('button').forEach(b=>b.onclick=()=>{el('wbRefCategory').value=b.dataset.category;searchRevision++;el('wbFind').click();});
    el('wbRefs').innerHTML=data.items.map(x=>`<article class="card"><a href="${safe(x.url)}" target="_blank" rel="noopener">#${x.id} · ${safe(x.title)}</a><p>${safe(x.excerpt)}</p><small>${statusName(x.status)} · atualizado em ${safe(x.date_mod)}</small><div class="actions"><button class="secondary" data-reference-open="${x.id}">Abrir no fechamento</button></div></article>`).join('')||'<div class="card"><h2>Nenhum resultado nesta consulta</h2><p>Experimente menos palavras ou amplie o período. A busca considera todos os termos digitados.</p></div>';
    el('wbRefs').querySelectorAll('[data-reference-open]').forEach(b=>b.onclick=()=>openTicketIn(b.dataset.referenceOpen,'operacao'));
  },'wbRefNote');
  function updateBackupSummary(){
    const rows=[...el('wbTemplateTasks').querySelectorAll('[data-template]')];
    const total=rows.length;
    const done=rows.filter(row=>+row.dataset.state===2 || row.querySelector('[data-complete]')?.checked).length;
    const selected=rows.filter(row=>row.querySelector('[data-use]')?.checked).length;
    const evidence=rows.reduce((n,row)=>n+(row.querySelector('input[type=file]')?.files?.length||0)+(row.querySelector('[data-received]')?.selectedOptions?.length||0),0);
    const pct=total?Math.round(done/total*100):0;
    if(el('wbBackupSummary'))el('wbBackupSummary').textContent=total?`${done}/${total} conferências · ${selected} selecionada(s) · ${evidence} print(s)`:'Nenhuma tarefa pronta';
    if(el('wbBackupSelection'))el('wbBackupSelection').textContent=selected?`${selected} tarefa(s) serão revisadas · ${evidence} evidência(s) associadas`:'Nenhuma tarefa selecionada.';
    const ring=el('wbBackupProgress');
    if(ring){ring.style.setProperty('--backup-progress',`${pct}%`);ring.querySelector('strong').textContent=total?`${done}/${total}`:'—';}
    rows.forEach(row=>{const isDone=+row.dataset.state===2 || row.querySelector('[data-complete]')?.checked;row.classList.toggle('done',!!isDone);row.classList.toggle('pending',!isDone);row.classList.toggle('selected',!!row.querySelector('[data-use]')?.checked);const chip=row.querySelector('.backup-task-state');if(chip){chip.className=`backup-task-state ${isDone?'done':'pending'}`;chip.textContent=isDone?'Concluída':'Pendente';}});
  }
  function invalidateTemplate(){templateRevision++;templatePlan=null;templateAfterAction=null;el('wbTemplateApply').disabled=true;el('wbTemplateResult').textContent='Alterado. Gere nova revisão.';updateBackupSummary();}
  run('wbTemplateLoad',async()=>{
    const id=+el('wbTemplateTicket').value;if(!id)throw Error('Informe o chamado.');
    const loadRevision=++templateLoadRevision;
    invalidateTemplate();el('wbTemplateReview').disabled=true;
    const data=await request('/api/templates/'+id);
    if(loadRevision!==templateLoadRevision || +el('wbTemplateTicket').value!==id)return;
    templateTicket=id;invalidateTemplate();
    el('wbTemplateTasks').innerHTML=data.tasks.map(t=>{
      const existing=(t.documents||[]);
      const existingHtml=existing.length?`<details class="backup-existing-evidence"><summary>${existing.length} evidência(s) já vinculada(s) no GLPI</summary><div>${existing.slice(0,8).map(d=>`<span title="Documento #${Number(d.id||0)}">📎 ${safe(d.name||d.filename||('Documento '+d.id))}</span>`).join('')}${existing.length>8?`<small>+${existing.length-8} documento(s)</small>`:''}</div></details>`:'<span class="backup-no-existing">Nenhuma evidência já vinculada</span>';
      return `<article class="backup-task-card ${+t.state===2?'done':'pending'}" data-template="${t.id}" data-state="${Number(t.state||0)}"><div class="backup-task-top"><label class="check"><input type="checkbox" data-use> <strong>Tarefa #${t.id}</strong></label><span>${Math.round(Number(t.actiontime||0)/60)} min registrados</span><span class="backup-task-state ${+t.state===2?'done':'pending'}">${+t.state===2?'Concluída':'Pendente'}</span></div><div class="backup-task-fields"><label>Tempo real (min)<input type="number" data-duration min="0" step="any" value="${Number(t.actiontime||0)/60}"></label><label class="check backup-complete"><input type="checkbox" data-complete ${+t.state===2?'checked disabled':''}> ${+t.state===2?'Já concluída':'Marcar concluída'}</label><textarea aria-label="Texto da tarefa ${t.id}">${safe(t.text)}</textarea></div><div class="backup-evidence-row">${existingHtml}<label>📎 Novas evidências<input type="file" multiple accept="image/png,image/jpeg,image/webp"></label><div class="wb-thumbs"></div></div></article>`;
    }).join('')||'<p>Este chamado não tem tarefas prontas.</p>';
    el('wbTemplateTasks').querySelectorAll('[data-template]').forEach(row=>{
      const complete=row.querySelector('[data-complete]');
      if(complete)complete.onchange=()=>{row.querySelector('[data-use]').checked=true;invalidateTemplate();};
      const use=row.querySelector('[data-use]');if(use)use.onchange=()=>{invalidateTemplate();};
      if (!files.length) return;
      const wrap=row.querySelector('.backup-evidence-row');
      const label=document.createElement('label');label.textContent='Prints recebidos do Bridge';
      const select=document.createElement('select');select.multiple=true;select.dataset.received='true';
      files.forEach(entry=>{const option=document.createElement('option');option.value=entry.id;option.textContent=entry.file.name;select.append(option);});
      select.onchange=()=>{row.querySelector('[data-use]').checked=true;invalidateTemplate();};label.append(select);wrap.append(label);
    });
    el('wbTemplateTasks').querySelectorAll('input:not([type=file]),textarea').forEach(x=>x.addEventListener('input',invalidateTemplate));
    el('wbTemplateTasks').querySelectorAll('input[type=file]').forEach(x=>x.onchange=()=>{
      const row=x.closest('[data-template]');row.querySelector('[data-use]').checked=true;const root=row.querySelector('.wb-thumbs');root.querySelectorAll('img').forEach(i=>URL.revokeObjectURL(i.src));root.innerHTML='';
      [...x.files].forEach((f,i)=>{const figure=document.createElement('figure'),img=document.createElement('img'),cap=document.createElement('figcaption');img.src=URL.createObjectURL(f);img.alt=f.name;cap.textContent=`${i+1}. ${f.name}`;figure.append(img,cap);root.append(figure);});invalidateTemplate();
    });
    updateBackupSummary();
    el('wbTemplateReview').disabled=!data.tasks.length;el('wbTemplateResult').textContent=data.suggested?'Conferência de backup detectada. Selecione somente o que foi conferido e associe as evidências correspondentes.':'Tarefas existentes carregadas para continuidade.';
  },'wbTemplateResult');
  run('wbTemplateReview',async()=>{
    if(!templateTicket || +el('wbTemplateTicket').value!==templateTicket)throw Error('O número mudou. Recarregue as tarefas antes de revisar.');
    const reviewingRevision=templateRevision;
    const after={target:el('wbTemplateAfterMode').value,content:el('wbTemplateAfterSolution').value.trim()};
    if(after.target!=='tasks' && after.content.length<10)throw Error('Descreva o resultado confirmado antes de concluir o chamado.');
    templateFiles=[];const edits=[];
    el('wbTemplateTasks').querySelectorAll('[data-template]').forEach(row=>{if(!row.querySelector('[data-use]').checked)return;const indexes=[];[...row.querySelector('[type=file]').files, ...[...(row.querySelector('[data-received]')?.selectedOptions||[])].map(o=>fileEntryById(o.value)?.file).filter(Boolean)].forEach(f=>{indexes.push(templateFiles.length);templateFiles.push(f);});edits.push({task_id:+row.dataset.template,text:row.querySelector('textarea').value,actiontime:Math.round(Number(row.querySelector('[data-duration]').value)*60),files:indexes,complete:row.querySelector('[data-complete]').checked});});
    const fd=new FormData();fd.append('ticket_id',templateTicket);fd.append('edits',JSON.stringify(edits));templateFiles.forEach(f=>fd.append('files',f));
    const reviewed=await request('/api/templates/plan',{method:'POST',body:fd});
    if(reviewingRevision!==templateRevision)throw Error('As tarefas foram alteradas durante a revisão. Revise novamente.');
    templatePlan=reviewed;
    templateAfterAction=after;
    el('wbTemplateResult').textContent=templatePlan.rows.map(r=>`Tarefa #${r.task_id}: ${r.edited?'texto editado':'texto original preservado'}; ${r.complete?'marcar como CONCLUÍDA após validar anexos':'preservar estado'}; tempo total: ${r.actiontime===null||r.actiontime===undefined?'preservado':r.actiontime+' s'}.\n${r.text}\nPrints: ${r.files.map(i=>`${i+1}. ${templatePlan.files[i].name}`).join(', ')||'nenhum'}`).join('\n\n');el('wbTemplateApply').disabled=false;
    el('wbTemplateResult').textContent+=`\n\nDepois: ${after.target==='tasks'?'somente tarefas':after.target==='solve'?'solucionar':'fechar'}\n${after.target==='tasks'?'':after.content}`;
  },'wbTemplateResult');
  el('wbTemplateApply').onclick=async()=>{
    if(!templatePlan)return;const p=templatePlan,after=templateAfterAction;templatePlan=null;templateAfterAction=null;el('wbTemplateApply').disabled=true;el('wbTemplateReview').disabled=true;
    try{const fd=new FormData();fd.append('plan_id',p.id);templateFiles.forEach(f=>fd.append('files',f));const r=await request('/api/templates/apply',{method:'POST',body:fd});el('wbTemplateResult').textContent=JSON.stringify(r,null,2);if(r.ok&&after?.target!=='tasks'&&after){try{await window.finishAfterFormalization(p.ticket_id,after.content,after.target);el('wbTemplateResult').textContent+='\nConclusão do chamado confirmada.';}catch(e){el('wbTemplateResult').textContent+='\nTarefas aplicadas; chamado não concluído: '+e.message;}}}
    catch(e){el('wbTemplateResult').textContent=e.message+'\nConfira as tarefas no GLPI antes de repetir.';}finally{el('wbTemplateReview').disabled=false;}
  };
  window.fetchBridgeEvidence=async packet=>{
    const fetched=[];
    for(const img of packet.images||[]){const r=await fetch(`/api/bridge/images/${packet.id}/${encodeURIComponent(img.id)}`);if(!r.ok)throw Error('Não foi possível importar o print '+img.id);const blob=await r.blob();const file=new File([blob],img.name,{type:blob.type,lastModified:0});file.bridgeEvidenceId=img.id;file.bridgeTicketId=Number(packet.ticket_id);fetched.push(file);}
    return fetched;
  };
  window.importBridgeEvidence=async packet=>{
    const fetched=await window.fetchBridgeEvidence(packet);
    if(fetched.length)addFiles(fetched);
    route('operacao');
  };
  window.finishAfterFormalization = async (ticket_id,content,target) => {
    const p = await request('/api/workbench/solution/plan',json({items:[{ticket_id,content}],target}));
    const r = await request('/api/workbench/solution/apply',json({plan_id:p.plan_id}));
    if (!r.ok) throw Error('Tarefas aplicadas; conclusão não confirmada. '+JSON.stringify(r.results));
  };
  window.onWorkbenchTicketLoaded = ticket => {
    if(templateTicket && templateTicket!==Number(ticket.id))window.resetWorkbenchEditor();
    el('wbRefTicket').value=ticket.id;el('wbTemplateTicket').value=ticket.id;el('wbAdminTicket').value=ticket.id;el('wbAdminCurrent').textContent=`Editando #${ticket.id} · ${ticket.title}`;
    let banner=el('wbExistingBanner');
    if(!banner){banner=document.createElement('div');banner.id='wbExistingBanner';banner.className='card';el('operacao').prepend(banner);}
    banner.replaceChildren();
    const text=document.createElement('p');text.textContent=/backup/i.test(ticket.title)?'Conferência de backup detectada. Verifique as tarefas prontas antes de criar novas.':'Este chamado pode ter tarefas prontas para complementar.';
    const button=document.createElement('button');button.className='secondary';button.textContent='Editar tarefas existentes e anexar prints';button.onclick=()=>{route('operacao');el('wbTemplatePanel').open=true;el('wbTemplateLoad').click();el('wbTemplatePanel').scrollIntoView({block:'start'});};banner.append(text,button);
    if(/backup/i.test(ticket.title)&&templateTicket!==Number(ticket.id)){route('operacao');el('wbTemplatePanel').open=true;el('wbTemplateLoad').click();}
  };
  el('wbAdminRecent').insertAdjacentHTML('beforebegin','<section class="card"><div class="section-head"><h2>Últimos fechamentos recebidos</h2><button id="wbRecentPacketsBtn" class="secondary">Atualizar registros</button></div><p class="small">Retome o texto e as evidências de um pacote recebido. Isto não reabre o status do chamado no GLPI.</p><div id="wbRecentPackets" style="max-height:320px;overflow:auto"></div></section>');
  run('wbRecentPacketsBtn',async()=>{
    const d=await request('/api/bridge/inbox?limit=50');
    el('wbRecentPackets').innerHTML=d.items.map(x=>`<article class="activity-row"><div><strong>Chamado #${safe(x.ticket_id)}</strong><p class="small">Pacote #${x.id} · ${safe(x.status||'recebido')}</p></div><button class="secondary" data-resume="${x.id}">Retomar registro</button></article>`).join('')||'<p>Nenhum fechamento recebido pelo Bridge.</p>';
    el('wbRecentPackets').querySelectorAll('[data-resume]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const packet=await request('/api/bridge/handoff/'+b.dataset.resume);if(await importBridgeHandoff(packet,{force:true}))route('operacao');}catch(e){setWorkflowStatus(e.message,'error');}finally{b.disabled=false;}});
  },'wbRecentPackets');
  run('wbAdminRefresh',async()=>{
    el('wbRecentPacketsBtn').click();
    el('wbAdminNote').textContent='Consultando atividade recente…';
    const d=await request('/api/workbench/recent-edits');
    el('wbAdminNote').textContent=d.scope+` Até 20 chamados.${d.errors?.length?' Algumas consultas falharam; tente atualizar.':''}`;
    el('wbAdminRecent').innerHTML=d.items.map(t=>`<article class="activity-row"><div><a href="${safe(t.url)}" target="_blank" rel="noopener"><strong>#${t.id} · ${safe(t.title)}</strong></a><p class="muted">Atualizado em ${safe(t.date_mod)}</p>${(t.tasks||[]).map(x=>`<p><small>Chamado #${t.id} → tarefa #${x.id} · ${x.state===2?'Concluída':x.state===1?'A fazer':'Informação'}</small><br>${safe(x.text)}</p>`).join('')||'<small>Sem tarefas disponíveis.</small>'}${t.task_count>5?'<small>Mostrando as 5 tarefas mais recentes. Abra o chamado para ver todas.</small>':''}</div><button class="secondary" data-admin-open="${t.id}">Administrar</button></article>`).join('')||'<p>Nenhum chamado encontrado para este perfil.</p>';
    el('wbAdminRecent').querySelectorAll('[data-admin-open]').forEach(b=>b.onclick=()=>openTicketIn(b.dataset.adminOpen,'administracao'));
  },'wbAdminNote');
  run('wbAdminLoad',async()=>{const id=+el('wbAdminTicket').value;if(!id)throw Error('Informe o número do chamado.');await openTicketIn(id,'administracao');},'wbAdminCurrent');
  request('/api/ai/prompt').then(d=>el('wbPromptText').textContent=d.prompt||'Prompt indisponível.').catch(e=>el('wbPromptText').textContent=e.message);
  el('dropzone').tabIndex=0;el('dropzone').setAttribute('role','button');el('dropzone').setAttribute('aria-label','Anexar prints');
  el('dropzone').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el('filePicker').click();}});
  el('dropzone').addEventListener('paste',e=>{const fs=[...e.clipboardData.items].filter(i=>i.kind==='file').map(i=>i.getAsFile());if(fs.length){e.preventDefault();addFiles(fs);}});
  request('/api/workbench').then(x=>accept(x,true)).catch(e=>el('wbStatus').textContent=e.message);
  setInterval(()=>{if(!document.hidden)request('/api/workbench').then(x=>accept(x)).catch(()=>{});},30000);
})();
