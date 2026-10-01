'use strict';
// Each pane owns its data; no batch operation reads the single-ticket editor.
(() => {
  const root = document.createElement('section');
  root.className = 'card closure-queue';
  root.id = 'closureQueue';
  root.innerHTML = `<h2>Registros pendentes</h2><p>Um chamado por aba. Revise todos e aplique os selecionados em sequência. Os rascunhos ficam nesta página; exporte antes de sair.</p>
    <div class="actions"><button type="button" data-new>+ Novo chamado</button><button type="button" class="secondary" data-capture>Copiar rascunho atual</button><button type="button" class="secondary" data-export>Exportar textos</button></div>
    <div class="closure-tabs" role="tablist" aria-label="Chamados em preparação"></div><div class="closure-panes"></div>
    <div class="actions"><button type="button" data-review>Revisar selecionados</button><button type="button" data-apply disabled>Aplicar lote revisado</button></div>
    <p data-status role="status">Nenhum pacote preparado.</p>`;
  document.querySelector('#operacao .section-title-row').after(root);
  const modeBar = document.createElement('div'); modeBar.className = 'closure-mode actions';
  modeBar.innerHTML = '<button type="button" class="secondary" data-single>Editor individual / backup</button><button type="button" class="secondary" data-multi>Abas e fechamento em lote</button>';
  root.before(modeBar);
  function mode(multi) {
    document.querySelector('#operacao').classList.toggle('queue-mode', multi);
    root.hidden = !multi;
    modeBar.querySelector('[data-single]').setAttribute('aria-pressed', String(!multi));
    modeBar.querySelector('[data-multi]').setAttribute('aria-pressed', String(multi));
  }
  modeBar.querySelector('[data-single]').onclick = () => mode(false);
  modeBar.querySelector('[data-multi]').onclick = () => mode(true);
  mode(false);
  const tabs = root.querySelector('.closure-tabs'), panes = root.querySelector('.closure-panes');
  const reviewButton = root.querySelector('[data-review]'), applyButton = root.querySelector('[data-apply]');
  const drafts = new Map();
  let sequence = 0, active = null, revision = 0, busy = false, reviewed = null;
  let lastOutcomes = [];
  const receiptButton = document.createElement('button');
  receiptButton.type='button'; receiptButton.className='secondary'; receiptButton.textContent='Ver último comprovante'; receiptButton.hidden=true;
  const receiptActions=document.createElement('div');receiptActions.className='queue-receipt-actions';receiptActions.append(receiptButton);root.querySelector('[data-status]').before(receiptActions);
  function showReceipt() {
    window.BatchReceipt.show({outcomes:lastOutcomes,
      pending:[...drafts.values()].map(d=>({key:d.key,id:value(d,'ticket').value,state:d.state})),
      selectPending:key=>{const d=drafts.get(key);if(d){select(d);d.tab.focus();}},
      createDraft:()=>{try{const d=create();value(d,'ticket').focus();}catch(error){status(error.message);}}
    });
  }
  receiptButton.onclick=showReceipt;
  const status = message => { root.querySelector('[data-status]').textContent = message; };
  const value = (d, name) => d.panel.querySelector(`[data-${name}]`);
  const operationLabel = op => {
    const names = { add_group:'Adicionar grupo', remove_group:'Remover grupo', add_technician:'Adicionar técnico',
      remove_technician:'Remover técnico', update_ticket:'Atualizar chamado', create_task:'Criar tarefa',
      skip_existing_task:'Preservar tarefa já existente' };
    if (op.op === 'contact_receipt') return `Primeiro contato: ${op.receipt.at} · ${op.receipt.status} · ID ${op.receipt.message_id}`;
    if (op.op === 'create_task') return `Criar ${op.task_id || 'tarefa'} · ${formatDuration(op.actiontime)} · ${(op.evidences || []).join(', ') || 'sem prints'}`;
    if (op.op === 'skip_existing_task') return `Preservar ${op.task_id || 'tarefa'} · já existe no GLPI`;
    return names[op.op] || String(op.op || 'Operação prevista').replaceAll('_', ' ');
  };
  function appendOutcome(d, result, existingTasks = false) {
    const box = value(d, 'result');
    const section = document.createElement('section');
    section.className = `closure-outcome ${result.ok ? 'ok' : 'bad'}`;
    const heading = document.createElement('strong');
    heading.textContent = result.ok ? '✓ Aplicação confirmada pelo GLPI' : '! Aplicação incompleta — não repita sem conferir';
    const summary = document.createElement('p');
    if (existingTasks) {
      const rows = result.results || [], done = rows.filter(row => row.ok).length;
      summary.textContent = `${done}/${rows.length + (result.not_executed || []).length} tarefa(s) processadas com confirmação.`;
    } else {
      summary.textContent = `${result.verified_task_count || 0}/${result.expected_task_count || 0} tarefa(s) criadas e confirmadas · ${(result.errors || []).length} falha(s).`;
    }
    section.append(heading, summary);
    const failures = existingTasks ? (result.results || []).filter(row => !row.ok).map(row => `Tarefa #${row.task_id}: ${row.error}`)
      : (result.errors || []).map(row => `${row.task || row.stage || 'Operação'}: ${row.message || 'falha não detalhada'}`);
    for (const message of failures) { const line = document.createElement('p'); line.className = 'closure-outcome-error'; line.textContent = message; section.append(line); }
    const details = document.createElement('details'), label = document.createElement('summary'), raw = document.createElement('pre');
    label.textContent = 'Detalhes técnicos'; raw.textContent = JSON.stringify(result, null, 2); details.append(label, raw); section.append(details);
    box.append(section); box.closest('details').open = true;
  }
  function invalidate() { revision++; reviewed = null; applyButton.disabled = true; }
  function select(d) {
    mode(true);
    active = d.key;
    for (const other of drafts.values()) {
      other.panel.hidden = other !== d;
      other.tab.setAttribute('aria-selected', String(other === d));
      other.tab.tabIndex = other === d ? 0 : -1;
    }
  }
  function lock(on) {
    busy = on;
    for (const node of document.querySelector('#operacao').children) if (node !== root) node.inert = on;
    document.querySelector('.workspace-nav').inert = on;
    root.querySelectorAll('input,textarea,select,button').forEach(e => {
      if (on) { e.dataset.beforeLockDisabled = String(e.disabled); e.disabled = true; }
      else { e.disabled = e.dataset.beforeLockDisabled === 'true'; delete e.dataset.beforeLockDisabled; }
    });
    if (!on) applyButton.disabled = !reviewed;
  }
  function title(d) {
    const id = value(d, 'ticket').value;
    d.tab.textContent = `#${id || 'Novo'} · ${d.state || 'Rascunho'}`;
  }
  function addImages(d, incoming, localEvidence = true) {
    const additions = [];
    for (const entry of incoming) {
      const file = entry.file || entry;
      if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw Error('Use prints PNG, JPEG ou WebP.');
      if (file.size > 8 * 1024 * 1024) throw Error('Cada print pode ter até 8 MiB.');
      additions.push({ id: entry.file ? entry.id : crypto.randomUUID(), file, localEvidence });
    }
    if ([...d.files, ...additions].reduce((sum, e) => sum + e.file.size, 0) > 20 * 1024 * 1024 || d.files.length + additions.length > 30) {
      throw Error('O chamado ultrapassou 20 MiB de prints. Remova arquivos antes de revisar.');
    }
    d.files.push(...additions);
    renderFiles(d); invalidate();
  }
  function mappedEvidenceForFile(d, fileId, index) {
    const match = Object.entries(d.mapping || {}).find(([, value]) => value === fileId)?.[0];
    return match || `Print ${index + 1}`;
  }
  function previewUrl(entry) {
    if (!entry.previewUrl) entry.previewUrl = URL.createObjectURL(entry.file);
    return entry.previewUrl;
  }
  function releaseEntry(entry) {
    if (entry?.previewUrl) { URL.revokeObjectURL(entry.previewUrl); entry.previewUrl = ''; }
  }
  function renderPreview(d) {
    const box = value(d, 'preview'), strip = value(d, 'preview-strip');
    if (!box || !strip) return;
    strip.replaceChildren();
    box.hidden = !d.files.length; const count=value(d,'preview-count'); if(count) count.textContent=`${d.files.length} print${d.files.length===1?'':'s'} carregado${d.files.length===1?'':'s'}`;
    d.files.forEach((entry, index) => {
      const card = document.createElement('button'); card.type = 'button'; card.className = 'queue-preview-item';
      card.title = `Ampliar ${entry.file.name}`;
      const img = document.createElement('img'); img.src = previewUrl(entry); img.alt = `Prévia de ${entry.file.name}`;
      const tag = document.createElement('strong'); tag.className='queue-preview-tag'; tag.textContent = mappedEvidenceForFile(d, entry.id, index); card.classList.toggle('is-mapped', !tag.textContent.startsWith('Print '));
      const name = document.createElement('small'); name.textContent = entry.file.name;
      card.append(img, tag, name);
      card.onclick = () => {
        const dialog = document.querySelector('#evidencePreviewDialog'), target = document.querySelector('#evidencePreviewImage');
        if (!dialog || !target) return;
        target.src = previewUrl(entry); target.alt = `Prévia ampliada de ${entry.file.name}`;
        document.querySelector('#evidencePreviewTitle').textContent = mappedEvidenceForFile(d, entry.id, index);
        document.querySelector('#evidencePreviewName').textContent = entry.file.name;
        if (typeof dialog.showModal === 'function') dialog.showModal();
      };
      strip.append(card);
    });
  }
  function renderFiles(d) {
    value(d, 'files').replaceChildren();
    for (const entry of d.files) {
      const row = document.createElement('div'); row.className = 'queue-file-row';
      const label = document.createElement('span'); label.textContent = entry.file.name;
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'ghost'; remove.textContent = 'Remover';
      remove.onclick = () => { releaseEntry(entry); d.files = d.files.filter(e => e.id !== entry.id); renderFiles(d); invalidate(); };
      row.append(label, remove); value(d, 'files').append(row);
    }
    renderMapping(d); renderPreview(d);
    d.panel.querySelectorAll('[data-existing-files]').forEach(select => {
      const selected = new Set([...select.selectedOptions].map(o => o.value)); select.replaceChildren();
      for (const entry of d.files) select.add(new Option(entry.file.name, entry.id, false, selected.has(entry.id)));
    });
  }
  function renderMapping(d) {
    const ids = [...new Set([...value(d, 'text').value.matchAll(/\[EVID[ÊE]NCIA\s*:\s*([A-Za-z0-9_.-]+)\s*\]/gi)].map(m => m[1].toUpperCase()))];
    for (const id of Object.keys(d.mapping)) {
      if (!ids.includes(id) || !d.files.some(e => e.id === d.mapping[id])) delete d.mapping[id];
    }
    const used = new Set(Object.values(d.mapping));
    // Bind explicit IDs before considering local insertion order, even if text is E02, E01.
    for (const id of ids) {
      if (d.mapping[id] || d.manualMapping?.has(id)) continue;
      const matches = d.files.filter(e => !used.has(e.id) &&
        (e.file.bridgeEvidenceId === id || (!e.file.bridgeEvidenceId && e.file.name.replace(/\.[^.]+$/, '').toUpperCase() === id)));
      if (matches.length === 1) { d.mapping[id] = matches[0].id; used.add(matches[0].id); }
    }
    const missing = ids.filter(id => !d.mapping[id] && !d.manualMapping?.has(id));
    const local = d.files.filter(e => e.localEvidence && !used.has(e.id) && !e.file.bridgeEvidenceId && !/^E\d{2,3}\./i.test(e.file.name));
    if (local.length <= missing.length) {
      local.forEach((e, i) => { d.mapping[missing[i]] = e.id; used.add(e.id); });
    }
    const container = value(d, 'mapping'); container.replaceChildren();
    for (const id of ids) {
      const label = document.createElement('label'); label.textContent = id;
      const selectFile = document.createElement('select'); selectFile.innerHTML = '<option value="">Associe o print desta evidência</option>';
      for (const entry of d.files) selectFile.add(new Option(entry.file.name, entry.id));
      selectFile.value = d.mapping[id] || '';
      selectFile.onchange = () => { (d.manualMapping ||= new Set()).add(id); d.mapping[id] = selectFile.value; invalidate(); renderPreview(d); };
      label.append(selectFile); container.append(label);
    }
    for (const id of Object.keys(d.mapping)) if (!ids.includes(id)) delete d.mapping[id];
  }
  function create(packet = {}, { activate = true } = {}) {
    if (busy) throw Error('Aguarde o lote atual terminar. O pacote continua na Inbox.');
    if (drafts.size >= 20) throw Error('Limite de 20 abas. Remova as concluídas para continuar.');
    const key = String(++sequence), panel = document.createElement('div'), tab = document.createElement('button');
    panel.className = 'closure-pane'; panel.id = `closure-pane-${key}`; panel.setAttribute('role', 'tabpanel');
    tab.type = 'button'; tab.id = `closure-tab-${key}`; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', panel.id);
    panel.setAttribute('aria-labelledby', tab.id);
    panel.innerHTML = `<div class="queue-pane-toolbar"><label class="queue-select-toggle"><input type="checkbox" data-selected><span class="queue-select-indicator" aria-hidden="true">✓</span><span class="queue-select-copy"><strong>Incluir no lote</strong><small>Aplicar junto aos demais revisados</small></span></label><label class="queue-field"><span>Chamado</span><input type="number" min="1" data-ticket></label><label class="queue-field"><span>Depois das tarefas</span><select data-target><option value="tasks">Somente tarefas</option><option value="solve">Solucionar</option><option value="close">Fechar</option></select></label><button type="button" class="ghost queue-remove" data-remove>Remover aba</button></div>
      <section class="queue-section queue-text-section"><div class="queue-section-head"><div><span class="queue-step">01</span><strong>Fechamento estruturado</strong><small>Mantenha o marcador [GLPI_ASSISTANT:ID]</small></div></div><textarea data-text rows="10" placeholder="[GLPI_ASSISTANT:901390]"></textarea></section>
      <section class="queue-section queue-evidence-section" data-evidence-dropzone><div class="queue-section-head"><div><span class="queue-step">02</span><strong>Evidências</strong><small>Prints adicionados aqui seguem a ordem das evidências deste chamado. Confira a associação antes de revisar.</small></div><div class="queue-evidence-actions"><label class="queue-file-picker"><span>＋ Adicionar prints</span><input type="file" multiple accept="image/png,image/jpeg,image/webp" data-picker></label><button type="button" class="queue-drop-clip" data-drop-clip title="Clique para selecionar ou arraste prints sobre esta área" aria-label="Adicionar ou arrastar prints">📎 <span>Arraste aqui</span></button></div></div><textarea data-paste-image rows="2" aria-label="Colar prints neste chamado" placeholder="Clique aqui e cole a imagem com Ctrl+V — ou arraste o arquivo"></textarea><div class="queue-drop-hint" data-drop-hint hidden>Solte os prints neste chamado</div><div class="queue-evidence-preview" data-preview hidden><div class="queue-preview-head"><strong>Prévia deste chamado</strong><span data-preview-count>0 prints carregados</span></div><div class="queue-preview-strip" data-preview-strip></div></div><div data-files class="queue-file-list"></div><div data-mapping class="editor-grid queue-mapping-grid"></div></section>
      <section class="queue-section queue-solution-section"><div class="queue-section-head"><div><span class="queue-step">03</span><strong>Solução para concluir</strong><small>Obrigatória apenas para solucionar ou fechar</small></div></div><textarea data-solution rows="3" placeholder="Descreva a solução validada quando o destino exigir conclusão."></textarea></section>
      <details class="queue-review-details"><summary>Revisão e resultado deste chamado</summary><div data-result class="closure-result"></div></details>`;
    const existing = document.createElement('section');
    existing.innerHTML = '<label>Origem das tarefas<select data-source><option value="new">Texto da IA · novas tarefas</option><option value="existing">Tarefas prontas · conferência de backup</option></select></label><div data-existing-panel hidden><button type="button" class="secondary" data-load-existing>Carregar tarefas deste chamado</button><p>Selecione apenas as verificações realizadas. Informe o tempo real e associe os prints de cada tarefa.</p><div data-existing-rows></div></div>';
    value({panel}, 'text').parentElement.before(existing);
    const d = { key, panel, tab, files: [], mapping: {}, state: 'Rascunho', packetId: packet.id || null };
    drafts.set(key, d); tabs.append(tab); panes.append(panel);
    value(d, 'ticket').value = packet.ticket_id || '';
    value(d, 'text').value = packet.closure || '';
    d.original = packet.closure || '';
    tab.onclick = () => select(d);
    tab.onkeydown = event => {
      const all = [...drafts.values()], index = all.indexOf(d);
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? all.length - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + all.length) % all.length;
        select(all[next]); all[next].tab.focus();
      }
    };
    panel.addEventListener('input', () => { d.state = 'Rascunho'; invalidate(); title(d); });
    value(d, 'text').addEventListener('change', () => renderMapping(d));
    value(d, 'source').onchange = () => {
      const ready = value(d, 'source').value === 'existing';
      value(d, 'existing-panel').hidden = !ready;
      value(d, 'text').parentElement.hidden = ready;
      value(d, 'mapping').hidden = ready;
      invalidate();
    };
    value(d, 'load-existing').onclick = async () => {
      const id = Number(value(d, 'ticket').value);
      if (!Number.isSafeInteger(id) || id <= 0) { status('Informe o chamado desta aba.'); return; }
      const loadRevision = d.loadRevision = (d.loadRevision || 0) + 1;
      value(d, 'load-existing').disabled = true;
      try {
        const response = await api('/api/templates/' + id);
        if (busy || d.loadRevision !== loadRevision || Number(value(d, 'ticket').value) !== id) return;
        d.templateTicket = id;
        value(d, 'existing-rows').replaceChildren();
        for (const task of response.tasks) {
          const row = document.createElement('article'); row.className = 'wb-template-row'; row.dataset.existingId = task.id;
          row.innerHTML = '<label class="check"><input type="checkbox" data-use-existing>Incluir tarefa <span></span></label><label>Texto<textarea data-existing-text rows="3"></textarea></label><label>Tempo total real (minutos)<input data-existing-time type="number" min="0" step="any"></label><label class="check"><input type="checkbox" data-existing-complete>Verificação realizada · marcar concluída</label><label>Prints desta tarefa<select multiple data-existing-files></select></label>';
          row.querySelector('span').textContent = '#' + task.id;
          row.querySelector('[data-existing-text]').value = task.text;
          row.querySelector('[data-existing-time]').value = Number(task.actiontime || 0) / 60;
          row.querySelector('[data-existing-complete]').checked = Number(task.state) === 2;
          row.querySelector('[data-existing-complete]').disabled = Number(task.state) === 2;
          value(d, 'existing-rows').append(row);
        }
        renderFiles(d); invalidate();
        status(`#${id}: ${response.tasks.length} tarefas prontas carregadas. Nenhuma foi selecionada automaticamente.`);
      } catch (error) { status(error.message); }
      finally { if (!busy) value(d, 'load-existing').disabled = false; }
    };
    value(d, 'picker').onchange = e => { try { addImages(d, [...e.target.files]); } catch (error) { status(error.message); renderFiles(d); } e.target.value = ''; };
    const dropzone = value(d, 'evidence-dropzone'), dropHint = value(d, 'drop-hint'), dropClip = value(d, 'drop-clip');
    const clearDrag = () => { dropzone?.classList.remove('is-dragging'); if (dropHint) dropHint.hidden = true; };
    dropClip.onclick = () => value(d, 'picker').click();
    for (const ev of ['dragenter','dragover']) dropzone.addEventListener(ev, event => {
      if (!event.dataTransfer?.types?.includes('Files')) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
      dropzone.classList.add('is-dragging'); if (dropHint) dropHint.hidden = false;
    });
    for (const ev of ['dragleave','drop']) dropzone.addEventListener(ev, event => {
      if (ev === 'drop') event.preventDefault(); clearDrag();
    });
    dropzone.addEventListener('drop', event => {
      const incoming = [...(event.dataTransfer?.files || [])]; if (!incoming.length) return;
      try { addImages(d, incoming); status(`#${value(d,'ticket').value || 'novo'}: ${incoming.length} print(s) adicionados por arrastar e soltar.`); }
      catch (error) { status(error.message); renderFiles(d); }
    });
    panel.addEventListener('paste', event => {
      const incoming = [...(event.clipboardData?.files || [])].filter(file => /^image\/(png|jpeg|webp)$/.test(file.type || ''));
      if (!incoming.length) return;
      event.preventDefault();
      try { addImages(d, incoming); status(`#${value(d,'ticket').value || 'novo'}: ${incoming.length} print(s) colados na aba.`); }
      catch (error) { status(error.message); renderFiles(d); }
    });
    value(d, 'remove').onclick = () => {
      if (!confirm('Remover este rascunho e seus prints desta página? O GLPI e a Inbox não serão alterados.')) return;
      removeDraft(d); invalidate();
      const next = [...drafts.values()][0]; if (next) select(next); else active = null;
    };
    title(d);
    if (activate) select(d); else { panel.hidden = true; tab.setAttribute('aria-selected', 'false'); tab.tabIndex = -1; }
    renderMapping(d); invalidate(); return d;
  }
  function removeDraft(d) {
    if (!d) return;
    d.files.forEach(releaseEntry);
    drafts.delete(d.key); d.panel.remove(); d.tab.remove();
    if (active === d.key) active = null;
  }
  function pruneCompleted() {
    const completed = new Set(['Fechado', 'Solucionado', 'Aplicado']);
    for (const d of [...drafts.values()]) if (completed.has(d.state)) removeDraft(d);
    if (!active) { const next = [...drafts.values()][0]; if (next) { select(next); } }
    invalidate();
  }
  function applyImportedIntent(d, packet) {
    const intent = packet.intent;
    const valid = intent && ['solve', 'close'].includes(intent.target)
      && typeof intent.solution === 'string' && intent.solution.trim().length >= 10
      && intent.solution.length <= 4000 && typeof intent.include_in_batch === 'boolean';
    const signature = valid ? JSON.stringify(intent) : '';
    if (d.lastImportedIntent === signature) return;
    if (valid) {
      value(d, 'target').value = intent.target;
      value(d, 'solution').value = intent.solution.trim();
      value(d, 'selected').checked = intent.include_in_batch;
      d.lastImportedIntent = signature;
      if (intent.include_in_batch) select(d);
    } else if (d.lastImportedIntent) {
      value(d, 'target').value = 'tasks';
      value(d, 'solution').value = '';
      value(d, 'selected').checked = false;
      d.lastImportedIntent = '';
    }
  }
  async function receive(packet, { activate = true, files = null } = {}) {
    if (packet.status === 'completed') return true;
    if (busy || executionBusy) return false;
    const text = normalizeText(packet.closure || '');
    const ticketId = Number(packet.ticket_id || text.match(/\[GLPI_ASSISTANT\s*:\s*(\d+)\]/i)?.[1]);
    if (!Number.isSafeInteger(ticketId) || ticketId <= 0 || !text) throw Error('Pacote sem número ou texto de chamado válido.');
    pruneCompleted();
    const existing = [...drafts.values()].find(d => d.packetId === packet.id && packet.id);
    const fingerprint = JSON.stringify([text, packet.images || [], files?.map(f => [f.name, f.size, f.bridgeEvidenceId]) || null]);
    if (existing?.fingerprint === fingerprint) { if (activate) select(existing); return true; }
    // Download first; a failed image transfer must not mark a partial packet imported.
    const fetched = files ? [...files] : [];
    if (!files) for (const img of packet.images || []) {
      const response = await fetch(`/api/bridge/images/${packet.id}/${encodeURIComponent(img.id)}`);
      if (!response.ok) throw Error(`Print ${img.id} indisponível; pacote preservado na Inbox.`);
      const blob = await response.blob(); const file = new File([blob], img.name, { type: blob.type });
      file.bridgeEvidenceId = img.id; file.bridgeTicketId = ticketId; fetched.push(file);
    }
    if (packet.status === 'completed') return true;
    if (busy || executionBusy) return false;
    if (fetched.some(file => file.bridgeTicketId && Number(file.bridgeTicketId) !== ticketId)) throw Error('Print de outro chamado; importação bloqueada.');
    // Validate the full transfer before creating an acknowledged draft.
    const probe = { files: [] };
    for (const file of fetched) {
      if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 8 * 1024 * 1024) throw Error('Print inválido; pacote preservado na Inbox.');
      probe.files.push(file);
    }
    if (probe.files.length > 30 || probe.files.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024) throw Error('Limite de prints excedido; pacote preservado na Inbox.');
    const sameTicket = [...drafts.values()].find(d => Number(value(d, 'ticket').value) === ticketId);
    if (sameTicket) {
      if (normalizeText(value(sameTicket, 'text').value).trim() !== normalizeText(sameTicket.original || '').trim()) {
        throw Error(`Chamado #${ticketId} tem texto editado. Atualização preservada na Inbox; copie seu rascunho antes de reimportar.`);
      }
      if (sameTicket.files.some(entry => entry.localEvidence) || sameTicket.manualMapping?.size) {
        throw Error(`Chamado #${ticketId} tem prints ou associações manuais. Atualização preservada na Inbox para evitar perda das suas alterações.`);
      }
      sameTicket.files.forEach(releaseEntry); sameTicket.files = []; sameTicket.mapping = {}; sameTicket.manualMapping = new Set(); sameTicket.packetId = packet.id || null;
      value(sameTicket, 'text').value = text; sameTicket.original = text; sameTicket.state = 'Recebido'; sameTicket.fingerprint = fingerprint;
      addImages(sameTicket, fetched, false); renderMapping(sameTicket); applyImportedIntent(sameTicket, packet); title(sameTicket);
      if (activate) select(sameTicket);
      status(`Pacote #${ticketId} atualizado na aba de lote existente; o conteúdo anterior foi substituído.`);
      return true;
    }
    const d = create({ ...packet, ticket_id: ticketId, closure: text }, { activate });
    d.state = 'Recebido'; d.fingerprint = fingerprint; title(d);
    addImages(d, fetched, false); applyImportedIntent(d, packet);
    status(`Pacote #${ticketId} adicionado às abas de lote${activate ? '' : ' em segundo plano'}.`);
    return true;
  }
  async function review() {
    const selected = [...drafts.values()].filter(d => value(d, 'selected').checked);
    if (!selected.length) throw Error('Selecione ao menos uma aba para revisar.');
    invalidate(); lock(true);
    try {
      const plans = [], ids = new Set();
      for (const d of selected) {
        const id = Number(value(d, 'ticket').value), text = normalizeText(value(d, 'text').value);
        if (!Number.isSafeInteger(id) || id <= 0 || ids.has(id)) throw Error('Informe IDs válidos, sem repetir o mesmo chamado no lote.');
        ids.add(id);
        const source = value(d, 'source').value;
        const markers = [...text.matchAll(/\[GLPI_ASSISTANT\s*:\s*(\d+)\]/gi)].map(m => Number(m[1]));
        if (source === 'new' && (!markers.length || markers.some(marker => marker !== id))) throw Error(`#${id}: marcador ausente ou aponta para outro chamado.`);
        const target = value(d, 'target').value, solution = value(d, 'solution').value.trim();
        if (target !== 'tasks' && solution.length < 10) throw Error(`#${id}: descreva a solução validada.`);
        if (d.files.reduce((sum, e) => sum + e.file.size, 0) > 20 * 1024 * 1024) throw Error(`#${id}: prints excedem 20 MiB.`);
        if (source === 'existing') {
          if (d.templateTicket !== id) throw Error(`#${id}: carregue as tarefas deste chamado antes de revisar.`);
          const uploads = [], changes = [];
          for (const row of d.panel.querySelectorAll('[data-existing-id]')) {
            if (!row.querySelector('[data-use-existing]').checked) continue;
            const indexes = [];
            for (const option of row.querySelector('[data-existing-files]').selectedOptions) {
              const entry = d.files.find(e => e.id === option.value);
              if (!entry || uploads.some(e => e.id === entry.id)) throw Error(`#${id}: print ausente ou associado a mais de uma tarefa.`);
              indexes.push(uploads.length); uploads.push(entry);
            }
            changes.push({ task_id: Number(row.dataset.existingId), text: row.querySelector('[data-existing-text]').value,
              actiontime: Math.round(Number(row.querySelector('[data-existing-time]').value) * 60),
              complete: row.querySelector('[data-existing-complete]').checked, files: indexes });
          }
          if (uploads.length !== d.files.length) throw Error(`#${id}: associe todos os prints às tarefas selecionadas.`);
          const body = new FormData(); body.append('ticket_id', id); body.append('edits', JSON.stringify(changes));
          uploads.forEach(e => body.append('files', e.file, e.file.name));
          const templatePlan = await api('/api/templates/plan', { method: 'POST', body });
          value(d, 'result').textContent = `#${id} · tarefas existentes · destino ${target}\nSolução: ${solution}\n` + templatePlan.rows.map(r => `Tarefa #${r.task_id} · ${formatDuration(r.actiontime)} · ${r.complete ? 'Concluir' : 'Preservar estado'}\n${r.text}\nPrints: ${r.files.map(i => uploads[i].file.name).join(', ') || 'nenhum'}`).join('\n\n');
          value(d, 'result').closest('details').open = true;
          d.state = 'Revisado'; title(d);
          plans.push({ d, id, uploads, target, solution, templatePlan, plan: { task_count: templatePlan.rows.length } });
          continue;
        }
        renderMapping(d);
        const mapping = Object.fromEntries(Object.entries(d.mapping).filter(([, fileId]) => fileId));
        status(`Gerando revisão do chamado #${id}…`);
        const plan = await api('/api/plan', jsonOpts({ ticket_id: id, text, evidence_map: mapping }));
        if (Number(plan.ticket.id) !== id) throw Error('A API devolveu outro chamado. Aplicação bloqueada.');
        const required = plan.required_evidence_ids ?? plan.parsed.evidence_ids;
        const missing = required.filter(e => !d.files.some(f => f.id === mapping[e]));
        if (missing.length) throw Error(`#${id}: associe os prints ${missing.join(', ')} antes de aplicar.`);
        const assigned = required.map(e => mapping[e]);
        if (new Set(assigned).size !== assigned.length) throw Error(`#${id}: um mesmo print foi associado a evidências diferentes.`);
        const used = new Set(assigned);
        const uploads = d.files.filter(e => used.has(e.id));
        if (d.files.some(e => !used.has(e.id))) throw Error(`#${id}: há prints sem destino nas tarefas novas. Remova-os desta aba ou ajuste o texto.`);
        const snapshot = { d, id, text, mapping, uploads, target, solution, plan };
        const operations = plan.operations.map(operationLabel).map(label => `• ${label}`).join('\n');
        value(d, 'result').textContent = `Chamado #${id} · ${plan.ticket.title}\nDestino: ${target}\nSolução: ${solution || 'Não será enviada'}\n${operations}`;
        value(d, 'result').closest('details').open = true;
        d.state = 'Revisado'; title(d); plans.push(snapshot);
      }
      reviewed = { revision, plans }; status(`${plans.length} chamado(s) revisados. Confira as operações de cada aba antes de aplicar.`);
    } finally { lock(false); }
  }
  async function apply() {
    if (!reviewed || reviewed.revision !== revision || busy) return;
    const batch = reviewed;
    if (!confirm(`Aplicar as revisões destes chamados?\n${batch.plans.map(p => `#${p.id}: ${p.plan.task_count} tarefa(s), destino ${p.target}`).join('\n')}\n\nTarefas e prints serão registrados antes da conclusão. Uma falha interrompe os próximos envios.`)) return;
    reviewed = null; lock(true);
    const outcomes = [];
    try {
      for (const p of batch.plans) {
        const { d } = p;
        select(d); d.state = 'Enviando'; title(d); status(`Aplicando chamado #${p.id}…`);
        try {
          if (p.templatePlan) {
            const body = new FormData(); body.append('plan_id', p.templatePlan.id);
            p.uploads.forEach(e => body.append('files', e.file, e.file.name));
            const result = await api('/api/templates/apply', { method: 'POST', body });
            appendOutcome(d, result, true);
            if (!result.ok) throw Error('Atualização parcial das tarefas existentes; confira o resultado.');
          } else if (p.plan.has_actionable_operations) {
            const body = new FormData();
            body.append('ticket_id', p.id); body.append('text', p.text); body.append('plan_id', p.plan.plan_id); body.append('evidence_map', JSON.stringify(p.mapping));
            p.uploads.forEach(e => { body.append('file_ids', e.id); body.append('files', e.file, e.file.name); });
            const result = await api('/api/execute', { method: 'POST', body });
            appendOutcome(d, result, false);
            if (!result.ok) throw Error('Tarefas parcialmente aplicadas. Consulte o resultado antes de repetir.');
          }
          d.state = 'Tarefas confirmadas'; title(d);
          if (p.target !== 'tasks') await window.finishAfterFormalization(p.id, p.solution, p.target);
          d.state = p.target === 'close' ? 'Fechado' : p.target === 'solve' ? 'Solucionado' : 'Aplicado'; title(d);
          value(d, 'selected').checked = false;
          value(d, 'result').textContent += '\nResultado confirmado pela API.';
          outcomes.push({id:p.id,ok:true,detail:p.target==='close'?'Tarefas confirmadas e chamado fechado.':p.target==='solve'?'Tarefas confirmadas e chamado solucionado.':'Operações da revisão confirmadas. Registro removido dos pendentes.'});
          // Server confirmation persists independently of visible pending drafts.
          removeDraft(d);
        } catch (error) {
          d.state = 'Conferir resultado'; title(d);
          outcomes.push({id:p.id,ok:false,detail:error.message});
          value(d, 'result').textContent += '\n' + error.message;
          throw Error(`#${p.id}: ${error.message} Lote interrompido. Demais abas preservadas; não reenviadas.`);
        }
      }
      if (!active && drafts.size) select([...drafts.values()][0]);
      status('Envio confirmado. Abas enviadas removidas; pendências preservadas.');
    } finally {
      revision++; lock(false);
      if (!active && drafts.size) select([...drafts.values()][0]);
      if(outcomes.length){lastOutcomes=outcomes;receiptButton.hidden=false;showReceipt();}
    }
  }
  reviewButton.onclick = () => review().catch(error => status(error.message));
  applyButton.onclick = () => apply().catch(error => status(error.message));
  root.querySelector('[data-new]').onclick = () => { try { create(); } catch (error) { status(error.message); } };
  root.querySelector('[data-capture]').onclick = () => {
    try {
      if (!currentTicketId() || !document.querySelector('#closure').value.trim()) throw Error('Carregue o chamado e o texto no editor primeiro.');
      const d = create({ ticket_id: currentTicketId(), closure: document.querySelector('#closure').value });
      d.mapping = { ...evidenceMap() }; addImages(d, files.map(e => ({ ...e })));
      value(d, 'solution').value = document.querySelector('#wbAfterSolution').value;
      value(d, 'target').value = document.querySelector('#wbAfterMode').value;
      status('Rascunho copiado com prints e mapeamento. O editor original foi preservado.');
    } catch (error) { status(error.message); }
  };
  root.querySelector('[data-export]').onclick = () => {
    const data = [...drafts.values()].map(d => ({ ticket_id: value(d, 'ticket').value, closure: value(d, 'text').value, solution: value(d, 'solution').value, target: value(d, 'target').value, state: d.state, evidence_files: d.files.map(e => e.file.name) }));
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'glpi-rascunhos.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('Textos exportados. As imagens não estão incluídas: mantenha os arquivos originais.');
  };
  window.addEventListener('beforeunload', event => {
    if (busy || [...drafts.values()].some(d => !['Fechado', 'Solucionado', 'Aplicado'].includes(d.state))) { event.preventDefault(); event.returnValue = ''; }
  });
  function reconcile(completedIds) {
    if (busy || executionBusy) return;
    const done = new Set(completedIds.map(Number));
    for (const d of [...drafts.values()]) if (value(d, 'target').value === 'tasks' && done.has(Number(d.packetId)) && normalizeText(value(d, 'text').value).trim() === normalizeText(d.original).trim()) removeDraft(d);
    if (!active && drafts.size) select([...drafts.values()][0]);
  }
  function complete(ticketId, text) {
    for (const d of [...drafts.values()]) {
      if (Number(value(d, 'ticket').value) === Number(ticketId) && normalizeText(value(d, 'text').value).trim() === normalizeText(text).trim()) removeDraft(d);
    }
    if (!active && drafts.size) select([...drafts.values()][0]);
    invalidate();
  }
  window.ClosureQueue = { receive, pruneCompleted, complete, reconcile, get busy() { return busy; } };
})();
