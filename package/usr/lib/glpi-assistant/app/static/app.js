const $ = (s) => document.querySelector(s);
let files = [];
let parsed = null;
let currentTicket = null;
let loadedTicketId = 0;
let currentPlan = null;
let analyzeTimer = null;
let planTimer = null;
let analyzeSeq = 0;
let planSeq = 0;
let fileObjectUrls = [];
let fileObjectUrlById = new Map();
let pendingHandoff = null;
let bridgeEventSource = null;
let bridgeInboxItems = [];
let bridgeStatusTimer = null;
let bridgeInboxTimer = null;
let bridgeRecoveryTimer = null;
let lastBridgeImport = null;
let handoffSequence = 0;
let executionBusy = false;
let reviewTimer = null;
let closureReview = null;
const catalogTimers = {};
const catalogCache = new Map();

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const raw = await r.text();
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error(`Resposta inválida da aplicação (HTTP ${r.status}). Consulte o log do serviço.`);
  }
  if (!r.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
    throw new Error(detail);
  }
  return data;
}

function jsonOpts(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

function log(x) {
  $('#log').textContent = typeof x === 'string' ? x : JSON.stringify(x, null, 2);
}

function esc(s = '') {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  }[c]));
}

function normalizeText(s = '') {
  let text = String(s).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (/\[GLPI_ASSISTANT\s*:\s*\d+\s*\]\s*\\(?:r\\n|n|r)/i.test(text) || /\[TAREFA:T\d+\]\s*\\(?:r\\n|n|r)/i.test(text)) {
    text = text.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n').replace(/\\r/g, '\n');
  }
  return text;
}

let fileSeq = 0;
function makeFileEntry(file) {
  fileSeq += 1;
  const random = (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2));
  return { id: `file_${Date.now().toString(36)}_${fileSeq}_${random}`, file };
}

function fileEntryById(id) {
  return files.find((entry) => entry.id === id) || null;
}

function evidenceFileName(id) {
  return fileEntryById(id)?.file?.name || '';
}

function formatDuration(seconds) {
  const n = Math.max(0, Number(seconds) || 0);
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  if (h && s) return `${h}h ${m}m ${s}s`;
  if (h) return `${h}h ${m}m`;
  if (s) return `${m}m ${s}s`;
  return `${m} min`;
}

function renderQualityState() {
  const summary = $('#qualitySummary');
  const warnings = $('#qualityWarnings');
  if (!summary || !warnings) return;
  if (!parsed) {
    summary.textContent = 'Aguardando análise.';
    warnings.className = 'quality-warnings muted';
    warnings.textContent = 'Modalidade e nível são obrigatórios em cada tarefa enviada.';
    return;
  }
  const quality = parsed.quality || {};
  const total = formatDuration(quality.total_actiontime || parsed.tasks.reduce((acc, t) => acc + (Number(t.actiontime) || 0), 0));
  const levels = (quality.levels || [...new Set(parsed.tasks.map((t) => t.nivel).filter(Boolean))]).join(' / ') || '—';
  const modalities = (quality.modalities || [...new Set(parsed.tasks.map((t) => t.modalidade).filter(Boolean))]).join(' / ') || '—';
  summary.textContent = `${parsed.tasks.length} tarefa(s) · ${modalities} · ${levels} · ${total}`;
  const items = quality.warnings || [];
  warnings.className = `quality-warnings ${items.length ? 'warning' : 'ok'}`;
  const autoGroups = quality.auto_added_groups || [];
  warnings.textContent = items.length
    ? items.join(' · ')
    : quality.partial_closure
      ? `Fechamento parcial válido (${(quality.task_ids || []).join(', ')}). O Assistant vai comparar com o histórico e lançar somente o que faltar.`
      : autoGroups.length
        ? `Contrato completo. Grupos operacionais garantidos automaticamente: ${autoGroups.join(', ')}.`
        : 'Contrato completo. Tempos, modalidade e nível prontos para revisão.';
}

function updateWorkflowRail() {
  const steps = [...document.querySelectorAll('#workflowRail [data-step]')];
  if (!steps.length) return;
  const evidenceReady = !!parsed && missingEvidence().length === 0;
  const state = {
    ticket: ticketIsLoaded(),
    closure: !!parsed,
    evidence: evidenceReady,
    plan: !!currentPlan && evidenceReady,
  };
  const order = ['ticket', 'closure', 'evidence', 'plan'];
  const current = order.find((key) => !state[key]) || 'plan';
  steps.forEach((el) => {
    const key = el.dataset.step;
    el.classList.toggle('done', !!state[key]);
    el.classList.toggle('current', key === current && !state[key]);
  });
}

function structuredClosureReadiness(text) {
  const source = normalizeText(text);
  const opens = [...source.matchAll(/\[TAREFA:(T\d+)\]/gi)];
  const closes = (source.match(/\[\/TAREFA\]/gi) || []).length;
  if (!opens.length) {
    return { ready: false, reason: 'Aguardando ao menos uma tarefa.' };
  }
  if (closes < opens.length) {
    return { ready: false, reason: `Aguardando conclusão da tarefa atual (${closes}/${opens.length} fechada(s)).` };
  }
  if (closes > opens.length) {
    return { ready: false, reason: 'Há mais fechamentos [/TAREFA] do que tarefas abertas.' };
  }
  const ids = opens.map((m) => String(m[1] || '').toUpperCase());
  if (ids.some((id) => !/^T(?:0[1-9]|[1-9][0-9]{1,2})$/.test(id))) {
    return { ready: false, reason: 'Use identificadores T01, T02… T999.' };
  }
  if (new Set(ids).size !== ids.length) {
    return { ready: false, reason: 'Há identificadores de tarefa repetidos no fechamento.' };
  }
  const order = ids.map((id) => Number(id.slice(1)));
  if (order.some((value, index) => index > 0 && value < order[index - 1])) {
    return { ready: false, reason: 'Mantenha as tarefas em ordem numérica crescente.' };
  }
  return { ready: true, reason: '' };
}

function durationInput(seconds) {
  const n = Math.max(0, Number(seconds) || 0);
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  const hh = String(h).padStart(2, '0');
  const mm = String(m).padStart(2, '0');
  return s ? `${hh}:${mm}:${String(s).padStart(2, '0')}` : `${hh}:${mm}`;
}

function setWorkflowStatus(message, kind = 'muted') {
  const el = $('#workflowStatus');
  if (!el) return;
  const busy = kind === 'muted' && /^(analisando|gerando|interpretando|consultando|aplicando|excluindo|validando|carregando|preparando|reprocessando|sincronizando|procurando)/i.test(String(message || ''));
  el.className = `small workflow-status ${kind}${busy ? ' busy' : ''}`;
  el.textContent = message;
}

function renderPlanPlaceholder(message = 'Analise o fechamento e carregue o chamado.') {
  const root = $('#plan');
  root.className = 'plan muted';
  root.textContent = message;
}

function invalidatePlan(message = '') {
  planSeq += 1;
  currentPlan = null;
  $('#executeBtn').disabled = true;
  if (message) setWorkflowStatus(message, 'muted');
  updateWorkflowRail();
}

function currentTicketId() {
  return parseInt($('#ticketId').value, 10) || 0;
}

function ticketIsLoaded() {
  return !!currentTicket && currentTicket.id === currentTicketId();
}

function evidenceMap() {
  const m = {};
  document.querySelectorAll('[data-evidence]').forEach((s) => {
    if (s.value) m[s.dataset.evidence] = s.value;
  });
  return m;
}

function requiredEvidence() {
  const ids = currentPlan?.required_evidence_ids ?? parsed?.evidence_ids ?? [];
  return new Set(ids);
}

function missingEvidence() {
  const m = evidenceMap();
  return [...requiredEvidence()].filter((x) => !m[x]);
}

function updateEvidenceState() {
  const dz = $('#dropzone');
  const badge = $('#evidenceState');
  const count = parsed ? requiredEvidence().size : null;

  if (!parsed) {
    dz.classList.remove('disabled');
    dz.setAttribute('aria-disabled', 'false');
    dz.innerHTML = '📎 Anexar prints · clique, cole ou arraste<input id="filePicker" type="file" multiple accept="image/png,image/jpeg,image/webp" hidden>';
    bindFilePicker();
    if (badge) { badge.className = 'badge neutral'; badge.textContent = 'Aguardando análise'; }
    return;
  }

  if (count === 0) {
    dz.classList.remove('disabled');
    dz.setAttribute('aria-disabled', 'false');
    dz.innerHTML = '📎 Adicionar print esquecido · associe-o a uma tarefa antes de aplicar<input id="filePicker" type="file" multiple accept="image/png,image/jpeg,image/webp" hidden>';
    bindFilePicker();
    if (badge) { badge.className = 'badge success'; badge.textContent = '0 imagens necessárias'; }
    return;
  }

  dz.classList.remove('disabled');
  dz.setAttribute('aria-disabled', 'false');
  dz.innerHTML = `📎 Anexar prints · clique, cole ou arraste · ${count} evidência(s) esperada(s)<input id="filePicker" type="file" multiple accept="image/png,image/jpeg,image/webp" hidden>`;
  bindFilePicker();
  const missing = missingEvidence().length;
  if (badge) {
    badge.className = `badge ${missing ? 'warning' : 'success'}`;
    badge.textContent = missing ? `${missing} pendente(s)` : `${count}/${count} mapeadas`;
  }
}

function prerequisitesForPlan() {
  if (!ticketIsLoaded()) return { ok: false, reason: 'Procure/carregue o chamado primeiro.' };
  if (!parsed) return { ok: false, reason: 'Cole um fechamento válido para analisar as tarefas.' };
  // O Dry Run precisa acontecer ANTES de bloquear por evidência: ele consulta
  // o histórico e descobre quais tarefas já existem. Assim não exigimos print
  // de T01–T03 quando apenas T04/T05 realmente precisam ser lançadas.
  return { ok: true };
}

function revokeFileUrls() {
  for (const url of fileObjectUrls) URL.revokeObjectURL(url);
  fileObjectUrls = [];
  fileObjectUrlById.clear();
}

function filePreviewUrl(entry) {
  if (!entry) return '';
  let url = fileObjectUrlById.get(entry.id);
  if (!url) {
    url = URL.createObjectURL(entry.file);
    fileObjectUrlById.set(entry.id, url);
    fileObjectUrls.push(url);
  }
  return url;
}

function evidenceLabelForFile(entry, index = 0) {
  const mapping = evidenceMap();
  const mapped = Object.entries(mapping).find(([, fileId]) => fileId === entry.id)?.[0];
  if (mapped) return mapped;
  const stem = String(entry?.file?.name || '').match(/^(E\d{2,3}|CONTEXTO)(?:[._ -]|$)/i)?.[1];
  return stem ? stem.toUpperCase() : `Print ${index + 1}`;
}

function openEvidencePreview(entry, index = 0) {
  const dialog = $('#evidencePreviewDialog');
  const img = $('#evidencePreviewImage');
  if (!dialog || !img || !entry) return;
  img.src = filePreviewUrl(entry);
  img.alt = `Prévia ampliada de ${entry.file.name}`;
  $('#evidencePreviewTitle').textContent = evidenceLabelForFile(entry, index);
  $('#evidencePreviewName').textContent = entry.file.name;
  if (typeof dialog.showModal === 'function') dialog.showModal();
}

function renderClosureEvidencePreview() {
  const root = $('#closureEvidencePreview');
  const strip = $('#closurePreviewStrip');
  const count = $('#closurePreviewCount');
  if (!root || !strip || !count) return;
  strip.replaceChildren();
  if (!files.length) {
    root.classList.add('hidden');
    count.textContent = '';
    return;
  }
  root.classList.remove('hidden');
  count.textContent = ` · ${files.length}`;
  files.forEach((entry, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'closure-preview-item';
    button.setAttribute('aria-label', `Ampliar ${evidenceLabelForFile(entry, index)}: ${entry.file.name}`);
    const img = document.createElement('img');
    img.src = filePreviewUrl(entry);
    img.alt = '';
    const meta = document.createElement('span');
    meta.className = 'closure-preview-meta';
    const label = document.createElement('strong');
    label.textContent = evidenceLabelForFile(entry, index);
    const name = document.createElement('small');
    name.textContent = entry.file.name;
    meta.append(label, name);
    button.append(img, meta);
    button.addEventListener('click', () => openEvidencePreview(entry, index));
    strip.appendChild(button);
  });
}

