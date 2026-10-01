'use strict';
(() => {
  const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const age=t=>{if(!t)return 'Sem registro';const h=Math.max(0,(Date.now()/1000-t)/3600);return h<1?`há ${Math.max(0,Math.floor(h*60))} min`:h<48?`há ${Math.floor(h)} h`:`há ${Math.floor(h/24)} dias`;};
  const date=t=>t?new Date(t*1000).toLocaleString('pt-BR'):'Sem registro';
  const status=n=>({1:'Novo',2:'Atribuído',3:'Planejado',4:'Pendente',5:'Solucionado',6:'Fechado'})[n]||'—';
  const views={};

  function make(rootId,kind){
    const root=document.getElementById(rootId);
    const closureWorkspace=kind==='closure';
    let closureView='solved';
    root.innerHTML=`
      <div class="my-queue-overview">
        <div class="my-queue-counter" aria-live="polite">
          <strong data-count>—</strong>
          <span data-count-label>${closureWorkspace?'fechamentos neste filtro':'chamados atribuídos ativos'}</span>
          <small data-count-note>${closureWorkspace?'Solução técnica vinculada ao seu usuário':'Status 1–4 · atribuídos ao seu usuário'}</small>
        </div>
        ${closureWorkspace?`<div class="closure-state-tabs" role="group" aria-label="Estado do fechamento">
          <button type="button" data-closure-view="solved" aria-pressed="true"><span>Solucionados</span><small>Aguardando aprovação/fechamento</small></button>
          <button type="button" data-closure-view="closed" aria-pressed="false"><span>Fechados</span><small>Solução aprovada</small></button>
        </div>`:''}
      </div>
      <form class="card ticket-query ticket-query-v2">
        <div class="ticket-query-grid">
          <label class="query-search">Pesquisar<input name="q" type="search" placeholder="Número, assunto, erro, tarefa ou solução…" maxlength="200"></label>
          <label>Empresa<select name="entity_id"><option value="-1">Todas as empresas</option></select></label>
          ${closureWorkspace
            ? `<label>Período<select name="days"><option value="0">Hoje</option><option value="7">7 dias</option><option value="30">30 dias</option><option value="90">90 dias</option><option value="365" selected>12 meses</option><option value="3650">10 anos</option></select></label>`
            : `<label>Status<select name="status"><option value="0">Todos atribuídos ativos</option><option value="1">Novo</option><option value="2">Atribuído</option><option value="3">Planejado</option><option value="4">Pendente</option></select></label>`}
          <div class="ticket-query-actions"><button type="submit">${closureWorkspace?'Pesquisar':'Atualizar fila'}</button><button type="button" class="secondary" data-cancel>Interromper</button></div>
        </div>
        ${closureWorkspace?'':'<label class="check queue-stale-check"><input name="stale_only" type="checkbox">Somente sem atualização minha há mais que o prazo configurado</label>'}
      </form>
      <div class="my-query-feedback"><p class="my-query-status muted small" role="status"></p></div>
      <div class="my-batch hidden"><strong></strong><button type="button" data-finish>Preparar conclusão em lote</button><button type="button" class="secondary" data-clear>Limpar seleção</button></div>
      <div class="my-ticket-list"></div>
      <div class="my-query-footer"><button type="button" class="secondary" data-more hidden>Carregar mais chamados</button></div>`;

    const form=root.querySelector('form');
    const note=root.querySelector('.my-query-status');
    const list=root.querySelector('.my-ticket-list');
    const more=root.querySelector('[data-more]');
    const batch=root.querySelector('.my-batch');
    const counter=root.querySelector('[data-count]');
    const counterLabel=root.querySelector('[data-count-label]');
    const counterNote=root.querySelector('[data-count-note]');
    let rows=new Map(),selected=new Set(),next=null,started=false,busy=false,revision=0,scanned=0,unverified=0,filters=null,controller=null,lastTotal=0;

    function activeView(){return closureWorkspace?closureView:'assigned';}
    function setCounter(){
      const q=form.elements.q.value.trim();
      const stale=!closureWorkspace&&form.elements.stale_only.checked;
      let value;
      if(!closureWorkspace&&!q&&!stale){value=String(lastTotal||rows.size);}
      else{value=String(rows.size)+(next!==null?'+':'');}
      counter.textContent=value;
      if(closureWorkspace){
        counterLabel.textContent=closureView==='solved'?'solucionados por você':'fechados com solução sua';
        counterNote.textContent=closureView==='solved'?'Status Solucionado · aguardando aprovação/fechamento':'Status Fechado · solução aprovada';
      }else{
        counterLabel.textContent='chamados atribuídos ativos';
        counterNote.textContent='Novo · Atribuído · Planejado · Pendente';
      }
    }

    function render(){
      setCounter();
      batch.classList.toggle('hidden',closureWorkspace||!selected.size);
      if(!closureWorkspace) batch.querySelector('strong').textContent=`${selected.size} selecionado(s)`;
      list.innerHTML=[...rows.values()].map(t=>{
        const closure=closureWorkspace;
        const event=t.event_at||(closureView==='solved'?t.solved_at:t.closed_at);
        const stateLabel=closureView==='solved'?'Solucionado':'Fechado';
        return `<article class="my-ticket-card${closure ? ' is-history' : ''}" data-status="${Number(t.status)||0}">
          ${closure?'':`<label class="my-ticket-select" title="Selecionar chamado #${t.id}"><input type="checkbox" data-select="${t.id}" aria-label="Selecionar chamado ${t.id}" ${selected.has(t.id)?'checked':''}><span></span></label>`}
          <div class="my-ticket-main">
            <div class="my-ticket-heading"><a href="${safe(t.url)}" target="_blank" rel="noopener"><span class="my-ticket-number">#${t.id}</span><strong>${safe(t.title)}</strong></a><span class="status-chip" data-status="${Number(t.status)||0}">${status(t.status)}</span></div>
            <div class="my-ticket-meta"><span title="${safe(t.entity)}">${safe(t.entity)}</span><span class="dot">•</span><span title="${safe(t.category)}">${safe(t.category)}</span></div>
            <p class="my-excerpt"><span>${safe(t.match_source)}:</span> ${safe(t.excerpt)||'Sem descrição disponível.'}</p>
          </div>
          <div class="my-ticket-activity">
            ${closure
              ? `<small>${stateLabel}</small><strong>${age(event)}</strong><span>${date(event)}</span><em>${safe(t.authorship||'Autoria técnica verificada')}</em><em>${closureView==='closed'&&t.approval_at?`Aprovação: ${date(t.approval_at)}`:safe(t.closure_state||'')}</em>`
              : `<small>Minha atualização</small><strong>${age(t.last_own_update)}</strong><span>Geral: ${age(t.last_any_update)}</span><em>${t.assigned_seen_at?'Atribuição '+age(t.assigned_seen_at):'Atribuição sem data local'}</em>`}
          </div>
          <div class="my-ticket-actions">${closure?'':`<button type="button" class="secondary" data-resume="${t.id}">Enviar retorno</button><small data-contact-result role="status"></small>`}<button type="button" data-open="${t.id}">${closure?'Consultar':'Abrir atendimento'}</button><a href="${safe(t.url)}" target="_blank" rel="noopener">Abrir no GLPI ↗</a></div>
        </article>`;
      }).join('')||'<div class="wb-empty">Nenhum chamado neste filtro. Ajuste os critérios e atualize a consulta.</div>';
      list.querySelectorAll('[data-select]').forEach(b=>b.onchange=()=>{b.checked?selected.add(+b.dataset.select):selected.delete(+b.dataset.select);render();});
      list.querySelectorAll('[data-resume]').forEach(b=>b.onclick=()=>globalThis.WhatsAppContact?.resume(rows.get(Number(b.dataset.resume)),b));
      list.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>window.openWorkbenchTicket(b.dataset.open,'operacao'));
    }

    async function query(append=false,background=false){
      if(busy)return;busy=true;const current=revision;
      form.querySelector('button[type=submit]').disabled=true;more.disabled=true;
      try{
        if(!append){if(!background){rows.clear();selected.clear();}scanned=0;unverified=0;lastTotal=0;filters=new URLSearchParams(new FormData(form));filters.set('view',activeView());next=0;if(!background)render();}
        if(next===null)return;
        controller=new AbortController();
        const qs=new URLSearchParams(filters);qs.set('offset',next);
        note.textContent=closureWorkspace?`Verificando ${closureView==='solved'?'soluções':'fechamentos'} e autoria técnica…`:'Consultando somente chamados ativos atribuídos ao seu usuário…';
        const response=await fetch('/api/workbench/my-tickets?'+qs,{signal:controller.signal});
        const d=await response.json();
        if(!response.ok)throw Error(typeof d.detail==='string'?d.detail:'A consulta falhou. Tente atualizar.');
        if(current!==revision){note.textContent='Filtros alterados. Clique em pesquisar para atualizar os resultados.';more.hidden=true;return;}
        if(background)rows.clear();
        d.items.forEach(t=>rows.set(t.id,t));scanned+=d.scanned;unverified+=d.unverified_closures||0;next=d.next_offset;lastTotal=d.total_candidates||0;started=true;
        const exact=next===null;
        note.textContent=`${rows.size}${exact?'':'+'} resultado(s) compatível(is) · ${scanned} de ${d.total_candidates} candidato(s) examinados. ${d.scope}${unverified?' '+unverified+' chamado(s) sem autoria técnica verificável ficaram fora.':''}${d.errors?.length?' '+d.errors.length+' falha(s) de leitura nesta página.':''}${d.warnings?.length?' '+d.warnings.length+' dado(s) complementar(es) indisponível(is).':''}`;
        note.textContent+=' · Atualizado às '+new Date().toLocaleTimeString('pt-BR');
        more.hidden=next===null;more.textContent=filters.get('q')?'Continuar pesquisa':'Carregar mais chamados';render();
        if(next!==null&&next<=Number(qs.get('offset')))throw Error('A API não avançou a página. Resultados parciais preservados.');
      }catch(e){if(e.name!=='AbortError')note.textContent=e.message;}finally{busy=false;form.querySelector('button[type=submit]').disabled=false;more.disabled=false;}
    }

    function invalidate(){revision++;controller?.abort();more.hidden=true;note.textContent='Filtros alterados. Atualize a consulta para aplicar.';}
    form.oninput=invalidate;
    form.onsubmit=e=>{e.preventDefault();query();};
    more.onclick=()=>query(true);
    root.querySelector('[data-cancel]').onclick=()=>{controller?.abort();note.textContent='Consulta interrompida. Resultados já carregados foram preservados.';};
    if(!closureWorkspace){
      root.querySelector('[data-clear]').onclick=()=>{selected.clear();render();};
      root.querySelector('[data-finish]').onclick=()=>{if(selected.size>20){note.textContent='Selecione até 20 chamados por lote.';return;}window.prepareWorkbenchSolutions([...selected].map(id=>rows.get(id)));};
    }else{
      root.querySelectorAll('[data-closure-view]').forEach(button=>button.onclick=()=>{
        if(button.dataset.closureView===closureView)return;
        closureView=button.dataset.closureView;
        root.querySelectorAll('[data-closure-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
        started=false;next=0;revision++;controller?.abort();query();
      });
    }

    async function activate(){
      if(!started&&!busy){
        query();
        try{const r=await fetch('/api/workbench/entities');if(r.ok){const d=await r.json(),select=form.elements.entity_id;const old=select.value;select.innerHTML='<option value="-1">Todas as empresas</option>'+d.items.map(e=>`<option value="${e.id}">${safe(e.name)}</option>`).join('');select.value=old;}}catch{}
      }
    }
    let filterDirty=false;
    form.addEventListener('input',()=>{filterDirty=true;});form.addEventListener('submit',()=>{filterDirty=false;});
    setInterval(()=>{
      if(closureWorkspace||document.hidden||location.hash!=='#minha-fila'||busy||selected.size||filterDirty||(root.contains(document.activeElement)&&document.activeElement?.matches('input,textarea,select')))return;
      query(false,true);
    },30000);
    return {activate};
  }

  views['minha-fila']=make('myQueueWorkspace','assigned');
  views.encerrados=make('myClosedWorkspace','closure');
  globalThis.MyTickets={activate:id=>views[id]?.activate()};
  MyTickets.activate(location.hash.slice(1));
})();
