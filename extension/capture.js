'use strict';
// GLPI Assistant Bridge 2.4.0 — resilient evidence capture.
// Captured bytes stay in Firefox storage/local and localhost handoffs only.
(() => {
  if (globalThis.__glpiCapture226) return;
  globalThis.__glpiCapture226 = true;

  const STORAGE_KEY = 'captureState22';
  const MAX_FILES = 30;
  const MAX_FILE = 8 * 1024 * 1024;
  const MAX_TOTAL = 20 * 1024 * 1024;
  const format = (n) => `E${String(n).padStart(2, '0')}`;
  const pageKey = () => `${location.origin}${location.pathname}`;

  let files = [];
  let promptTimestamp = null;
  let promptText = null;
  let promptSnapshot = [];
  let submittedKeys = new Set();
  let nextOrdinal = 1;
  let capturedPath = pageKey();
  function recentEnough(ts, minutes = 15) { return Date.now() - Number(ts || 0) <= minutes * 60 * 1000; }
  function canPromoteCapturedRoute(fromKey, toKey, updatedAt = Date.now()) {
    if (!fromKey || !toKey || fromKey === toKey || !recentEnough(updatedAt)) return false;
    try {
      const from = new URL(fromKey);
      const to = new URL(toKey);
      if (from.origin !== to.origin) return false;
      const oldPath = from.pathname.replace(/\/$/, '') || '/';
      const newPath = to.pathname.replace(/\/$/, '') || '/';
      if (from.hostname === 'chatgpt.com') {
        const oldHasConversation = /\/c\/[^/]+/.test(oldPath);
        const newHasConversation = /\/c\/[^/]+/.test(newPath);
        if (!oldHasConversation && newHasConversation) {
          const parent = newPath.replace(/\/c\/[^/]+.*$/, '') || '/';
          return oldPath === '/' || oldPath === parent || parent.startsWith(oldPath + '/');
        }
      }
      if (from.hostname === 'gemini.google.com') {
        const oldBase = oldPath === '/app' || oldPath === '/';
        const newConversation = /^\/app\/[^/]+/.test(newPath);
        if (oldBase && newConversation) return true;
      }
      return false;
    } catch { return false; }
  }

  function promoteCapturedRouteIfSafe(current = pageKey(), updatedAt = Date.now()) {
    if (capturedPath === current) return true;
    if (!files.length || !canPromoteCapturedRoute(capturedPath, current, updatedAt)) return false;
    capturedPath = current;
    persistSoon();
    status('A conversa foi criada nesta mesma aba; os prints do primeiro envio foram preservados e migrados para o chamado atual.');
    return true;
  }

  let pending = Promise.resolve();
  let ready = null;
  let host = null;
  let root = null;
  let saveTimer = null;
  let inputScanTimer = null;
  const inputSignatures = new WeakMap();
  const deliveredAssignments = new Map();

  function status(text) {
    if (!root) return;
    root.getElementById('status').textContent = text;
    root.getElementById('toggle').title = text;
  }

  function compactPersisted() {
    return {
      page: capturedPath, next_ordinal: nextOrdinal, prompt_timestamp:promptTimestamp, prompt_text:promptText, prompt_snapshot:promptSnapshot, submitted_keys:[...submittedKeys],
      updated_at: Date.now(),
      files: files.map((f) => ({
        key: f.key, ref: f.ref, name: f.name, size: f.size, type: f.type, data: f.data,
        id: f.id, role: f.role, ticket_id: Number(f.ticket_id || 0), created_at: Number(f.created_at || Date.now()),
      })),
    };
  }

  function persistSoon() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        if (files.length || nextOrdinal > 1) await browser.storage.local.set({ [STORAGE_KEY]: compactPersisted() });
        else await browser.storage.local.remove(STORAGE_KEY);
      } catch (error) {
        status(`Não consegui persistir os prints no Firefox: ${error.message}`);
      }
    }, 120);
  }

  async function restore(reload = false) {
    try {
      const stored = (await browser.storage.local.get(STORAGE_KEY))[STORAGE_KEY];
      if (!stored || !Array.isArray(stored.files) || (stored.page !== pageKey() && !canPromoteCapturedRoute(stored.page,pageKey(),stored.updated_at))) return;
      if(!promptTimestamp){
        promptTimestamp=stored.prompt_timestamp||null;promptText=stored.prompt_text||null;promptSnapshot=stored.prompt_snapshot||[];
        submittedKeys=new Set(stored.submitted_keys||(!stored.prompt_timestamp?stored.files.map(f=>f.key):[]));
      }else{
        // A user may submit while asynchronous storage restoration is still pending.
        (stored.submitted_keys||stored.files.map(f=>f.key)).forEach(key=>submittedKeys.add(key));
      }
      const restored = stored.files.filter((f) => f && /^image\/(png|jpeg|webp)$/.test(f.type || '') && f.data)
        .map((f) => ({ ...f, created_at: Number(f.created_at || stored.updated_at || Date.now()) }));
      // Never overwrite files collected while storage was being read.
      const fresh = new Map(files.map(f => [f.key, f]));
      files = [...restored.filter(f => !fresh.has(f.key)), ...fresh.values()];
      nextOrdinal=Math.max(Number(stored.next_ordinal)||1,...files.map(f=>Number(String(f.ref||'').slice(1))+1));
      for(const f of files)if(!f.ref)f.ref='A'+String(nextOrdinal++).padStart(2,'0');
      capturedPath = pageKey();
      if (files.length) {
        render();
        status(`${files.length} print(s) restaurado(s) após recarregar a aba.`);
      }
    } catch (error) {
      status(`Falha ao restaurar prints: ${error.message}`);
    }
  }

  function selectOptions(select, file) {
    const values = [['auto', 'Contexto / não identificado'], ['', 'Contexto'], ...Array.from({ length: Math.max(files.length, 20) }, (_, i) => [format(i + 1), format(i + 1)])];
    for (const [value, text] of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      select.append(option);
    }
    select.value = file.id ?? 'auto';
  }

  function mount() {
    if (host?.isConnected || !document.documentElement) return;
    host = document.createElement('div');
    host.id = 'glpi-original-prints';
    host.style.cssText = 'position:fixed;right:12px;top:76px;z-index:2147483645';
    root = host.attachShadow({ mode: 'closed' });
    document.documentElement.append(host);
    root.innerHTML = `
      <style>
        :host{all:initial}*{box-sizing:border-box}button,input,select,textarea{font:inherit}textarea{width:100%;padding:10px;border:1px dashed #718bbb;border-radius:9px;background:#101d34;color:#fff;resize:vertical}
        #toggle{float:right;min-width:32px;min-height:32px;background:linear-gradient(135deg,#07111f,#132c4c);color:#ecfbff;border:1px solid #4bcfff;border-radius:11px;cursor:pointer;font:700 14px system-ui;box-shadow:0 0 24px #2da8ff33}
        section{clear:both;font:13px/1.45 system-ui;color:#eff9ff;background:linear-gradient(160deg,#07101d 0%,#101a30 70%,#901434 100%);border:1px solid #5178ad;border-radius:14px;width:330px;max-width:92vw;box-shadow:0 18px 60px #000a,0 0 34px #498cff22;padding:15px;margin-top:8px}
        summary{cursor:pointer;font-weight:800;color:#f8fdff}p{font-size:12px;color:#aebfd4;margin:7px 0}#list{max-height:220px;overflow:auto;margin-top:8px}
        article{display:grid;grid-template-columns:70px 1fr;gap:9px;align-items:center;margin:8px 0;padding:8px;border:1px solid #ffffff16;border-radius:10px;background:#07101d99}
        img{width:70px;height:58px;object-fit:contain;background:#030711;border-radius:7px;border:1px solid #ffffff12}
        .meta{min-width:0;display:grid;grid-template-columns:1fr 110px;gap:6px}.meta small{grid-column:1/-1;display:block;overflow-wrap:anywhere;color:#c8d8e8;font-size:10px}
        button,input,select{border:1px solid #607b9d;border-radius:7px;padding:7px 8px;background:#132039;color:#fff}button{cursor:pointer;margin:4px 3px 0 0}button.primary{background:linear-gradient(135deg,#eefdff,#86dcff 56%,#998cff);color:#07111f;border-color:#fff}input.ticket{width:100%;min-width:0}select{width:100%}
        #status{white-space:pre-wrap;border-top:1px solid #ffffff12;padding-top:8px}.toolbar{display:flex;gap:5px;flex-wrap:wrap}.manual{width:100%;margin-top:8px}
      </style>
      <button id="toggle" aria-label="Prints do GLPI Assistant" aria-expanded="false">📎</button>
      <section hidden>
        <details open><summary>Prints deste chat</summary>
          <p>A01, A02… preservam a ordem. A IA indica o chamado e a evidência. Contexto não é enviado como prova.</p>
          <textarea id="pastebox" rows="2" placeholder="Clique aqui e cole seu print (Ctrl+V)" aria-label="Colar imagem"></textarea>
          <input id="manual" class="manual" type="file" multiple accept="image/png,image/jpeg,image/webp" aria-label="Adicionar prints">
          <div id="list"></div>
          <div class="toolbar"><button id="number">Numerar E01…</button><button id="bind">Vincular sem ticket</button><button id="cleanup">Limpar antigos</button><button id="clear">Descartar tudo</button></div>
          <p id="status" role="status">Capturador ativo.</p>
        </details>
      </section>`;
    const toggle = root.getElementById('toggle');
    const panel = root.querySelector('section');
    toggle.onclick = () => { panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); };
    root.getElementById('pastebox').addEventListener('paste', event => { const incoming = transferFiles(event.clipboardData); if (incoming.length) { event.preventDefault(); enqueue(incoming); } });
    root.getElementById('manual').onchange = (event) => enqueue(event.target.files);
    root.getElementById('number').onclick = () => { files.forEach((f, i) => { f.id = format(i + 1); }); render(); persistSoon(); };
    root.getElementById('bind').onclick = () => {
      const raw = prompt('Vincular prints sem número ao chamado #');
      const id = Number(String(raw || '').replace(/\D/g, ''));
      if (!Number.isSafeInteger(id) || id <= 0) return;
      files.filter((f) => !f.ticket_id).forEach((f) => { f.ticket_id = id; });
      render(); persistSoon(); status(`Prints sem vínculo associados ao chamado #${id}.`);
    };
    root.getElementById('cleanup').onclick = async () => { try { const r = await browser.runtime.sendMessage({ type: 'bridge:evidence:cleanup', force: false }); await restore(true); status(`${r.removed || 0} print(s) expirado(s) removido(s).`); } catch (error) { status(error.message); } };
    root.getElementById('clear').onclick = () => { files = []; deliveredAssignments.clear(); render(); persistSoon(); status('Prints descartados.'); };
  }

  function render() {
    mount();
    if (!root) return;
    const toggle = root.getElementById('toggle');
    toggle.textContent = `📎${files.length ? ` ${files.length}` : ''}`;
    const list = root.getElementById('list');
    list.replaceChildren();
    files.forEach((f) => {
      const row = document.createElement('article');
      const img = document.createElement('img');
      const meta = document.createElement('div');
      const name = document.createElement('small');
      const select = document.createElement('select');
      const ticket = document.createElement('input');
      img.src = `data:${f.type};base64,${f.data}`;
      img.alt = f.name;
      name.textContent = `${f.ref || ""} · ${f.name} · ${Math.max(1, Math.round(f.size / 1024))} KiB`;
      meta.className = 'meta';
      selectOptions(select, f);
      select.setAttribute('aria-label', `Destino de ${f.name}`);
      select.onchange = () => { f.id = select.value; persistSoon(); status('Associação atualizada; tentando completar o handoff.'); if (ready) ready(Number(f.ticket_id || 0)); };
      ticket.className = 'ticket';
      ticket.inputMode = 'numeric';
      ticket.placeholder = 'Chamado #';
      ticket.value = f.ticket_id || '';
      ticket.setAttribute('aria-label', `Chamado de ${f.name}`);
      ticket.onchange = () => { f.ticket_id = Number(String(ticket.value || '').replace(/\D/g, '')) || 0; ticket.value = f.ticket_id || ''; persistSoon(); if (ready) ready(Number(f.ticket_id || 0)); };
      meta.append(name, select, ticket);
      row.append(img, meta);
      list.append(row);
    });
  }

  async function collect(incoming) {
    if (!incoming.length) return;
    const current = pageKey();
    if (capturedPath !== current && files.length && !promoteCapturedRouteIfSafe(current)) {
      status('A conversa mudou. Os prints anteriores foram preservados no storage; descarte ou volte à conversa original.');
      return;
    }
    capturedPath = current;
    for (const file of incoming) {
      if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type || '')) continue;
      let key = `${file.name}|${file.size}|${file.lastModified}`;
      const total = files.reduce((n, f) => n + Number(f.size || 0), 0);
      if (file.size > MAX_FILE || total + file.size > MAX_TOTAL || files.length >= MAX_FILES) {
        status('Limite: 30 prints, 8 MiB por arquivo e 20 MiB no total.');
        continue;
      }
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1]);
        reader.onerror = () => reject(Error(`Não foi possível ler ${file.name}`));
        reader.readAsDataURL(file);
      });
      if (files.some(f => f.data === data)) continue;
      const match = /(?:^|[-_ ])(E\d{2,3})(?:\.|[-_ ])/i.exec(file.name);
      const ticketMatch = /(?:^|[-_ ])(\d{5,8})(?:[-_ ])/i.exec(file.name);
      const ref='A'+String(nextOrdinal++).padStart(2,'0');key+='|'+ref;
      files.push({ key, ref, name: file.name, size: file.size, type: file.type, data, id: match?.[1]?.toUpperCase() || 'auto', ticket_id: Number(ticketMatch?.[1] || 0), created_at: Date.now() });
    }
    render();
    persistSoon();
    status(`${files.length} print(s) disponível(is). Sem identificação = contexto; selecione E01… apenas nas evidências.`);
    if (ready) setTimeout(() => ready(0), 0);
  }

  function transferFiles(transfer) {
    const list = [...(transfer?.files || [])];
    if (list.length) return list;
    return [...(transfer?.items || [])].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
  }

  function enqueue(list) {
    const incoming = [...(list || [])];
    if (!incoming.length) return;
    pending = pending.then(() => collect(incoming)).catch((error) => status(error.message));
  }

  function scanFileInputs() {
    for (const input of document.querySelectorAll('input[type="file"]')) {
      const list = [...(input.files || [])];
      if (!list.length) continue;
      const signature = list.map((f) => `${f.name}|${f.size}|${f.lastModified}`).join('::');
      if (inputSignatures.get(input) === signature) continue;
      inputSignatures.set(input, signature);
      enqueue(list);
    }
  }

  document.addEventListener('change', (event) => {
    const input = event.composedPath().find((x) => x instanceof HTMLInputElement && x.type === 'file');
    if (input?.files) enqueue(input.files);
  }, true);
  document.addEventListener('input', (event) => {
    const input = event.composedPath().find((x) => x instanceof HTMLInputElement && x.type === 'file');
    if (input?.files) enqueue(input.files);
  }, true);
  document.addEventListener('paste', (event) => enqueue(transferFiles(event.clipboardData)), true);
  document.addEventListener('drop', (event) => enqueue(transferFiles(event.dataTransfer)), true);

  // Last-chance snapshot before React/SPA submit handlers clear or replace the
  // file input. Capture phase runs before the page's normal click/keydown path.
  function looksLikeSendControl(target) {
    const el = target instanceof Element ? target.closest('button,[role="button"]') : null;
    if (!el) return false;
    const hint = `${el.getAttribute('data-testid') || ''} ${el.getAttribute('aria-label') || ''} ${el.textContent || ''}`;
    return /send-button|send message|enviar mensagem|send prompt|enviar/i.test(hint);
  }
  function markPrompt(){
    const editor=document.querySelector('#prompt-textarea,rich-textarea [contenteditable="true"],textarea[placeholder]');
    const text=String(editor?.value||editor?.innerText||editor?.textContent||'').trim();
    if(!text)return;
    // Pointerdown and click are one submission. Only a later prompt consumes its images.
    if(text===promptText&&Date.now()-Date.parse(promptTimestamp||'')<2000)return;
    promptSnapshot.forEach(key=>submittedKeys.add(key));
    promptText=text;promptTimestamp=new Date().toISOString();
    const snapshot=()=>files.filter(f=>!submittedKeys.has(f.key)).map(f=>f.key);
    promptSnapshot=snapshot();
    pending.then(()=>{promptSnapshot=snapshot();persistSoon();});
    persistSoon();
  }
  document.addEventListener('pointerdown', (event) => { if (looksLikeSendControl(event.target)) {scanFileInputs();markPrompt();} }, true);
  document.addEventListener('click', (event) => { if (looksLikeSendControl(event.target)) {scanFileInputs();markPrompt();} }, true);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing) return;
    const editor=event.target instanceof Element && event.target.closest('textarea,[contenteditable="true"]');
    if(editor){scanFileInputs();markPrompt();}
  }, true);

  const previewSeen = new WeakMap();
  let previewBusy = false;
  async function scanComposerPreviews() {
    if (previewBusy || document.hidden) return;
    const editor = document.querySelector('#prompt-textarea,rich-textarea [contenteditable="true"],textarea[placeholder]');
    const composer = editor?.closest('form') || editor?.closest('rich-textarea')?.parentElement;
    if (!composer) return;
    previewBusy=true;
    try {
      for (const img of composer.querySelectorAll('img')) {
        const src=img.currentSrc||img.src;
        if (!src || previewSeen.get(img)===src || !img.complete || img.naturalWidth<72 || img.naturalHeight<52) continue;
        if (img.naturalWidth*img.naturalHeight>16000000) continue;
        try {
          const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
          canvas.getContext('2d').drawImage(img,0,0);
          const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
          if (!blob || blob.size>MAX_FILE) continue;
          const hint=img.alt||img.title||'';
          const name=/[^/\\]+\.(?:png|jpe?g|webp)$/i.test(hint)?hint:'print-anexado.png';
          enqueue([new File([blob],name,{type:'image/png',lastModified:0})]);
          previewSeen.set(img,src);
        } catch { /* Cross-origin previews cannot be read; original file events remain active. */ }
      }
    } finally {previewBusy=false;}
  }
  setInterval(scanComposerPreviews,500);
  const watchedInputs = new WeakSet();
  function watchInputs() {
    for (const input of document.querySelectorAll('input[type="file"]')) {
      if (watchedInputs.has(input)) continue;
      watchedInputs.add(input);
      input.addEventListener('change', () => enqueue(input.files), true);
      input.addEventListener('input', () => enqueue(input.files), true);
    }
    mount();
    scanFileInputs();
  }
  if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(watchInputs).observe(document, { childList: true, subtree: true });
  }
  document.addEventListener('DOMContentLoaded', watchInputs, { once: true });
  watchInputs();

  inputScanTimer = setInterval(scanFileInputs, 650);
  for (const delay of [0, 80, 180, 350, 700, 1200, 2200]) setTimeout(scanFileInputs, delay);
  window.addEventListener('pageshow', () => { mount(); scanFileInputs(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { mount(); scanFileInputs(); } });

  globalThis.glpiCapture = {
    hasPending: () => files.length > 0,
    stats: () => ({ count: files.length, bytes: files.reduce((n, f) => n + Number(f.size || 0), 0), page: capturedPath, next_ordinal: nextOrdinal, oldest_at: files.length ? Math.min(...files.map(f => Number(f.created_at || Date.now()))) : null, retention_hours: 12 }),
    onReady: (fn) => { ready = fn; },
    async routePackets(packets){
      await pending;
      if(capturedPath!==pageKey()&&!promoteCapturedRouteIfSafe(pageKey()))return;
      const result=globalThis.GLPiEvidencePlan.route(packets,files);
      for(const a of result.assignments){const f=files.find(f=>f.key===a.key);f.ticket_id=a.ticket;f.id=a.evidence;}
      if(result.assignments.length){persistSoon();render();}
      if(result.issues.length)status('Associação ambígua: '+result.issues.join(', ')+'. Revise o vínculo; prints preservados.');
      return result;
    },
    async proactiveFor(raw, userText) {
      await pending;
      if(capturedPath!==pageKey()&&!promoteCapturedRouteIfSafe(pageKey()))return {images:[],prompt_timestamp:null};
      if(!promptText||!String(userText||'').includes(promptText))return {images:[],prompt_timestamp:null};
      const ordered=promptSnapshot.map(key=>files.find(f=>f.key===key)).filter(Boolean);
      const images=[];
      for(const e of raw.evidence||[]){
        if(e.role==='context')continue;
        const f=ordered[Number(e.source_index)-1];
        if(f&&f.role!=='context')images.push({draft_ref:raw.draft_ref,id:e.id,data:f.data});
      }
      return {images,prompt_timestamp:promptTimestamp};
    },
    async packetFor(id, closure = '', { multiTicket = false } = {}) {
      await pending;
      const required = [...new Set([...String(closure).matchAll(/\[EVID[ÊE]NCIA\s*:\s*(E\d{2,3})\s*\]/gi)].map((m) => m[1].toUpperCase()))]
        .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
      if (!required.length) return { blocked: false, images: [] };
      if (capturedPath !== pageKey() && !promoteCapturedRouteIfSafe(pageKey())) {
        status(`Os prints pertencem a outra conversa. Volte à conversa original ou descarte-os antes de enviar #${id}.`);
        return { blocked: true, images: [] };
      }
      // Associate only explicit filename labels in the structured output, never by image order.
      for (const file of files) {
        if (file.id !== 'auto' || file.role === 'context') continue;
        const labels = [...new Set([...String(closure).matchAll(/^\s*EVIDENCIA_ARQUIVO\s*:\s*(E\d{2,3})\s*\|\s*(.+?)\s*$/gmi)].filter(m => m[2] === file.name).map(m => m[1].toUpperCase()))];
        const duplicateName = files.filter(f => f.name === file.name).length > 1;
        if (!multiTicket && !duplicateName && labels.length === 1 && required.includes(labels[0])) {
          file.id = labels[0]; file.ticket_id = Number(id);
        }
      }
      const scoped = files.filter((f) => Number(f.ticket_id) === Number(id) || (!multiTicket && !f.ticket_id));
      // Em múltiplos chamados, evidência sem ticket nunca é adivinhada. Vincule cada print ao chamado correto.
      if (multiTicket && files.some((f) => !f.ticket_id) && !scoped.length) {
        status(`#${id}: texto será enviado agora. Vincule os prints ao chamado correto no clips; eles entram depois.`);
        root.getElementById('toggle').textContent = `📎 ${files.length} !`;
        return { blocked: false, pending: true, images: [] };
      }
      const planned = globalThis.GLPiEvidencePlan?.plan(required, scoped);
      if (!planned) {
        status('Planejador de evidências indisponível; texto preservado e prints mantidos para associação manual.');
        return { blocked: false, pending: true, images: [] };
      }
      const assigned = planned.assigned;
      if (planned.ambiguous || planned.pending) {
        const detail = planned.remaining.length ? ` faltam ${planned.remaining.join(', ')}` : '';
        status(`#${id}: ${assigned.length} print(s) associado(s) com segurança;${detail || ' há arquivos extras/duplicados para revisar'}.`);
        root.getElementById('toggle').textContent = `📎 ${files.length}${planned.pending || planned.ambiguous ? ' !' : ''}`;
      }
      deliveredAssignments.set(Number(id), new Set(assigned.map((x) => x.file.key)));
      return { blocked: false, pending: planned.pending, suppressRecovery: files.length > 0, images: assigned.map((x) => ({ id: x.id, data: x.file.data })) };
    },
    async delivered(id) {
      const keys = deliveredAssignments.get(Number(id));
      if (keys?.size) files = files.filter((f) => !keys.has(f.key));
      deliveredAssignments.delete(Number(id));
      render();
      persistSoon();
      status(`#${id} confirmado pelo Assistant. Prints usados foram removidos da fila local.`);
    },
    async repair() {
      mount();
      scanFileInputs();
      await pending;
      return { ok: true, count: files.length };
    },
    async syncFromStorage() {
      await restore(true);
      render();
      status(files.length ? `${files.length} print(s) preservado(s) após limpeza automática.` : 'Fila de prints limpa.');
      return { ok: true, count: files.length };
    },
  };

  mount();
  pending = restore().then(() => { if (ready && files.length) setTimeout(() => ready(0), 0); });
  scanFileInputs();
  status('Bridge 2.4.0: evidência parcial, seleção, colagem, arraste e varredura periódica ativas.');
})();