function clearDraft() {
  clearTimeout(analyzeTimer);
  clearTimeout(planTimer);
  analyzeSeq += 1;
  planSeq += 1;
  parsed = null;
  currentPlan = null;
  files = [];
  $('#closure').value = '';
  revokeFileUrls();
  renderFiles();
  renderTasks();
  updateEvidenceState();
  renderPlanPlaceholder();
  $('#executeBtn').disabled = true;
  setWorkflowStatus('Cole o fechamento: a análise será automática.', 'muted');
  renderQualityState();
  updateWorkflowRail();
  resetClosureReview();
}

function resetForAnotherTicket() {
  if (executionBusy) return;
  handoffSequence++;
  ticketLoadSequence++;
  existingTaskLoadRevision++;
  lastBridgeImport = null;
  clearDraft();
  window.resetWorkbenchEditor?.();
  if ($('#wbAfterMode')) $('#wbAfterMode').value = 'tasks';
  if ($('#wbAfterSolution')) $('#wbAfterSolution').value = '';
  $('#executeBtn').textContent = 'Aplicar no GLPI';
  currentTicket = null;
  loadedTicketId = 0;
  $('#ticketId').value = '';
  $('#ticketSummary').textContent = 'Nenhum chamado carregado.';
  $('#refreshTicket').disabled = true;
  $('#refreshTasks').disabled = true;
  if ($('#selectAllTasks')) $('#selectAllTasks').disabled = true;
  if ($('#deleteSelectedTasks')) $('#deleteSelectedTasks').disabled = true;
  $('#existingTasks').className = 'existing-tasks muted';
  $('#existingTasks').textContent = 'Carregue um chamado para visualizar as tarefas.';
  $('#ticketEditor').classList.add('hidden');
  $('#manualTaskCreator').classList.add('hidden');
  log('Pronto para outro chamado.');
  $('#ticketId').focus();
}


function formatConnectionDiagnostics(d) {
  const diag = d?.diagnostics || d || {};
  const profile = diag.active_profile || {};
  const profiles = Array.isArray(diag.profiles) ? diag.profiles : [];
  const entities = Array.isArray(diag.entities) ? diag.entities : [];
  const warnings = Array.isArray(diag.warnings) ? diag.warnings : [];
  const lines = [
    `Autenticação: ${diag.auth_ok === false ? 'FALHOU' : 'OK'}`,
    `user_id: ${diag.user_id ?? d?.user_id ?? 'não identificado'}`,
    `Perfil ativo: ${profile.name || profile.id || 'não identificado'}`,
    `Perfis disponíveis: ${profiles.length}`,
    `Entidades visíveis: ${entities.length}`,
    `entities_id=all: ${diag.all_entities_ok === true ? 'permitido' : diag.all_entities_ok === false ? 'restrito (não impede login)' : 'não testado'}`,
  ];
  if (warnings.length) {
    lines.push('', 'Avisos de compatibilidade:');
    warnings.forEach((w) => lines.push(`- ${w}`));
  }
  return lines.join('\n');
}

function decodeBase64UrlUtf8(value) {
  const normalized = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function extractHandoffFromLocation() {
  const raw = window.location.hash || '';
  if (!raw.startsWith('#handoff=')) return null;
  try {
    const packet = JSON.parse(decodeBase64UrlUtf8(raw.slice('#handoff='.length)));
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    return packet;
  } catch (e) {
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    log(`Handoff inválido: ${e.message}`);
    return null;
  }
}

async function importHandoff(packet, { source = 'Handoff de IA', receivedFiles = null } = {}) {
  if (executionBusy) throw new Error('Aguarde a aplicação atual; pacote preservado na Inbox.');
  const sequence = ++handoffSequence;
  if (!packet || typeof packet !== 'object') throw new Error('Pacote de handoff inválido.');
  const text = normalizeText(packet.closure ?? packet.text ?? '');
  const marker = text.match(/\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]/i);
  const markerTicketId = Number(marker?.[1] || 0);
  const payloadTicketId = Number(packet.ticket_id || packet.ticketId || 0);
  if (payloadTicketId > 0 && markerTicketId > 0 && payloadTicketId !== markerTicketId) {
    throw new Error(`Conflito de chamado: pacote #${payloadTicketId} e marcador #${markerTicketId}.`);
  }
  const ticketId = payloadTicketId || markerTicketId;
  if (!text.trim()) throw new Error('O handoff não contém texto de fechamento.');
  if (!(ticketId > 0)) throw new Error('Número do chamado ausente.');
  const validatedTicket = await fetchTicket(ticketId);
  const importedFiles = receivedFiles ?? (await window.fetchBridgeEvidence?.(packet) || []);
  if (sequence !== handoffSequence || executionBusy) throw new Error('Importação substituída ou aplicação em andamento; pacote preservado na Inbox.');
  clearDraft();
  $('#closure').value = text;
  if (ticketId > 0) {
    $('#ticketId').value = String(ticketId);
    currentTicket = validatedTicket;
    loadedTicketId = ticketId;
    renderTicketSummary(currentTicket);
    if(importedFiles.length)addFiles(importedFiles);
    document.querySelector('.workspace-nav a[href="#operacao"]')?.click();
    window.onWorkbenchTicketLoaded?.(currentTicket);
    loadExistingTasks().catch(e => log(e.message));
  } else {
    throw new Error('Número do chamado ausente. Use [GLPI_ASSISTANT:<ID>] no início do fechamento.');
  }
  setWorkflowStatus(`${source} recebido. Analisando fechamento...`, 'ok');
  scheduleAnalyze(0);
}

async function importClipboardText() {
  if (!navigator.clipboard?.readText) {
    throw new Error('O navegador não liberou leitura da área de transferência. Cole o texto diretamente no campo de fechamento.');
  }
  const raw = (await navigator.clipboard.readText()).trim();
  if (!raw) throw new Error('A área de transferência está vazia.');

  const marker = '#handoff=';
  if (raw.includes(marker)) {
    const encoded = raw.slice(raw.indexOf(marker) + marker.length).split(/[\s#]/)[0];
    const packet = JSON.parse(decodeBase64UrlUtf8(encoded));
    await importHandoff(packet, { source: 'Link legado copiado' });
    return;
  }

  if (raw.startsWith('{')) {
    try {
      const parsedJson = JSON.parse(raw);
      if (parsedJson.closure || parsedJson.text) {
        await importHandoff(parsedJson, { source: 'Pacote de IA copiado' });
        return;
      }
    } catch {}
  }

  await importHandoff({ closure: raw }, { source: 'Clipboard' });
}


function bridgeDraftIsDirty() {
  return !!normalizeText($('#closure')?.value || '').trim() || files.length > 0 || !!currentPlan;
}

function bridgeTimeLabel(value) {
  if (!value) return '—';
  const text = String(value).replace(' ', 'T');
  const parsedDate = new Date(text.endsWith('Z') ? text : `${text}Z`);
  if (Number.isNaN(parsedDate.getTime())) return String(value);
  const seconds = Math.max(0, Math.round((Date.now() - parsedDate.getTime()) / 1000));
  if (seconds < 10) return 'agora';
  if (seconds < 60) return `${seconds}s atrás`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min atrás`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h atrás`;
  return parsedDate.toLocaleString('pt-BR');
}

function renderBridgeStatus(info = {}) {
  const badge = $('#bridgeStatusBadge');
  const hero = $('#bridgeHeroState');
  const paired = !!info.paired;
  const connected = !!info.connected;
  const statusText = connected ? 'Extensão conectada' : paired ? 'Pareado · aguardando contato' : 'Não pareado';

  $('#bridgeStatusText').textContent = statusText;
  $('#bridgeExtensionVersion').textContent = info.extension_version ? `v${info.extension_version}` : '—';
  $('#bridgeLastSeen').textContent = info.last_seen
    ? (info.last_seen_age <= 10 ? 'agora' : `${Math.round(info.last_seen_age)}s atrás`)
    : '—';

  badge.className = `badge ${connected ? 'success' : paired ? 'warning' : 'neutral'}`;
  badge.textContent = connected ? 'Conectado' : paired ? 'Pareado' : 'Não pareado';
  hero.textContent = `IA Bridge · ${connected ? 'Conectado' : paired ? 'Pareado' : 'Offline'}`;
  hero.classList.toggle('connected', connected);
  $('#revokeBridge').disabled = !paired;
}

async function refreshBridgeStatus() {
  try {
    const info = await api('/api/bridge/info');
    renderBridgeStatus(info);
    return info;
  } catch (e) {
    renderBridgeStatus({ paired: false, connected: false });
    $('#bridgeStatusText').textContent = `Bridge indisponível: ${e.message}`;
    return null;
  }
}

async function setBridgeHandoffState(id, status) {
  return api(`/api/bridge/handoff/${Number(id)}/state`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

function bridgeCanSupersedeCurrent(item) {
  if (!lastBridgeImport || !item?.closure) return false;
  const ticketId = Number(item.ticket_id || 0);
  if (!ticketId || ticketId !== Number(lastBridgeImport.ticket_id || 0)) return false;
  if (currentTicketId() && currentTicketId() !== ticketId) return false;

  const current = normalizeText($('#closure')?.value || '').trim();
  const previous = normalizeText(lastBridgeImport.closure || '').trim();
  const incoming = normalizeText(item.closure || '').trim();
  if (!current || current !== previous || incoming === previous) return false;

  // Typical streaming upgrade: the first packet ended at [/TAREFA] and the
  // next packet adds the trailing [ALTERACOES_CHAMADO] block.
  return incoming.startsWith(previous);
}

async function supersedeBridgeHandoff(item) {
  if (executionBusy) return false;
  const sequence = ++handoffSequence;
  const receivedFiles = await window.fetchBridgeEvidence?.(item) || [];
  if(sequence!==handoffSequence || executionBusy || !bridgeCanSupersedeCurrent(item))return false;
  const text = normalizeText(item.closure || '');
  $('#closure').value = text;
  parsed = null;
  currentPlan = null;
  $('#executeBtn').disabled = true;
  renderPlanPlaceholder();
  if(receivedFiles.length)addFiles(receivedFiles);
  renderQualityState();
  updateWorkflowRail();
  lastBridgeImport = {
    id: Number(item.id || 0),
    ticket_id: Number(item.ticket_id || 0),
    closure: text.trim(),
  };
  await setBridgeHandoffState(item.id, 'imported');
  setWorkflowStatus(`∞ Fechamento #${item.ticket_id || '—'} completado automaticamente pelo Browser Bridge. Reanalisando...`, 'ok');
  scheduleAnalyze(0);
  await refreshBridgeInbox();
  return true;
}

async function importBridgeHandoff(item, { force = false, automatic = false } = {}) {
  if (!item?.closure) throw new Error('Handoff recebido sem fechamento.');
  const evidencePending = item.evidence_ready === false;
  const missingEvidence = (item.missing_evidence_ids || []).join(', ');
  if (executionBusy || window.ClosureQueue?.busy) return false;

  // A entrega 3.2.5 é espelhada: a aba em lote recebe/adiciona o chamado e
  // o editor individual sempre passa a representar o pacote mais recente.
  // Isso elimina o estado em que o Bridge "guardava" o fechamento anterior.
  const receivedFiles = await window.fetchBridgeEvidence?.(item) || [];
  let queueImported = false;
  try {
    if (window.ClosureQueue) queueImported = await window.ClosureQueue.receive(item, { activate: false, files: receivedFiles });
  } catch (queueError) {
    setWorkflowStatus(`∞ #${item.ticket_id || '—'} chegou ao editor individual, mas a aba em lote precisa de atenção: ${queueError.message}`, 'warning');
  }

  await importHandoff(item, { source: '∞ IA Browser Bridge', receivedFiles });
  lastBridgeImport = {
    id: Number(item.id || 0),
    ticket_id: Number(item.ticket_id || 0),
    closure: normalizeText(item.closure || '').trim(),
  };
  await setBridgeHandoffState(item.id, 'imported');
  const mirrorNote = queueImported ? ' e adicionado às abas de lote' : '';
  setWorkflowStatus(evidencePending
    ? `∞ Texto do #${item.ticket_id || '—'} recebido e espelhado${mirrorNote}; aguardando ${missingEvidence || 'prints'}.`
    : `∞ Fechamento #${item.ticket_id || '—'} recebido, carregado no editor individual${mirrorNote}.`, evidencePending ? 'warning' : 'ok');
  document.querySelector('.closure-card')?.classList.add('bridge-received-flash');
  setTimeout(() => document.querySelector('.closure-card')?.classList.remove('bridge-received-flash'), 1300);
  await refreshBridgeInbox();
  return true;
}

function renderBridgeInbox(items = []) {
  bridgeInboxItems = items;
  const root = $('#bridgeInbox');
  if (!items.length) {
    root.className = 'bridge-inbox';
    root.innerHTML = '<div class="bridge-inbox-empty">Nenhum fechamento recebido pelo Browser Bridge.</div>';
    return;
  }

  const renderItem = (item) => {
    const statusLabel = item.status === 'pending' ? 'Aguardando' : item.status === 'imported' ? 'Importado' : 'Descartado';
    const pendingClass = item.status === 'pending' ? ' pending' : '';
    const ticket = item.ticket_id ? `#${item.ticket_id}` : 'Sem ticket';
    const sourceRaw = String(item.source || 'IA').toLowerCase();
    const sourceLabel = sourceRaw.includes('gemini') ? 'Gemini' : sourceRaw.includes('chatgpt') ? 'ChatGPT' : 'IA';
    const ready = item.evidence_ready !== false;
    const evidenceLabel = ready
      ? `${item.stored_evidence_count ?? item.evidence_count}/${item.evidence_count} prints prontos`
      : `Faltam ${(item.missing_evidence_ids || []).join(', ') || 'prints'}`;
    return `<article class="bridge-inbox-item${pendingClass}${ready ? '' : ' evidence-missing'}" data-bridge-id="${item.id}">
      <div class="bridge-inbox-main">
        <div class="bridge-inbox-title">∞ ${esc(ticket)} · ${esc(sourceLabel)} · ${esc(statusLabel)}</div>
        <div class="bridge-inbox-meta">${item.task_count} tarefas · <span class="${ready ? 'evidence-ok' : 'evidence-bad'}">${esc(evidenceLabel)}</span> · ${esc(bridgeTimeLabel(item.created_at))}</div>
      </div>
      <div class="bridge-inbox-actions">
        <button type="button" class="secondary compact bridge-queue" data-id="${item.id}">Abrir em aba própria</button>
        ${item.status === 'pending' ? `<button type="button" class="white-action compact bridge-open" data-id="${item.id}">${ready ? 'Abrir' : 'Abrir texto'}</button><button type="button" class="secondary compact bridge-dismiss" data-id="${item.id}">Deixar de lado</button>` : `<button type="button" class="secondary compact bridge-open" data-id="${item.id}">Reabrir</button>`}
        <button type="button" class="ghost compact bridge-delete" data-id="${item.id}">Remover</button>
      </div>
    </article>`;
  };

  root.className = 'bridge-inbox';
  root.tabIndex = 0;
  root.setAttribute('aria-label','Fechamentos recebidos; role para consultar o histórico');
  const active = items.filter(item => item.status === 'pending');
  const history = items.filter(item => item.status !== 'pending');
  root.innerHTML = `<div class="bridge-inbox-summary"><strong>${active.length}</strong> aguardando ação · ${history.length} no histórico</div>
    <div class="bridge-inbox-primary">${active.length ? active.map(renderItem).join('') : '<div class="bridge-inbox-empty">Nenhum fechamento aguardando ação.</div>'}</div>
    ${history.length ? `<details class="bridge-inbox-history"><summary><strong>Histórico recente</strong><span>${history.length} itens</span></summary><div class="bridge-inbox-overflow">${history.map(renderItem).join('')}</div></details>` : ''}`;

  root.querySelectorAll('.bridge-open').forEach((btn) => {
    btn.onclick = async () => {
      const item = bridgeInboxItems.find((x) => Number(x.id) === Number(btn.dataset.id));
      if (!item) return;
      try { await importBridgeHandoff(item, { force: true }); }
      catch (e) { setWorkflowStatus(`Falha ao importar handoff: ${e.message}`, 'error'); log(e.message); }
    };
  });
  root.querySelectorAll('.bridge-queue').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const item = await api(`/api/bridge/handoff/${Number(btn.dataset.id)}`);
        if (await window.ClosureQueue.receive(item)) {
          await setBridgeHandoffState(item.id, 'imported');
          document.querySelector('.workspace-nav a[href="#operacao"]').click();
          document.querySelector('#closureQueue').scrollIntoView({block:'start'});
        }
      } catch (error) { setWorkflowStatus(error.message, 'error'); }
      finally { btn.disabled = false; }
    };
  });
  root.querySelectorAll('.bridge-dismiss').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await setBridgeHandoffState(btn.dataset.id, 'dismissed');
        await refreshBridgeInbox();
      } catch (e) { log(e.message); }
    };
  });
  root.querySelectorAll('.bridge-delete').forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm('Remover este handoff apenas da Inbox local? Isso não altera o GLPI.')) return;
      try {
        await api(`/api/bridge/handoff/${Number(btn.dataset.id)}`, { method: 'DELETE' });
        await refreshBridgeInbox();
      } catch (e) { log(e.message); }
    };
  });
}

async function refreshBridgeInbox({ autoImportLatest = false } = {}) {
  try {
    const data = await api('/api/bridge/inbox?limit=30');
    const items = data.items || [];
    window.ClosureQueue?.reconcile(data.completed_ids || []);
    if (!executionBusy && !window.ClosureQueue?.busy && lastBridgeImport && (data.completed_ids || []).includes(lastBridgeImport.id) && normalizeText($('#closure').value).trim() === lastBridgeImport.closure) resetForAnotherTicket();
    renderBridgeInbox(items);
    if (autoImportLatest) {
      const pending = items.find((x) => x.status === 'pending');
      if (pending) await importBridgeHandoff(pending, { force: true, automatic: true });
    }
    return items;
  } catch (e) {
    $('#bridgeInbox').className = 'bridge-inbox bad';
    $('#bridgeInbox').textContent = `Falha ao carregar IA Inbox: ${e.message}`;
    return [];
  }
}

function connectBridgeEvents() {
  if (bridgeEventSource) bridgeEventSource.close();
  bridgeEventSource = new EventSource('/api/bridge/events');
  bridgeEventSource.addEventListener('handoff', async (event) => {
    try {
      const item = JSON.parse(event.data);
      if (executionBusy || window.ClosureQueue?.busy) { await refreshBridgeInbox(); return; }
      await importBridgeHandoff(item, { force: true, automatic: true });
      await refreshBridgeStatus();
    } catch (e) {
      log(`Browser Bridge: ${e.message}`);
    }
  });
  bridgeEventSource.onopen = () => {
    $('#bridgeHeroState').textContent = 'IA Bridge · Sincronizado';
    $('#bridgeHeroState').classList.add('connected');
  };
  bridgeEventSource.onerror = () => {
    $('#bridgeHeroState').textContent = 'IA Bridge · Recuperando conexão';
    $('#bridgeHeroState').classList.remove('connected');
    clearTimeout(bridgeRecoveryTimer);
    bridgeRecoveryTimer = setTimeout(async () => {
      await refreshBridgeInbox({ autoImportLatest: true });
      await refreshBridgeStatus();
      if (!bridgeEventSource || bridgeEventSource.readyState === EventSource.CLOSED) connectBridgeEvents();
    }, 1800);
  };
}

async function recoverBridgeSurface() {
  if (document.hidden) return;
  await Promise.allSettled([refreshBridgeStatus(), refreshBridgeInbox({ autoImportLatest: true })]);
  if (!bridgeEventSource || bridgeEventSource.readyState === EventSource.CLOSED) connectBridgeEvents();
}

async function initBridge({ autoImportLatest = true } = {}) {
  connectBridgeEvents();
  await refreshBridgeStatus();
  await refreshBridgeInbox({ autoImportLatest });
  clearInterval(bridgeStatusTimer);
  clearInterval(bridgeInboxTimer);
  bridgeStatusTimer = setInterval(refreshBridgeStatus, 30000);
  // SSE stays the fastest path; this poll is the recovery path for sleeping tabs,
  // browser throttling and transient EventSource failures.
  bridgeInboxTimer = setInterval(() => refreshBridgeInbox({ autoImportLatest: true }), 5000);
}

window.addEventListener('focus', recoverBridgeSurface);
window.addEventListener('pageshow', recoverBridgeSurface);
document.addEventListener('visibilitychange', () => { if (!document.hidden) recoverBridgeSurface(); });

$('#generateBridgeCode').onclick = async () => {
  try {
    const data = await api('/api/bridge/pair-code', { method: 'POST' });
    $('#bridgePairCode').textContent = data.code;
    $('#bridgePairHint').textContent = 'Digite este código no popup da extensão. Ele expira em 5 minutos e é de uso único.';
  } catch (e) {
    $('#bridgePairHint').textContent = e.message;
  }
};

$('#refreshBridgeStatus').onclick = async () => {
  await refreshBridgeStatus();
  await refreshBridgeInbox();
};
$('#refreshBridgeInbox').onclick = () => refreshBridgeInbox();
$('#revokeBridge').onclick = async () => {
  if (!confirm('Revogar o Browser Bridge? A extensão precisará ser pareada novamente.')) return;
  try {
    await api('/api/bridge/revoke', { method: 'POST' });
    $('#bridgePairCode').textContent = '——— ———';
    await refreshBridgeStatus();
  } catch (e) { log(e.message); }
};

async function init() {
  try {
    pendingHandoff = extractHandoffFromLocation();
    const hadLegacyHandoff = !!pendingHandoff;
    const [h, st] = await Promise.all([api('/health'), api('/api/status')]);
    $('#health').textContent = `v${h.version} · Online`;
    $('#catalogStats').textContent = `Catálogo: ${JSON.stringify(st.catalog)}${st.current_user_id ? ` · user_id ${st.current_user_id}` : ''}`;
    if (!st.configured) {
      $('#setupCard').classList.remove('hidden');
    } else {
      $('#workspace').classList.remove('hidden');
      $('#cfgUrl').value = st.config?.url || '';
      if (pendingHandoff) {
        const packet = pendingHandoff;
        pendingHandoff = null;
        setTimeout(() => importHandoff(packet).catch((e) => {
          setWorkflowStatus(`Não foi possível importar o handoff: ${e.message}`, 'error');
          log(e.message);
        }), 0);
      }
      setTimeout(() => initBridge({ autoImportLatest: !hadLegacyHandoff }).catch((e) => log(`Bridge: ${e.message}`)), 0);
    }
  } catch (e) {
    $('#health').textContent = 'Offline';
    log(e.message);
  }
}

$('#testCfg').onclick = async () => {
  try {
    const d = await api('/api/setup/test', jsonOpts({
      url: $('#cfgUrl').value,
      user_token: $('#cfgUserToken').value,
      app_token: $('#cfgAppToken').value,
      verify_tls: true,
    }));
    $('#setupResult').textContent = formatConnectionDiagnostics(d);
  } catch (e) {
    $('#setupResult').textContent = e.message;
  }
};

$('#saveCfg').onclick = async () => {
  try {
    const body = {
      url: $('#cfgUrl').value,
      user_token: $('#cfgUserToken').value,
      app_token: $('#cfgAppToken').value,
      verify_tls: true,
    };
    const d = await api('/api/setup/save', jsonOpts(body));
    $('#setupResult').textContent = formatConnectionDiagnostics(d);
    $('#setupCard').classList.add('hidden');
    $('#workspace').classList.remove('hidden');
    log('Configuração salva. Execute a sincronização dos catálogos.');
    if (pendingHandoff) {
      const packet = pendingHandoff;
      pendingHandoff = null;
      await importHandoff(packet);
    }
    await initBridge({ autoImportLatest: !bridgeDraftIsDirty() });
  } catch (e) {
    $('#setupResult').textContent = e.message;
  }
};

$('#importClipboardBtn').onclick = async () => {
  try {
    await importClipboardText();
  } catch (e) {
    setWorkflowStatus(e.message, 'error');
    log(e.message);
  }
};

$('#syncBtn').onclick = async () => {
  try {
    $('#syncBtn').disabled = true;
    log('Sincronizando categorias, grupos, usuários e entidades visíveis pela sessão...');
    const d = await api('/api/sync', { method: 'POST' });
    log(d);
    $('#catalogStats').textContent = `Catálogo: ${JSON.stringify(d.counts)} · user_id ${d.current_user_id ?? '—'}`;
    if (Array.isArray(d.warnings) && d.warnings.length) {
      log(`Sincronização concluída com ${d.warnings.length} aviso(s). O token pode continuar apto para chamados mesmo sem alguns catálogos globais.`);
    }
  } catch (e) {
    log(e.message);
  } finally {
    $('#syncBtn').disabled = false;
  }
};

function actorChipHtml(rel, kind, role) {
  return `<span class="actor-chip">${esc(rel.label)} <button type="button" class="remove-actor" data-kind="${kind}" data-role="${role}" data-rel-id="${rel.id}" title="Remover">×</button></span>`;
}

function renderActorChips(t) {
  $('#requesterChips').innerHTML = t.requesters.length
    ? t.requesters.map((x) => actorChipHtml(x, 'user', 'requester')).join('')
    : '<span class="muted small">Nenhum.</span>';
  $('#assignedUserChips').innerHTML = t.assigned_users.length
    ? t.assigned_users.map((x) => actorChipHtml(x, 'user', 'assigned')).join('')
    : '<span class="muted small">Nenhum.</span>';
  $('#assignedGroupChips').innerHTML = t.assigned_groups.length
    ? t.assigned_groups.map((x) => actorChipHtml(x, 'group', 'assigned')).join('')
    : '<span class="muted small">Nenhum.</span>';
  $('#observerChips').innerHTML = t.observers.length
    ? t.observers.map((x) => actorChipHtml(x, 'user', 'observer')).join('')
    : '<span class="muted small">Nenhum.</span>';

  document.querySelectorAll('.remove-actor').forEach((btn) => {
    btn.onclick = async () => {
      if (!ticketIsLoaded()) return;
      const kind = btn.dataset.kind;
      const relationId = Number(btn.dataset.relId);
      const role = btn.dataset.role;
      const roleLabel = role === 'requester' ? 'requerente' : role === 'assigned' ? 'atribuído' : 'observador';
      const sensitive = role === 'requester';
      const message = sensitive
        ? `Remover este requerente do chamado #${currentTicket.id}?\n\nAlterações de requerente são sensíveis e serão gravadas imediatamente no GLPI.`
        : `Remover este ${roleLabel} do chamado #${currentTicket.id}?`;
      if (!confirm(message)) return;
      try {
        btn.disabled = true;
        const d = await api(`/api/ticket/${currentTicket.id}/actors/${kind}/${relationId}`, { method: 'DELETE' });
        currentTicket = d.ticket;
        renderTicketSummary(currentTicket);
        invalidatePlan('O chamado foi alterado manualmente. Gerando novo Dry Run quando possível.');
        scheduleAutoPlan();
        log(d);
      } catch (e) {
        setWorkflowStatus(`Falha ao remover ator: ${e.message}`, 'error');
        log(e.message);
        btn.disabled = false;
      }
    };
  });
}

function renderTicketEditor(t) {
  $('#ticketEditor').classList.remove('hidden');
  $('#manualTaskCreator').classList.remove('hidden');
  $('#editTitle').value = t.title || '';
  $('#editCategory').value = t.category?.label || '';
  $('#editStatus').value = String(t.status || 1);
  $('#editPriority').value = String(t.priority || 3);
  renderActorChips(t);
}

function renderTicketSummary(t) {
  $('#ticketSummary').innerHTML = `<strong>#${t.id} · ${esc(t.title)}</strong><br>`
    + `Entidade: ${esc(t.entity?.label || t.entity_id || '—')}<br>`
    + `Categoria: ${esc(t.category.label)} (ID ${t.category.id})<br>`
    + `Status: ${esc(t.status_label || t.status)} · Prioridade: ${esc(t.priority_label || t.priority)}<br>`
    + `Requerente: ${esc(t.requesters.map((x) => x.label).join(', ') || '—')}<br>`
    + `Atribuídos: ${esc([...t.assigned_users.map((x) => x.label), ...t.assigned_groups.map((x) => x.label)].join(', ') || '—')}`;
  renderTicketEditor(t);
  updateWorkflowRail();
}

async function refreshCatalogDatalist(kind, query, datalistId) {
  try {
    const normalizedQuery = String(query || '').trim();
    const cacheKey = `${kind}:${normalizedQuery.toLocaleLowerCase('pt-BR')}`;
    const cached = catalogCache.get(cacheKey);
    let items;
    if (cached && (Date.now() - cached.at) < 300_000) {
      items = cached.items;
    } else {
      const d = await api(`/api/catalog/${encodeURIComponent(kind)}?q=${encodeURIComponent(normalizedQuery)}&limit=80`);
      items = d.items || [];
      catalogCache.set(cacheKey, { at: Date.now(), items });
    }
    const list = $(`#${datalistId}`);
    list.innerHTML = items.map((x) => `<option value="${esc(x.full_name || x.name)}"></option>`).join('');
  } catch {}
}

function bindCatalogInput(inputId, kind, datalistId) {
  const input = $(`#${inputId}`);
  if (!input) return;
  input.addEventListener('focus', () => refreshCatalogDatalist(kind, input.value, datalistId));
  input.addEventListener('input', () => {
    clearTimeout(catalogTimers[inputId]);
    catalogTimers[inputId] = setTimeout(() => refreshCatalogDatalist(kind, input.value, datalistId), 180);
  });
}

['editCategory'].forEach((id) => bindCatalogInput(id, 'ITILCategory', 'catalogCategoryList'));
['addRequester', 'addAssignedUser', 'addObserver', 'manualTaskTech'].forEach((id) => bindCatalogInput(id, 'User', 'catalogUserList'));
['addAssignedGroup', 'manualTaskModality'].forEach((id) => bindCatalogInput(id, 'Group', 'catalogGroupList'));

async function addActorFromInput(inputId, kind, role) {
  if (!ticketIsLoaded()) throw new Error('Carregue o chamado primeiro.');
  const input = $(`#${inputId}`);
  const query = input.value.trim();
  if (!query) throw new Error('Informe o usuário ou grupo a adicionar.');
  const d = await api(`/api/ticket/${currentTicket.id}/actors`, jsonOpts({ kind, role, query }));
  currentTicket = d.ticket;
  input.value = '';
  renderTicketSummary(currentTicket);
  invalidatePlan('O chamado foi alterado manualmente.');
  scheduleAutoPlan();
  log(d);
}

$('#addRequesterBtn').onclick = () => addActorFromInput('addRequester', 'user', 'requester').catch((e) => { setWorkflowStatus(e.message, 'error'); log(e.message); });
$('#replaceRequesterBtn').onclick = async () => {
  try {
    if (!ticketIsLoaded()) throw new Error('Carregue o chamado primeiro.');
    const query = $('#addRequester').value.trim();
    if (!query) throw new Error('Informe o requerente substituto.');
    const current = currentTicket.requesters.map((x) => x.label).join(', ') || 'nenhum';
    if (!confirm(`Substituir o(s) requerente(s) atual(is) do chamado #${currentTicket.id}?\n\nAtual: ${current}\nNovo: ${query}`)) return;
    $('#replaceRequesterBtn').disabled = true;
    const d = await api(`/api/ticket/${currentTicket.id}/requester`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }),
    });
    currentTicket = d.ticket;
    $('#addRequester').value = '';
    renderTicketSummary(currentTicket);
    invalidatePlan('Requerente atualizado. Reinterpretando o Dry Run...');
    scheduleAutoPlan(60);
    setWorkflowStatus(d.changed ? 'Requerente substituído.' : 'O requerente informado já era o requerente atual.', 'ok');
    log(d);
  } catch (e) {
    setWorkflowStatus(`Falha ao substituir requerente: ${e.message}`, 'error');
    log(e.message);
  } finally {
    $('#replaceRequesterBtn').disabled = false;
  }
};
$('#addAssignedUserBtn').onclick = () => addActorFromInput('addAssignedUser', 'user', 'assigned').catch((e) => { setWorkflowStatus(e.message, 'error'); log(e.message); });
$('#replaceAssignedUserBtn').onclick = async () => {
  try {
    if (!ticketIsLoaded()) throw new Error('Carregue o chamado primeiro.');
    const query = $('#addAssignedUser').value.trim();
    if (!query) throw new Error('Informe o técnico substituto.');
    const current = currentTicket.assigned_users.map((x) => x.label).join(', ') || 'nenhum';
    if (!confirm(`Substituir o(s) técnico(s) atual(is) do chamado #${currentTicket.id}?\n\nAtual: ${current}\nNovo: ${query}`)) return;
    $('#replaceAssignedUserBtn').disabled = true;
    setWorkflowStatus(`Resolvendo técnico “${query}” no catálogo do GLPI...`, 'muted');
    const d = await api(`/api/ticket/${currentTicket.id}/technician`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }),
    });
    currentTicket = d.ticket;
    $('#addAssignedUser').value = '';
    renderTicketSummary(currentTicket);
    invalidatePlan('Técnico atualizado. Reinterpretando o Dry Run...');
    scheduleAutoPlan(60);
    setWorkflowStatus(d.changed ? `Técnico substituído por ${d.item?.full_name || query}.` : 'O técnico informado já era o único técnico atribuído.', 'ok');
    log(d);
  } catch (e) {
    setWorkflowStatus(`Falha ao substituir técnico: ${e.message}`, 'error');
    log(e.message);
  } finally {
    $('#replaceAssignedUserBtn').disabled = false;
  }
};
$('#addAssignedGroupBtn').onclick = () => addActorFromInput('addAssignedGroup', 'group', 'assigned').catch((e) => { setWorkflowStatus(e.message, 'error'); log(e.message); });
$('#addObserverBtn').onclick = () => addActorFromInput('addObserver', 'user', 'observer').catch((e) => { setWorkflowStatus(e.message, 'error'); log(e.message); });

$('#saveTicketFields').onclick = async () => {
  try {
    if (!ticketIsLoaded()) throw new Error('Carregue o chamado primeiro.');
    const nextStatus = Number($('#editStatus').value);
    if (nextStatus === 6 && currentTicket.status !== 6) {
      if (!confirm(`O status será alterado para Fechado no chamado #${currentTicket.id}. Continuar?`)) return;
    }
    const body = {
      title: $('#editTitle').value,
      category: $('#editCategory').value,
      status: nextStatus,
      priority: Number($('#editPriority').value),
    };
    $('#saveTicketFields').disabled = true;
    const d = await api(`/api/ticket/${currentTicket.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    currentTicket = d.ticket;
    renderTicketSummary(currentTicket);
    invalidatePlan('Campos do chamado atualizados. O Dry Run anterior foi invalidado.');
    scheduleAutoPlan();
    setWorkflowStatus(`Chamado #${currentTicket.id} atualizado manualmente.`, 'ok');
    log(d);
  } catch (e) {
    setWorkflowStatus(`Falha ao atualizar chamado: ${e.message}`, 'error');
    log(e.message);
  } finally {
    $('#saveTicketFields').disabled = false;
  }
};

let existingTaskLoadRevision=0;
async function loadExistingTasks() {
  const revision=++existingTaskLoadRevision;
  const ticketId=currentTicket?.id;
  if (!ticketIsLoaded()) {
    $('#existingTasks').className = 'existing-tasks muted';
    $('#existingTasks').textContent = 'Carregue um chamado para visualizar as tarefas.';
    $('#refreshTasks').disabled = true;
    return;
  }
  const root = $('#existingTasks');
  root.className = 'existing-tasks muted';
  root.textContent = 'Consultando tarefas do GLPI...';
  $('#refreshTasks').disabled = true;
  try {
    const d = await api(`/api/ticket/${currentTicket.id}/tasks`);
    if(revision!==existingTaskLoadRevision || currentTicket?.id!==ticketId)return;
    renderExistingTasks(d.tasks || []);
  } catch (e) {
    if(revision!==existingTaskLoadRevision || currentTicket?.id!==ticketId)return;
    root.className = 'existing-tasks bad';
    root.textContent = `Não foi possível carregar as tarefas: ${e.message}`;
    log(e.message);
  } finally {
    if(revision===existingTaskLoadRevision)$('#refreshTasks').disabled = !ticketIsLoaded();
  }
}

function updateBulkTaskControls() {
  const boxes = [...document.querySelectorAll('#existingTasks .task-select')];
  const checked = boxes.filter((b) => b.checked);
  const selectAll = $('#selectAllTasks');
  const del = $('#deleteSelectedTasks');
  if (selectAll) {
    selectAll.disabled = boxes.length === 0;
    selectAll.textContent = boxes.length && checked.length === boxes.length ? 'Limpar seleção' : 'Selecionar todas';
  }
  if (del) {
    del.disabled = checked.length === 0;
    del.textContent = checked.length ? `Excluir selecionadas (${checked.length})` : 'Excluir selecionadas';
  }
}

function renderExistingTasks(tasks) {
  const root = $('#existingTasks');
  root.className = 'existing-tasks';
  root.innerHTML = '';
  if (!tasks.length) {
    root.className = 'existing-tasks muted';
    root.textContent = 'Este chamado não possui tarefas.';
    updateBulkTaskControls();
    return;
  }

  const summary = document.createElement('div');
  summary.className = 'task-manager-summary';
  summary.textContent = `${tasks.length} tarefa(s) encontrada(s) no chamado.`;
  root.appendChild(summary);

  tasks.forEach((t) => {
    const card = document.createElement('article');
    card.className = 'existing-task';
    const firstLine = (t.content_text || '').split('\n').find((x) => x.trim()) || '(sem conteúdo)';
    const logical = t.logical_id ? `<span class="badge">GLPI Assistant · ${esc(t.logical_id)}</span>` : '';
    const docs = (t.documents || []).map((d) => `<span class="doc-chip" title="Document ID ${d.id}">${esc(d.name)}</span>`).join('');
    card.innerHTML = `
      <div class="existing-task-head">
        <label class="task-select-wrap" title="Selecionar tarefa #${t.id}">
          <input type="checkbox" class="task-select" value="${t.id}" aria-label="Selecionar tarefa #${t.id}">
        </label>
        <div class="minw0">
          <div class="existing-task-title">Chamado #${currentTicket.id} · Tarefa #${t.id} ${logical}</div>
          <div class="meta">${esc(t.state_label)} · ${esc(formatDuration(t.actiontime))} · ${esc(t.tech_label)} · ${esc(t.group_label)}</div>
          <div class="meta">${esc(t.date || '')}</div>
        </div>
        <div class="existing-task-actions">
          <button type="button" class="secondary compact edit-task" data-task-id="${t.id}">Editar</button>
          <button type="button" class="danger compact delete-task" data-task-id="${t.id}" data-first-line="${esc(firstLine)}">Excluir</button>
        </div>
      </div>
      <details>
        <summary>${esc(firstLine.length > 120 ? `${firstLine.slice(0, 120)}…` : firstLine)}</summary>
        <pre class="task-preview">${esc(t.content_text || '(sem conteúdo)')}</pre>
      </details>
      <div class="doc-list">${t.documents_loaded===false?`<button class="secondary compact load-task-docs" data-task-id="${t.id}">Consultar anexos desta tarefa</button>`:docs || '<span class="muted small">Sem documentos vinculados.</span>'}</div>
      <div class="task-edit-form hidden" data-task-edit="${t.id}">
        <label>Conteúdo
          <textarea class="task-edit-content" rows="7">${esc(t.content_text || '')}</textarea>
        </label>
        <div class="task-edit-grid">
          <label>Tempo
            <input class="task-edit-time" value="${esc(durationInput(t.actiontime))}">
          </label>
          <label>Estado
            <select class="task-edit-state">
              <option value="FEITO" ${Number(t.state) === 2 ? 'selected' : ''}>FEITO</option>
              <option value="A FAZER" ${Number(t.state) === 1 ? 'selected' : ''}>A FAZER</option>
            </select>
          </label>
          <label>Técnico
            <input class="task-edit-tech" list="catalogUserList" value="${esc(t.tech_label === '—' ? '' : t.tech_label)}">
          </label>
          <label>Modalidade / grupo
            <input class="task-edit-modality" list="catalogGroupList" value="${esc(t.group_label === '—' ? '' : t.group_label)}">
          </label>
        </div>
        <div class="actions right">
          <button type="button" class="ghost compact cancel-task-edit" data-task-id="${t.id}">Cancelar</button>
          <button type="button" class="white-action compact save-task-edit" data-task-id="${t.id}">Salvar tarefa</button>
        </div>
      </div>
    `;
    root.appendChild(card);
  });

  const renderedTicketId=currentTicket.id;
  root.querySelectorAll('.load-task-docs').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    try{
      const data=await api(`/api/ticket/${renderedTicketId}/tasks/${button.dataset.taskId}/documents`);
      if(currentTicket?.id!==renderedTicketId||!button.isConnected)return;
      button.parentElement.innerHTML=data.documents.map(d=>`<span class="doc-chip">${esc(d.name)}</span>`).join('')||'<span class="small muted">Sem documentos vinculados.</span>';
    }catch(e){button.textContent='Não foi possível consultar. Tentar novamente';button.title=e.message;button.disabled=false;}
  });
  root.querySelectorAll('.task-select').forEach((box) => {
    box.addEventListener('change', updateBulkTaskControls);
  });
  updateBulkTaskControls();

  root.querySelectorAll('.edit-task').forEach((btn) => {
    btn.addEventListener('click', () => {
      const form = root.querySelector(`[data-task-edit="${btn.dataset.taskId}"]`);
      form?.classList.toggle('hidden');
      if (form && !form.classList.contains('hidden')) {
        refreshCatalogDatalist('User', form.querySelector('.task-edit-tech')?.value || '', 'catalogUserList');
        refreshCatalogDatalist('Group', form.querySelector('.task-edit-modality')?.value || '', 'catalogGroupList');
      }
    });
  });

  root.querySelectorAll('.cancel-task-edit').forEach((btn) => {
    btn.addEventListener('click', () => {
      root.querySelector(`[data-task-edit="${btn.dataset.taskId}"]`)?.classList.add('hidden');
    });
  });

  root.querySelectorAll('.task-edit-tech').forEach((input) => {
    input.addEventListener('input', () => refreshCatalogDatalist('User', input.value, 'catalogUserList'));
  });
  root.querySelectorAll('.task-edit-modality').forEach((input) => {
    input.addEventListener('input', () => refreshCatalogDatalist('Group', input.value, 'catalogGroupList'));
  });

  root.querySelectorAll('.save-task-edit').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!ticketIsLoaded()) return;
      const taskId = Number(btn.dataset.taskId);
      const form = root.querySelector(`[data-task-edit="${taskId}"]`);
      if (!form) return;
      try {
        btn.disabled = true;
        const body = {
          content: form.querySelector('.task-edit-content').value,
          time: form.querySelector('.task-edit-time').value,
          state: form.querySelector('.task-edit-state').value,
          technician: form.querySelector('.task-edit-tech').value,
          modality: form.querySelector('.task-edit-modality').value,
        };
        const d = await api(`/api/ticket/${currentTicket.id}/tasks/${taskId}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        renderExistingTasks(d.tasks || []);
        invalidatePlan('Uma tarefa existente foi editada. Revise o fechamento antes de aplicar novas tarefas.');
        scheduleAutoPlan();
        setWorkflowStatus(`Tarefa #${taskId} atualizada.`, 'ok');
        log(d);
      } catch (e) {
        setWorkflowStatus(`Falha ao editar tarefa #${taskId}: ${e.message}`, 'error');
        log(e.message);
        btn.disabled = false;
      }
    });
  });

  root.querySelectorAll('.delete-task').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!ticketIsLoaded()) return;
      const taskId = Number(btn.dataset.taskId);
      const firstLine = btn.dataset.firstLine || '';
      const ok = confirm(`Excluir a tarefa #${taskId} do chamado #${currentTicket.id}?\n\n${firstLine}\n\nEsta operação é enviada ao GLPI e não possui desfazer pelo GLPI Assistant.`);
      if (!ok) return;
      try {
        btn.disabled = true;
        setWorkflowStatus(`Excluindo tarefa #${taskId}...`, 'muted');
        const d = await api(`/api/ticket/${currentTicket.id}/tasks/${taskId}`, { method: 'DELETE' });
        renderExistingTasks(d.tasks || []);
        setWorkflowStatus(`Tarefa #${taskId} excluída.`, 'ok');
        log(d);
      } catch (e) {
        setWorkflowStatus(`Falha ao excluir tarefa #${taskId}: ${e.message}`, 'error');
        log(e.message);
        btn.disabled = false;
      }
    });
  });
}

async function fetchTicket(id) {
  return api(`/api/ticket/${id}`);
}

let ticketLoadSequence = 0;
async function loadTicket({ preserveDraft = false, reanalyze = true } = {}) {
  const loadingSequence = ++ticketLoadSequence;
  try {
    invalidatePlan('Procurando chamado...');
    const id = currentTicketId();
    if (!id) throw new Error('Informe o número do chamado.');
    const switching = !!loadedTicketId && loadedTicketId !== id;
    $('#loadTicket').disabled = true;
    $('#refreshTicket').disabled = true;

    const fetched = await fetchTicket(id);
    if (loadingSequence !== ticketLoadSequence || currentTicketId() !== id) return;
    if (switching && !preserveDraft) clearDraft();
    currentTicket = fetched;
    loadedTicketId = currentTicket.id;
    renderTicketSummary(currentTicket);
    $('#refreshTicket').disabled = false;
    window.onWorkbenchTicketLoaded?.(currentTicket);
    $('#refreshTasks').disabled = false;
    setWorkflowStatus(`Chamado #${currentTicket.id} carregado.`, 'ok');
    log(currentTicket);

    // O histórico é secundário para o fechamento. Carregá-lo em background
    // evita segurar parser/Dry Run enquanto o GLPI resolve tarefas/documentos.
    loadExistingTasks().catch((e) => log(`Histórico: ${e.message}`));

    if (reanalyze && $('#closure').value.trim()) scheduleAnalyze(0);
    else if (!$('#closure').value.trim()) setWorkflowStatus(`Chamado #${currentTicket.id} carregado. Cole o fechamento; a análise será automática.`, 'ok');
    if (parsed) scheduleClosureReview(120);
  } catch (e) {
    if (loadingSequence !== ticketLoadSequence) return;
    currentTicket = null;
    loadedTicketId = 0;
    $('#ticketSummary').textContent = 'Nenhum chamado carregado.';
    $('#refreshTicket').disabled = true;
    $('#refreshTasks').disabled = true;
    setWorkflowStatus(e.message, 'error');
    log(e.message);
  } finally {
    $('#loadTicket').disabled = false;
  }
}

$('#loadTicket').onclick = () => loadTicket();
$('#refreshTicket').onclick = () => loadTicket({ preserveDraft: true, reanalyze: true });
$('#refreshTasks').onclick = loadExistingTasks;

$('#selectAllTasks').onclick = () => {
  const boxes = [...document.querySelectorAll('#existingTasks .task-select')];
  if (!boxes.length) return;
  const shouldCheck = boxes.some((b) => !b.checked);
  boxes.forEach((b) => { b.checked = shouldCheck; });
  updateBulkTaskControls();
};

$('#deleteSelectedTasks').onclick = async () => {
  if (!ticketIsLoaded()) return;
  const ids = [...document.querySelectorAll('#existingTasks .task-select:checked')]
    .map((b) => Number(b.value)).filter(Boolean);
  if (!ids.length) return;
  if (!confirm(`Excluir ${ids.length} tarefa(s) selecionada(s) do chamado #${currentTicket.id}?

IDs: ${ids.join(', ')}

O Assistant valida todas as tarefas antes de iniciar a exclusão.`)) return;
  try {
    $('#deleteSelectedTasks').disabled = true;
    $('#selectAllTasks').disabled = true;
    setWorkflowStatus(`Validando e excluindo ${ids.length} tarefa(s)...`, 'muted');
    const d = await api(`/api/ticket/${currentTicket.id}/tasks/bulk-delete`, jsonOpts({ task_ids: ids }));
    renderExistingTasks(d.tasks || []);
    invalidatePlan('Histórico alterado. Reinterpretando o fechamento contra as tarefas restantes...');
    scheduleAutoPlan(60);
    if (d.ok) setWorkflowStatus(`${d.deleted_count} tarefa(s) excluída(s).`, 'ok');
    else setWorkflowStatus(`Exclusão parcial: ${d.deleted_count}/${d.requested_count}. Revise o log.`, 'error');
    log(d);
  } catch (e) {
    setWorkflowStatus(`Falha na exclusão em massa: ${e.message}`, 'error');
    log(e.message);
    updateBulkTaskControls();
  }
};
$('#newTicket').onclick = resetForAnotherTicket;
$('#toggleManualTask').onclick = () => {
  const box = $('#manualTaskCreator');
  const textarea = $('#manualTaskContent');
  const collapsed = textarea.classList.toggle('hidden');
  box.querySelector('.editor-grid')?.classList.toggle('hidden', collapsed);
  box.querySelector('.actions')?.classList.toggle('hidden', collapsed);
  $('#toggleManualTask').textContent = collapsed ? 'Expandir' : 'Recolher';
};

$('#createManualTask').onclick = async () => {
  try {
    if (!ticketIsLoaded()) throw new Error('Carregue o chamado primeiro.');
    const body = {
      content: $('#manualTaskContent').value,
      time: $('#manualTaskTime').value,
      state: $('#manualTaskState').value,
      technician: $('#manualTaskTech').value || null,
      modality: $('#manualTaskModality').value,
    };
    if (!body.content.trim()) throw new Error('Descreva o conteúdo da tarefa.');
    $('#createManualTask').disabled = true;
    const d = await api(`/api/ticket/${currentTicket.id}/tasks/manual`, jsonOpts(body));
    $('#manualTaskContent').value = '';
    renderExistingTasks(d.tasks || []);
    invalidatePlan('Uma tarefa manual foi criada. Revise o fechamento antes de aplicar novas tarefas.');
    scheduleAutoPlan();
    setWorkflowStatus(`Tarefa #${d.task_id} criada manualmente.`, 'ok');
    log(d);
  } catch (e) {
    setWorkflowStatus(`Falha ao criar tarefa: ${e.message}`, 'error');
    log(e.message);
  } finally {
    $('#createManualTask').disabled = false;
  }
};
$('#ticketId').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    loadTicket();
  }
});

function addFiles(list) {
  const oldMap = evidenceMap();
  invalidatePlan('Evidências alteradas. Preparando novo Dry Run automático...');
  for (const f of list) {
    if (!f.type.startsWith('image/')) continue;
    if (!files.some((x) => x.file.name === f.name && x.file.size === f.size && x.file.lastModified === f.lastModified)) files.push(makeFileEntry(f));
  }
  renderFiles();
  renderTasks(oldMap);
  updateEvidenceState();
  scheduleAutoPlan();
}

function renderFiles() {
  revokeFileUrls();
  const root = $('#filesList');
  root.innerHTML = '';
  files.forEach((entry, i) => {
    const f = entry.file;
    const div = document.createElement('div');
    div.className = 'file-card';
    div.dataset.fileId = entry.id;
    const url = filePreviewUrl(entry);
    div.innerHTML = `<img src="${url}" alt="Prévia de ${esc(f.name)}"><div class="file-name">${esc(f.name)}</div><div class="muted micro">ID local: ${esc(entry.id.slice(-8))}</div><button type="button" class="secondary compact remove-file" data-i="${i}">Remover</button>`;
    root.appendChild(div);
  });
  root.querySelectorAll('.remove-file').forEach((b) => {
    b.onclick = () => {
      const oldMap = evidenceMap();
      invalidatePlan('Evidências alteradas. O Dry Run será refeito quando todos os slots estiverem preenchidos.');
      files.splice(parseInt(b.dataset.i, 10), 1);
      renderFiles();
      renderTasks(oldMap, false);
      updateEvidenceState();
      scheduleAutoPlan();
    };
  });
  renderClosureEvidencePreview();
  updateEvidenceState();
}

const dz = $('#dropzone');

function bindFilePicker() {
  const fp = $('#filePicker');
  if (!fp) return;
  fp.onchange = () => {
    addFiles(fp.files);
    fp.value = '';
  };
}

dz.addEventListener('click', () => {
  if (dz.getAttribute('aria-disabled') === 'true') return;
  $('#filePicker')?.click();
});
['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault();
  if (dz.getAttribute('aria-disabled') !== 'true') dz.classList.add('drag');
}));
['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault();
  dz.classList.remove('drag');
}));
dz.addEventListener('drop', (e) => {
  if (dz.getAttribute('aria-disabled') === 'true') return;
  addFiles(e.dataTransfer.files);
});
bindFilePicker();

function renderTasks(preferredMap = {}, fillEmpty = true) {
  const root = $('#tasks');
  root.innerHTML = '';
  if (!parsed) {
    root.innerHTML = '<div class="muted">Nenhuma tarefa analisada.</div>';
    updateEvidenceState();
    return;
  }
  const count = document.createElement('div');
  count.className = 'detected-count';
  if (currentPlan) {
    count.textContent = `${parsed.tasks.length} recebida(s) · ${currentPlan.task_count} nova(s) · ${currentPlan.skipped_task_count || 0} já existente(s) · ${currentPlan.evidence_count} evidência(s) necessária(s)`;
  } else {
    count.textContent = `${parsed.tasks.length} tarefa(s) detectada(s) · interpretando histórico…`;
  }
  root.appendChild(count);

  const skippedIds = new Set((currentPlan?.skipped_tasks || []).map((x) => x?.task?.id));
  const requiredIds = requiredEvidence();
  parsed.tasks.forEach((t, index) => {
    const div = document.createElement('div');
    const skipped = skippedIds.has(t.id);
    div.className = `task${skipped ? ' task-already-exists' : ''}`;
    const taskEvidence = (t.evidences || []).filter((e) => requiredIds.has(e));
    const rows = skipped
      ? '<div class="no-evidence existing-note">Já representada no histórico do chamado · não será criada novamente.</div>'
      : taskEvidence.length
        ? taskEvidence.map((e) => `<div class="evidence-row"><div class="evidence-id">${esc(e)}</div><select data-evidence="${esc(e)}"><option value="">Selecione o arquivo…</option>${files.map((entry) => `<option value="${esc(entry.id)}">${esc(entry.file.name)}</option>`).join('')}</select><div class="muted micro evidence-selected-name" data-evidence-label="${esc(e)}"></div></div>`).join('')
        : '<div class="no-evidence">Sem evidências necessárias nesta tarefa · pronta para Dry Run</div>';
    div.innerHTML = `<div class="task-head"><div><div class="task-code">${index + 1}. ${esc(t.id)} ${skipped ? '<span class="badge success">Já existe</span>' : ''}</div><div class="meta">${skipped ? 'ignorada com segurança' : `${taskEvidence.length} evidência(s) necessária(s)`}</div></div><div class="meta">${esc(t.modalidade)} · ${esc(t.nivel || '—')} · ${esc(t.tempo)} · ${esc(t.estado)}</div></div>${rows}`;
    root.appendChild(div);
  });
  autoMapEvidence(preferredMap, fillEmpty);
  root.querySelectorAll('[data-evidence]').forEach((s) => s.addEventListener('change', () => {
    invalidatePlan('Mapeamento alterado. Gerando novo Dry Run automático...');
    updateEvidenceSelectionLabels();
    renderClosureEvidencePreview();
    updateEvidenceState();
    scheduleAutoPlan(60);
  }));
  updateEvidenceState();
  renderQualityState();
  updateWorkflowRail();
}

function updateEvidenceSelectionLabels() {
  document.querySelectorAll('[data-evidence-label]').forEach((el) => {
    const evid = el.dataset.evidenceLabel;
    const select = document.querySelector(`[data-evidence="${CSS.escape(evid)}"]`);
    const name = select?.value ? evidenceFileName(select.value) : '';
    el.textContent = name ? `${evid} → ${name}` : `${evid} sem arquivo`;
  });
}

function autoMapEvidence(preferredMap = {}, fillEmpty = true) {
  const selects = [...document.querySelectorAll('[data-evidence]')];
  const used = new Set();
  for (const s of selects) {
    const wanted = preferredMap[s.dataset.evidence];
    if (wanted && files.some((entry) => entry.id === wanted)) {
      s.value = wanted;
      used.add(wanted);
    }
  }
  if (fillEmpty) {
    for (const s of selects) {
      if (s.value) continue;
      const named = files.find(entry => !used.has(entry.id) && (entry.file.bridgeEvidenceId || entry.file.name.split('.')[0].toUpperCase()) === s.dataset.evidence);
      const next = named || files.find((entry) => !used.has(entry.id) && !entry.file.bridgeEvidenceId && !/^E\d{2,3}\./i.test(entry.file.name));
      if (next) {
        s.value = next.id;
        used.add(next.id);
      }
    }
  }
  updateEvidenceSelectionLabels();
  renderClosureEvidencePreview();
}



function resetClosureReview(message = 'Carregue o chamado e um fechamento válido. A revisão usa somente catálogos do GLPI e nunca altera nada sem o Dry Run.') {
  closureReview = null;
  clearTimeout(reviewTimer);
  const badge = $('#reviewConfidence');
  if (badge) { badge.className = 'badge neutral'; badge.textContent = 'Aguardando fechamento'; }
  if ($('#reviewReason')) $('#reviewReason').textContent = message;
  if ($('#reviewTitleInput')) { $('#reviewTitleInput').value = ''; delete $('#reviewTitleInput').dataset.suggested; }
  if ($('#reviewCategoryInput')) { $('#reviewCategoryInput').value = ''; delete $('#reviewCategoryInput').dataset.suggested; }
  if ($('#reviewAlternatives')) $('#reviewAlternatives').replaceChildren();
  if ($('#reviewApplyBtn')) $('#reviewApplyBtn').disabled = true;
}

function reviewCategoryLabel(category = {}) {
  return String(category.full_name || category.label || category.name || '').trim();
}

function updateReviewApplyState() {
  if (!closureReview) { $('#reviewApplyBtn').disabled = true; return; }
  const title = $('#reviewTitleInput').value.trim();
  const category = $('#reviewCategoryInput').value.trim();
  const currentTitle = String(closureReview.current?.title || '').trim();
  const currentCategory = reviewCategoryLabel(closureReview.current?.category || {});
  $('#reviewApplyBtn').disabled = (!title || title === currentTitle) && (!category || category === currentCategory);
}

function renderClosureReview(data) {
  closureReview = data;
  const titleInput = $('#reviewTitleInput');
  const categoryInput = $('#reviewCategoryInput');
  const previousTitleSuggestion = titleInput.dataset.suggested || '';
  const previousCategorySuggestion = categoryInput.dataset.suggested || '';
  const titleSuggestion = String(data.title?.value || '').trim();
  const categorySuggestion = String(data.category?.recommended?.full_name || '').trim();
  if (!titleInput.value || titleInput.value === previousTitleSuggestion) titleInput.value = titleSuggestion;
  if (!categoryInput.value || categoryInput.value === previousCategorySuggestion) categoryInput.value = categorySuggestion;
  titleInput.dataset.suggested = titleSuggestion;
  categoryInput.dataset.suggested = categorySuggestion;

  const titleConfidence = Number(data.title?.confidence || 0);
  const categoryConfidence = Number(data.category?.recommended?.score || 0);
  const confidence = Math.max(titleConfidence, categoryConfidence);
  const badge = $('#reviewConfidence');
  badge.className = `badge ${confidence >= .78 ? 'success' : confidence >= .48 ? 'warning' : 'neutral'}`;
  badge.textContent = confidence ? `${Math.round(confidence * 100)}% · sugestão local` : 'Revisão conservadora';
  const currentCategory = reviewCategoryLabel(data.current?.category || {}) || 'Sem categoria';
  const currentGroups = (data.current?.groups || []).filter(Boolean).join(', ') || 'Sem grupo atribuído';
  $('#reviewReason').innerHTML = `<span class="review-current">Atual: <strong>${esc(data.current?.title || '—')}</strong> · ${esc(currentCategory)}<br>Grupos: ${esc(currentGroups)}</span><br>${esc(data.category?.reason || data.title?.reason || 'Revise os campos antes do Dry Run.')}`;

  const alternatives = $('#reviewAlternatives');
  alternatives.replaceChildren();
  for (const item of data.category?.candidates || []) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'review-alt';
    btn.textContent = `${item.full_name} · ${Math.round(Number(item.score || 0) * 100)}%`;
    btn.title = (item.matched_terms || []).length ? `Termos: ${(item.matched_terms || []).join(', ')}` : 'Alternativa do catálogo';
    btn.onclick = () => { categoryInput.value = item.full_name; updateReviewApplyState(); };
    alternatives.append(btn);
  }
  updateReviewApplyState();
}

async function runClosureReview({ quiet = false } = {}) {
  if (!ticketIsLoaded() || !parsed || !normalizeText($('#closure').value).trim()) {
    if (!quiet) resetClosureReview('Carregue o chamado e um fechamento válido para revisar título e categoria.');
    return;
  }
  const ticketId = currentTicketId();
  const text = normalizeText($('#closure').value);
  try {
    if (!quiet) { $('#reviewConfidence').className = 'badge neutral'; $('#reviewConfidence').textContent = 'Revisando…'; }
    const data = await api('/api/review/suggest', jsonOpts({ ticket_id: ticketId, text }));
    if (ticketId !== currentTicketId() || text !== normalizeText($('#closure').value)) return;
    renderClosureReview(data);
  } catch (error) {
    if (!quiet) {
      $('#reviewConfidence').className = 'badge warning'; $('#reviewConfidence').textContent = 'Revisão indisponível';
      $('#reviewReason').textContent = error.message;
    }
  }
}

function scheduleClosureReview(delay = 420) {
  clearTimeout(reviewTimer);
  if (!ticketIsLoaded() || !parsed) return;
  reviewTimer = setTimeout(() => runClosureReview({ quiet: true }), delay);
}

function setChangeField(text, field, value) {
  const cleanValue = String(value || '').replace(/\s+/g, ' ').trim();
  if (!cleanValue) return normalizeText(text);
  let source = normalizeText(text).trimEnd();
  const blockRe = /\[ALTERACOES_CHAMADO\]([\s\S]*?)\[\/ALTERACOES_CHAMADO\]/i;
  const match = blockRe.exec(source);
  if (!match) return `${source}\n\n[ALTERACOES_CHAMADO]\n${field}: ${cleanValue}\n[/ALTERACOES_CHAMADO]\n`;
  const body = match[1];
  const fieldRe = new RegExp(`(^|\\n)\\s*${field}\\s*:[^\\n]*`, 'i');
  const nextBody = fieldRe.test(body)
    ? body.replace(fieldRe, (whole, prefix) => `${prefix}${field}: ${cleanValue}`)
    : `${body.replace(/\s*$/, '')}\n${field}: ${cleanValue}\n`;
  return `${source.slice(0, match.index)}[ALTERACOES_CHAMADO]${nextBody}[/ALTERACOES_CHAMADO]${source.slice(match.index + match[0].length)}`;
}

$('#reviewTitleInput')?.addEventListener('input', updateReviewApplyState);
$('#reviewCategoryInput')?.addEventListener('input', updateReviewApplyState);
$('#reviewSuggestBtn')?.addEventListener('click', () => runClosureReview());
$('#reviewKeepBtn')?.addEventListener('click', () => {
  if (!closureReview) return;
  $('#reviewTitleInput').value = '';
  $('#reviewCategoryInput').value = '';
  $('#reviewApplyBtn').disabled = true;
  $('#reviewConfidence').className = 'badge neutral';
  $('#reviewConfidence').textContent = 'Manter campos atuais';
  setWorkflowStatus('Título e categoria atuais serão preservados.', 'ok');
});
$('#reviewManualBtn')?.addEventListener('click', async () => {
  if (!ticketIsLoaded()) { setWorkflowStatus('Carregue um chamado antes de editar atores e grupos.', 'error'); return; }
  if (typeof window.openWorkbenchTicket === 'function') await window.openWorkbenchTicket(currentTicketId(), 'administracao');
});
$('#reviewApplyBtn')?.addEventListener('click', () => {
  let text = normalizeText($('#closure').value);
  const title = $('#reviewTitleInput').value.trim();
  const category = $('#reviewCategoryInput').value.trim();
  if (title) text = setChangeField(text, 'titulo', title);
  if (category) text = setChangeField(text, 'categoria', category);
  $('#closure').value = text.trim() + '\n';
  invalidatePlan('Sugestões de título/categoria adicionadas ao fechamento. Gerando novo Dry Run...');
  scheduleAnalyze(0);
});


function describeAppliedOperation(entry) {
  const op = String(entry?.op || '');
  const ok = entry?.ok !== false;
  const task = entry?.task ? String(entry.task) : '';
  const labels = {
    update_title: ['Título atualizado', entry?.title || entry?.to || 'Novo título aplicado'],
    update_category: ['Categoria atualizada', entry?.to?.completename || entry?.to?.name || (entry?.id ? `Categoria #${entry.id}` : 'Nova categoria aplicada')],
    replace_requester: ['Requerente atualizado', entry?.user_id ? `Usuário #${entry.user_id}` : 'Relação atualizada'],
    add_group: ['Grupo adicionado', entry?.group_id ? `Grupo #${entry.group_id}` : 'Grupo aplicado'],
    remove_group: ['Grupo removido', entry?.group_id ? `Grupo #${entry.group_id}` : 'Grupo removido'],
    add_technician: ['Técnico adicionado', entry?.user_id ? `Usuário #${entry.user_id}` : 'Técnico aplicado'],
    remove_technician: ['Técnico removido', entry?.user_id ? `Usuário #${entry.user_id}` : 'Técnico removido'],
    create_task: [`${task || 'Tarefa'} criada`, entry?.task_id ? `TicketTask #${entry.task_id}` : 'Criada no GLPI'],
    upload_evidence: [`${entry?.evidence || 'Evidência'} anexada`, entry?.file || (entry?.document_id ? `Documento #${entry.document_id}` : 'Documento vinculado')],
    update_task_inline: [`${task || 'Tarefa'} atualizada`, entry?.task_id ? `Conteúdo confirmado na TicketTask #${entry.task_id}` : 'Conteúdo inline atualizado'],
    verify_task: [`${task || 'Tarefa'} verificada`, entry?.task_id ? `TicketTask #${entry.task_id}` : 'Verificação concluída'],
  };
  const pair = labels[op] || [op ? op.replaceAll('_', ' ') : 'Operação', entry?.message || 'Registrada pela API'];
  return { ok, title: pair[0], detail: String(pair[1] || '') };
}

function renderApplySuccessVisual(result, plan, afterMode) {
  const root = $('#applySuccessAppliedList');
  if (!root) return;
  const executionLog = Array.isArray(result?.log) ? result.log : [];
  const useful = executionLog.filter((entry) => ['update_title','update_category','replace_requester','add_group','remove_group','add_technician','remove_technician','create_task','upload_evidence','update_task_inline','verify_task'].includes(String(entry?.op || '')));
  const rows = useful.map(describeAppliedOperation);
  const skipped = Number(result?.skipped_existing_at_apply_count || plan?.skipped_task_count || 0);
  if (skipped) rows.push({ ok: true, title: `${skipped} tarefa(s) preservada(s)`, detail: 'Já existiam no GLPI e não foram duplicadas.' });
  if (afterMode === 'solve') rows.push({ ok: true, title: 'Chamado solucionado', detail: 'Solução registrada após a formalização.' });
  if (afterMode === 'close') rows.push({ ok: true, title: 'Chamado fechado', detail: 'Encerramento solicitado após a formalização.' });
  if (!rows.length) rows.push({ ok: true, title: 'Aplicação confirmada', detail: 'A API confirmou as operações previstas para este chamado.' });
  root.innerHTML = rows.map((row) => `<article class="success-applied-item ${row.ok ? 'ok' : 'bad'}"><span class="success-applied-icon">${row.ok ? '✓' : '!'}</span><div><strong>${esc(row.title)}</strong><span>${esc(row.detail)}</span></div></article>`).join('');
}

function setApplySuccessTab(mode) {
  const visual = mode !== 'log';
  const visualPanel = $('#applySuccessVisual');
  const logPanel = $('#applySuccessLog');
  const visualTab = $('#applySuccessVisualTab');
  const logTab = $('#applySuccessLogTab');
  if (visualPanel) visualPanel.hidden = !visual;
  if (logPanel) logPanel.hidden = visual;
  if (visualTab) { visualTab.classList.toggle('active', visual); visualTab.setAttribute('aria-selected', String(visual)); }
  if (logTab) { logTab.classList.toggle('active', !visual); logTab.setAttribute('aria-selected', String(!visual)); }
}

function showApplySuccess(result, plan, afterMode) {
  const dialog = $('#applySuccessDialog');
  if (!dialog) return;
  const ops = plan?.operations || [];
  const changedTitle = ops.some((o) => o.op === 'update_title');
  const changedCategory = ops.some((o) => o.op === 'update_category');
  const evidences = Number(plan?.evidence_count || 0);
  $('#applySuccessTitle').textContent = `#${plan?.ticket?.id || currentTicketId()} atualizado no GLPI`;
  $('#applySuccessSubtitle').textContent = afterMode === 'close' ? 'Tarefas aplicadas e chamado encerrado.' : afterMode === 'solve' ? 'Tarefas aplicadas e chamado solucionado.' : 'Tarefas e alterações confirmadas pela API.';
  const stats = [
    { value: `${result.verified_task_count || 0}/${result.expected_task_count || 0}`, label: 'tarefas confirmadas', good: true },
    { value: String(evidences), label: 'evidências', good: true },
    { value: changedCategory ? 'Atualizada' : 'Mantida', label: 'categoria', good: changedCategory },
    { value: changedTitle ? 'Atualizado' : 'Mantido', label: 'título', good: changedTitle },
  ];
  $('#applySuccessStats').innerHTML = stats.map((item) => `<div class="success-stat${item.good ? ' good' : ''}"><strong>${esc(item.value)}</strong><span>${esc(item.label)}</span></div>`).join('');
  $('#applySuccessLog').textContent = JSON.stringify({ ticket: plan?.ticket?.id, result, operations: ops }, null, 2);
  renderApplySuccessVisual(result, plan, afterMode);
  setApplySuccessTab('visual');
  const openGlpi = $('#applySuccessOpenGlpi');
  const glpiUrl = String(currentTicket?.url || plan?.ticket?.url || '');
  if (openGlpi) { openGlpi.disabled = !glpiUrl; openGlpi.dataset.url = glpiUrl; }
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
}

$('#applySuccessVisualTab')?.addEventListener('click', () => setApplySuccessTab('visual'));
$('#applySuccessLogTab')?.addEventListener('click', () => setApplySuccessTab('log'));

$('#applySuccessOpenGlpi')?.addEventListener('click', () => {
  const url = $('#applySuccessOpenGlpi')?.dataset.url;
  if (url) window.open(url, '_blank', 'noopener');
});

$('#applySuccessNext')?.addEventListener('click', () => {
  $('#applySuccessDialog')?.close?.();
  resetForAnotherTicket();
  renderPlanPlaceholder('Aplicação concluída. Aguardando o próximo chamado.');
});
$('#applySuccessStay')?.addEventListener('click', async () => {
  $('#applySuccessDialog')?.close?.();
  clearDraft();
  if (ticketIsLoaded()) {
    setWorkflowStatus(`Chamado #${currentTicketId()} atualizado. Pronto para nova ação sem recarregar a página.`, 'ok');
    await loadExistingTasks().catch(() => {});
  }
});

async function analyzeClosure() {
  const seq = ++analyzeSeq;
  const text = normalizeText($('#closure').value);
  invalidatePlan();
  if (!text.trim()) {
    parsed = null;
    renderTasks();
    setWorkflowStatus('Cole o fechamento para iniciar a análise automática.', 'muted');
    return;
  }
  const readiness = structuredClosureReadiness(text);
  if (!readiness.ready) {
    parsed = null;
    renderTasks();
    setWorkflowStatus(readiness.reason, 'muted');
    return;
  }
  try {
    setWorkflowStatus('Analisando fechamento...', 'muted');
    const previousMap = evidenceMap();
    const result = await api('/api/parse', jsonOpts({ text }));
    if (seq !== analyzeSeq) return;
    parsed = result;
    renderTasks(previousMap);
    log(parsed);
    updateEvidenceState();
    const partial = parsed?.quality?.partial_closure;
    setWorkflowStatus(`${parsed.tasks.length} tarefa(s) detectada(s)${partial ? ' · fechamento parcial' : ''}. Interpretando histórico, título/categoria e gerando Dry Run automático...`, 'muted');
    scheduleClosureReview();
    scheduleAutoPlan((parsed.evidence_ids || []).length === 0 ? 60 : 100);
  } catch (e) {
    if (seq !== analyzeSeq) return;
    parsed = null;
    renderTasks();
    setWorkflowStatus(`Fechamento ainda não está válido: ${e.message}`, 'error');
    log(e.message);
  }
}

function scheduleAnalyze(delay = 120) {
  clearTimeout(analyzeTimer);
  analyzeTimer = setTimeout(analyzeClosure, delay);
}

function renderPlan(p) {
  const root = $('#plan');
  root.className = 'plan';
  root.innerHTML = '';
  const plannedTasks = p.operations.filter((o) => o.op === 'create_task').length;
  const head = document.createElement('div');
  head.innerHTML = `<strong>#${p.ticket.id} · ${esc(p.ticket.title)}</strong><div class="muted small">Usuário técnico da sessão: ID ${p.current_user_id}</div><div class="plan-count">${p.incoming_task_count ?? p.parsed.tasks.length} recebida(s) · ${plannedTasks} nova(s) · ${p.skipped_task_count || 0} já existente(s) · ${p.evidence_count} evidência(s) necessária(s)</div>`;
  root.appendChild(head);
  p.operations.forEach((o) => {
    const d = document.createElement('div');
    d.className = `plan-item${o.sensitive ? ' sensitive' : ''}`;
    if (o.op === 'create_task') d.textContent = `+ Nova tarefa ${o.task_id}: ${o.modality} · ${o.level || '—'} · ${formatDuration(o.actiontime)} · ${o.evidences.length} evidência(s)`;
    else if (o.op === 'contact_receipt') d.textContent = `Primeiro contato: ${o.receipt.at} · ${o.receipt.status} · ID ${o.receipt.message_id}`;
    else if (o.op === 'skip_existing_task') {
      const target = o.existing_task_id ? `tarefa GLPI #${o.existing_task_id}` : (o.existing_logical_id || 'outra tarefa do fechamento');
      const pct = o.score ? ` · ${Math.round(Number(o.score) * 100)}%` : '';
      d.textContent = `✓ ${o.task_id} já representada por ${target} · não será duplicada${pct}`;
      d.classList.add('plan-skip');
    }
    else if (o.op === 'skip_existing_change') {
      d.textContent = `✓ Alteração já refletida no chamado · nenhuma escrita necessária`;
      d.classList.add('plan-skip');
    }
    else if (o.op === 'update_title') d.textContent = `~ Título: ${o.from || '—'} → ${o.to || '—'}`;
    else if (o.op === 'update_category') {
      const match = o.to?.match || {};
      const approx = match.method === 'fuzzy' ? ` · correspondência aproximada ${Math.round((match.score || 0) * 100)}%` : '';
      d.textContent = `~ Categoria: ${o.from.label} → ${o.to.full_name}${approx}`;
      if (match.method === 'fuzzy') d.classList.add('approximate');
    }
    else if (o.op === 'replace_requester') d.textContent = `⚠ Requerente: ${o.current.map((x) => x.label).join(', ') || '—'} → ${o.to.full_name}`;
    else if (o.op === 'add_group') d.textContent = `+ Grupo atribuído: ${o.item?.full_name || '—'}`;
    else if (o.op === 'remove_group') d.textContent = `− Grupo removido: ${o.item?.full_name || '—'}`;
    else if (o.op === 'add_technician') d.textContent = `+ Técnico atribuído: ${o.item?.full_name || '—'}`;
    else if (o.op === 'remove_technician') d.textContent = `− Técnico removido: ${o.item?.full_name || '—'}`;
    else d.textContent = `${o.op}: ${o.item?.full_name || ''}`;
    root.appendChild(d);
  });
}

async function runDryRun({ manual = false } = {}) {
  const pre = prerequisitesForPlan();
  if (!pre.ok) {
    currentPlan = null;
    $('#executeBtn').disabled = true;
    if (manual) {
      log(pre.reason);
      setWorkflowStatus(pre.reason, 'error');
    }
    return;
  }
  const seq = ++planSeq;
  const id = currentTicketId();
  const text = normalizeText($('#closure').value);
  const mapping = evidenceMap();
  const mappingSnapshot = JSON.stringify(mapping);
  try {
    currentPlan = null;
    $('#executeBtn').disabled = true;
    setWorkflowStatus('Gerando Dry Run automático...', 'muted');
    const result = await api('/api/plan', jsonOpts({ ticket_id: id, text, evidence_map: mapping }));
    if (seq !== planSeq) return;
    if (currentTicketId() !== id || normalizeText($('#closure').value) !== text || JSON.stringify(evidenceMap()) !== mappingSnapshot) {
      scheduleAutoPlan();
      return;
    }
    const plannedTasks = result.operations.filter((o) => o.op === 'create_task').length;
    if ((result.incoming_task_count ?? result.parsed.tasks.length) !== result.parsed.tasks.length || plannedTasks !== result.task_count) {
      throw new Error(`Inconsistência interna: recebidas=${result.parsed.tasks.length}, novas=${result.task_count}, operações=${plannedTasks}. Aplicação bloqueada.`);
    }
    currentPlan = result;
    parsed = result.parsed;
    renderTasks(mapping, false);
    renderPlan(result);

    const missing = missingEvidence();
    if (missing.length) {
      $('#executeBtn').disabled = true;
      setWorkflowStatus(`Plano gerado, mas AINDA NÃO está pronto para aplicar: associe as evidências ${missing.join(', ')}. ${result.task_count} tarefa(s) nova(s) aguardando liberação.`, 'muted');
    } else if (!result.has_actionable_operations) {
      $('#executeBtn').disabled = true;
      setWorkflowStatus(`Nada novo para aplicar: ${result.skipped_task_count || 0} tarefa(s) já estão representadas no chamado.`, 'ok');
    } else {
      $('#executeBtn').disabled = false;
      setWorkflowStatus(`Dry Run pronto: ${result.task_count} tarefa(s) nova(s), ${result.skipped_task_count || 0} já existente(s).`, 'ok');
    }
    renderQualityState();
    updateWorkflowRail();
    log(result);
  } catch (e) {
    if (seq !== planSeq) return;
    currentPlan = null;
    $('#executeBtn').disabled = true;
    setWorkflowStatus(`Dry Run não pôde ser gerado: ${e.message}`, 'error');
    log(e.message);
  }
}

function scheduleAutoPlan(delay = 100) {
  clearTimeout(planTimer);
  const pre = prerequisitesForPlan();
  if (!pre.ok) {
    $('#executeBtn').disabled = true;
    if (parsed && missingEvidence().length) setWorkflowStatus(pre.reason, 'muted');
    return;
  }
  planTimer = setTimeout(() => runDryRun(), delay);
}

$('#planBtn').onclick = () => runDryRun({ manual: true });

$('#executeBtn').onclick = async () => {
  if (executionBusy || window.ClosureQueue?.busy) return;
  let sent = false;
  try {
    if (!currentPlan) throw new Error('O Dry Run ainda não está pronto.');
    const afterMode = $('#wbAfterMode')?.value || 'tasks';
    const afterSolution = $('#wbAfterSolution')?.value.trim() || '';
    const applyingTicketId = currentPlan.ticket.id;
    const appliedPlan = currentPlan;
    if (afterMode !== 'tasks' && afterSolution.length < 10) throw new Error('Informe a solução confirmada para concluir após aplicar.');
    const m = evidenceMap();
    const needed = new Set(currentPlan.required_evidence_ids ?? currentPlan.parsed.evidence_ids);
    const missing = [...needed].filter((x) => !m[x]);
    if (missing.length) throw new Error(`Associe arquivos a: ${missing.join(', ')}`);
    const invalidRefs = Object.entries(m).filter(([, fileId]) => !fileEntryById(fileId));
    if (invalidRefs.length) throw new Error(`Mapeamento aponta para arquivo removido: ${invalidRefs.map(([e]) => e).join(', ')}. Gere um novo Dry Run.`);
    setWorkflowStatus('Validando integridade das evidências antes do Apply...', 'muted');
    if (!confirm(`Aplicar exatamente o Dry Run mostrado no GLPI?\n\n${currentPlan.task_count} tarefa(s) nova(s) serão processadas.\n${currentPlan.skipped_task_count || 0} tarefa(s) já existentes serão ignoradas.\nResultado: ${afterMode === 'tasks' ? 'somente tarefas' : afterMode === 'solve' ? 'solucionar' : 'fechar'}.\n${afterMode !== 'tasks' ? afterSolution : ''}`)) {
      setWorkflowStatus('Dry Run pronto. Aplicação cancelada pelo usuário.', 'ok');
      return;
    }

    const fd = new FormData();
    fd.append('ticket_id', currentPlan.ticket.id);
    fd.append('text', normalizeText($('#closure').value));
    fd.append('evidence_map', JSON.stringify(m));
    fd.append('plan_id', currentPlan.plan_id);
    const usedIds = new Set(Object.values(m));
    files.filter((entry) => usedIds.has(entry.id)).forEach((entry) => {
      fd.append('file_ids', entry.id);
      fd.append('files', entry.file, entry.file.name);
    });

    sent = true;
    executionBusy = true;
    $('#operacao').inert = true;
    $('.workspace-nav').inert = true;
    $('#executeBtn').disabled = true;
    setWorkflowStatus(`Aplicando ${currentPlan.task_count} tarefa(s) no GLPI...`, 'muted');
    log('Aplicando alterações...');
    const d = await api('/api/execute', { method: 'POST', body: fd });
    log(d);
    currentPlan = null;
    $('#executeBtn').disabled = true;

    // Atualiza o estado da aplicação sem exigir reload do navegador e sem
    // gerar automaticamente outro plano que duplicaria o mesmo fechamento.
    try {
      currentTicket = await fetchTicket(currentTicketId());
      renderTicketSummary(currentTicket);
    } catch (refreshError) {
      log({ execution: d, refresh_error: refreshError.message });
    }
    if (!d.ok) await loadExistingTasks();

    if (d.ok) {
      if (afterMode !== 'tasks') {
        await window.finishAfterFormalization(applyingTicketId, afterSolution, afterMode);
        $('#wbAfterMode').value = 'tasks';
        $('#wbAfterSolution').value = '';
      }
      const successMessage = `∞ Aplicação confirmada: ${d.verified_task_count}/${d.expected_task_count} tarefa(s) nova(s). Escolha manter o chamado ou seguir para o próximo.`;
      executionBusy = false;
      setWorkflowStatus(successMessage, 'ok');
      renderPlanPlaceholder('Aplicação concluída. Use o recibo visual para escolher o próximo passo.');
      showApplySuccess(d, appliedPlan, afterMode);
      window.ClosureQueue?.complete(applyingTicketId, fd.get('text'));
      resetForAnotherTicket();
      void refreshBridgeInbox();
    } else {
      const failed = (d.errors || []).map((x) => `${x.task || 'execução'} · ${x.stage}: ${x.message}`).join('\n');
      setWorkflowStatus(`Execução parcial: ${d.verified_task_count}/${d.expected_task_count} tarefas confirmadas. Revise a lista de tarefas abaixo.`, 'error');
      alert(`Execução parcial.\n${d.verified_task_count}/${d.expected_task_count} tarefas confirmadas.\n\n${failed || 'Consulte o log.'}`);
    }
  } catch (e) {
    log(e.message);
    setWorkflowStatus(e.message, 'error');
    if (sent) {
      currentPlan = null;
      $('#executeBtn').disabled = true;
      await loadExistingTasks();
    }
  } finally {
    executionBusy = false;
    $('#operacao').inert = false;
    $('.workspace-nav').inert = false;
  }
};

$('#clearDraftBtn').onclick = () => {
  if ($('#closure').value.trim() || files.length || parsed) {
    if (!confirm('Limpar o texto, tarefas detectadas, evidências e Dry Run atual?')) return;
  }
  clearDraft();
  renderPlanPlaceholder('Rascunho limpo. Pronto para um novo fechamento.');
  setWorkflowStatus('Rascunho limpo.', 'ok');
};

$('#closure').addEventListener('input', () => {
  invalidatePlan('Fechamento alterado. Reanalisando automaticamente...');
  scheduleAnalyze();
});

$('#closure').addEventListener('paste', () => {
  invalidatePlan('Texto colado. Analisando automaticamente...');
  scheduleAnalyze(0);
});

$('#ticketId').addEventListener('input', () => {
  if (currentTicket && currentTicket.id !== currentTicketId()) {
    currentTicket = null;
    $('#ticketSummary').textContent = 'Número alterado. Clique em Procurar ou pressione Enter.';
    $('#refreshTicket').disabled = true;
    $('#refreshTasks').disabled = true;
    $('#ticketEditor').classList.add('hidden');
    $('#manualTaskCreator').classList.add('hidden');
    $('#existingTasks').className = 'existing-tasks muted';
    $('#existingTasks').textContent = 'Procure o novo chamado para visualizar as tarefas.';
  }
  invalidatePlan('Número do chamado alterado. Procure o chamado novamente.');
});


async function copyAiPrompt() {
  const button = $('#copyAiPrompt');
  const status = $('#promptCopyStatus');
  try {
    button.disabled = true;
    status.textContent = 'Carregando prompt…';
    const data = await api('/api/ai/prompt');
    await navigator.clipboard.writeText(data.prompt || '');
    status.className = 'ok small';
    status.textContent = 'Prompt 2.3 copiado. Use no ChatGPT ou Gemini.';
  } catch (e) {
    status.className = 'error small';
    status.textContent = `Não foi possível copiar: ${e.message}`;
  } finally {
    button.disabled = false;
  }
}

$('#copyAiPrompt')?.addEventListener('click', copyAiPrompt);

// Navigation is owned by workbench.js.

init();
