'use strict';

const $ = (id) => document.getElementById(id);
let currentStatus = null;
let currentTabContext = null;

function setMessage(text = '', kind = '') { const el = $('message'); el.textContent = text; el.className = `message footer-message ${kind}`.trim(); }
function setPairMessage(text = '', kind = '') { const el = $('pairMessage'); el.textContent = text; el.className = `message ${kind}`.trim(); }
function formatPairCode(value) { const digits = String(value || '').replace(/\D/g, '').slice(0, 6); return digits.length > 3 ? `${digits.slice(0, 3)}-${digits.slice(3)}` : digits; }
function timeAgo(timestamp) { const value = Number(timestamp || 0); if (!value) return '—'; const seconds = Math.max(0, Math.round((Date.now() - value) / 1000)); if (seconds < 10) return 'agora'; if (seconds < 60) return `${seconds}s atrás`; if (seconds < 3600) return `${Math.floor(seconds / 60)} min atrás`; return `${Math.floor(seconds / 3600)}h atrás`; }
async function ask(message) { return browser.runtime.sendMessage(message); }

function knownProvider(url) { return url.startsWith('https://chatgpt.com/') || url.startsWith('https://gemini.google.com/'); }
function activatable(url) { return /^https:\/\//.test(url) && !url.startsWith('https://addons.mozilla.org/') && !url.startsWith('https://support.mozilla.org/'); }
function originPattern(url) { try { return `${new URL(url).origin}/*`; } catch { return ''; } }

async function hasSitePermission(url) {
  if (knownProvider(url)) return true;
  const origin = originPattern(url);
  if (!origin) return false;
  try { return await browser.permissions.contains({ origins: [origin] }); } catch { return false; }
}

async function injectBridge(tabId) {
  await browser.scripting.executeScript({ target: { tabId }, files: ['capture.js'] });
  await browser.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
}

async function getTabContext() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  const url = String(tab?.url || '');
  if (!tab?.id) return { supported: false, activatable: false, tabId: null, url, health: null };
  const permitted = await hasSitePermission(url);
  if (permitted) {
    try {
      const health = await browser.tabs.sendMessage(tab.id, { type: 'bridge:health' });
      return { supported: true, permitted: true, activatable: false, tabId: tab.id, url, health };
    } catch (error) {
      return { supported: true, permitted: true, activatable: false, tabId: tab.id, url, health: null, error: error?.message || String(error) };
    }
  }
  return { supported: false, permitted: false, activatable: activatable(url), tabId: tab.id, url, health: null };
}

function renderLastSend(lastSend, lastDetected, outbox = []) {
  const card = $('lastSendCard');
  const detectedNewer = !!lastDetected && (!lastSend || Number(lastDetected.at || 0) > Number(lastSend.at || 0) + 100);
  const display = detectedNewer ? lastDetected : lastSend;
  if (!display) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  const raw = String(display.provider || 'IA');
  const provider = /gemini/i.test(raw) ? 'Gemini' : /chatgpt/i.test(raw) ? 'ChatGPT' : raw === 'generic' ? 'IA web' : 'IA';
  $('lastSendEyebrow').textContent = detectedNewer ? 'FECHAMENTO ATUAL' : 'ÚLTIMO ENVIO';
  $('lastSendTitle').textContent = `#${display.ticket_id || '—'} · ${provider}`;
  $('lastSendMeta').textContent = `${display.task_count || '—'} tarefa(s) · ${timeAgo(display.at)}`;
  const state = $('lastSendState');
  const queuedItem = (outbox || []).find((item) => Number(item.ticket_id) === Number(display.ticket_id));
  const queued = detectedNewer ? !!queuedItem : !!lastSend?.queued;
  state.className = `mini-state ${queued || lastSend?.duplicate || detectedNewer ? 'warn' : lastSend?.ok ? '' : 'bad'}`.trim();
  state.textContent = detectedNewer ? (queued ? 'Na fila' : 'Detectado') : queued ? 'Na fila' : lastSend?.evidence_pending ? 'Texto recebido · prints pendentes' : lastSend?.ok ? (lastSend?.duplicate ? 'Já recebido' : 'ACK recebido') : 'Falhou';
}

function render(status, tabContext) {
  currentStatus = status; currentTabContext = tabContext;
  const reachable = !!status?.assistant?.reachable;
  const paired = !!status?.paired;
  const online = paired && !!status?.ping?.ok;
  const info = status?.assistant?.info || {};
  const health = tabContext?.health || null;
  const latest = health?.latest || null;
  const outboxCount = Number(status?.outbox?.count || 0);

  $('assistantState').textContent = reachable ? `Online · v${info.assistant_version || '?'}` : 'Offline';
  $('pairState').textContent = paired ? (online ? 'Conectado' : 'Pareado') : 'Não pareado';
  $('versions').textContent = `Bridge v${status?.extensionVersion || '2.4.1'} · Assistant ${info.assistant_version || '—'} · protocolo ${info.protocol || 2}`;
  $('outboxState').textContent = outboxCount ? `${outboxCount} pacote(s) aguardando ACK` : 'Outbox vazia · ACK sincronizado';
  const recovery = health?.evidence_recovery || null;
  const recoveryFresh = recovery?.at && Date.now() - Number(recovery.at) < 120000;
  $('resilienceNote').textContent = health?.evidence?.count
    ? `${health.evidence.count} print(s) persistido(s) nesta conversa.${recoveryFresh ? ` Recuperação do prompt: ${recovery.recovered}/${recovery.required}.` : ''}`
    : recoveryFresh && recovery.required
      ? `Recuperação do primeiro prompt: ${recovery.recovered}/${recovery.required} (${recovery.source}).`
      : 'Contrato GLPI_ASSISTANT + prints persistentes + recuperação do primeiro prompt + watchdog.';

  const badge = $('statusBadge');
  badge.className = `status-badge ${online ? (outboxCount ? 'warn' : 'good') : paired ? 'warn' : reachable ? 'neutral' : 'bad'}`;
  $('statusBadgeText').textContent = online ? (outboxCount ? 'Fila pendente' : 'Conectado') : paired ? 'Pareado' : reachable ? 'Não pareado' : 'Offline';

  let providerText = tabContext?.activatable ? 'IA web · ativação disponível' : 'Abra uma IA compatível';
  if (tabContext?.supported) {
    const label = health?.provider_label || new URL(tabContext.url).hostname;
    providerText = health?.capture_active ? `${label} · capturador ativo` : `${label} · reparar capturador`;
  }
  $('providerState').textContent = providerText;
  $('captureState').textContent = tabContext?.activatable ? 'Permissão ainda não concedida' : !tabContext?.supported ? 'Aba não compatível' : health?.capture_active ? `${health.provider_label} ativo${health.generating ? ' · gerando' : ''}` : 'Script não respondeu';
  $('diagSummary').textContent = online && health?.capture_active ? (outboxCount ? 'Fila pendente' : 'Tudo pronto') : online ? 'Verificar IA' : paired ? 'Assistant offline' : 'Não pareado';

  $('activateSite').classList.toggle('hidden', !tabContext?.activatable);
  $('repairCapture').disabled = !tabContext?.supported;
  $('flushOutbox').disabled = !paired || !outboxCount;
  $('pairPanel').classList.toggle('hidden', paired);
  $('settingsPanel').classList.toggle('hidden', !paired);
  $('disconnect').classList.toggle('hidden', !paired);

  const settings = status?.settings || {};
  $('autoSend').checked = settings.autoSend !== false;
  $('openIfClosed').checked = settings.openIfClosed !== false;
  $('focusOnSend').checked = !!settings.focusOnSend;

  const sendBtn = $('sendLast'); const sendText = $('sendLastText'); const hint = $('sendHint');
  const canSend = paired && tabContext?.supported && !!health?.capture_active && !!latest;
  sendBtn.disabled = !canSend;
  if (!paired) { sendText.textContent = 'Pareie o Bridge para enviar'; hint.textContent = 'A credencial fica no perfil local do Firefox.'; }
  else if (tabContext?.activatable) { sendText.textContent = 'Ative o Bridge nesta IA'; hint.textContent = 'A permissão é concedida apenas ao domínio atual.'; }
  else if (!tabContext?.supported) { sendText.textContent = 'Abra uma IA compatível'; hint.textContent = 'ChatGPT/Gemini funcionam direto; outras IAs HTTPS podem ser ativadas por domínio.'; }
  else if (!health?.capture_active) { sendText.textContent = 'Capturador precisa de reparo'; hint.textContent = 'Use “Reparar capturador”; não é necessário recarregar a conversa.'; }
  else if (!latest) { sendText.textContent = health?.generating ? 'Aguardando fechamento terminar…' : 'Nenhum fechamento detectado'; hint.textContent = 'Procuro o contrato [GLPI_ASSISTANT:<ID>] independentemente da IA.'; }
  else {
    const count = Number(latest.packet_count || 1);
    sendText.textContent = count > 1 ? `Enviar ${count} chamados · ${latest.ticket_ids.join(', ')}` : `Enviar #${latest.ticket_id} · ${latest.task_count} tarefa(s)`;
    hint.textContent = count > 1 ? 'Cada chamado será validado, enfileirado e confirmado separadamente.' : `${(latest.task_ids || []).join(', ')}${latest.has_changes ? ' · alterações incluídas' : ''}`;
  }

  renderLastSend(status?.lastSend, status?.lastDetected, status?.outbox?.items || []);
  if (!reachable) setMessage(outboxCount ? `Assistant offline. ${outboxCount} pacote(s) permanecem seguros na fila local.` : 'O Assistant não respondeu em 127.0.0.1:8765.', outboxCount ? 'warn' : 'bad');
  else if (!paired) setMessage('Gere um código de pareamento no Assistant.', 'warn');
  else if (online && health?.capture_active) setMessage(outboxCount ? 'Captura ativa. Há envios aguardando ACK; o Bridge tentará novamente.' : 'Captura e entrega com ACK prontas.', outboxCount ? 'warn' : 'ok');
  else if (online) setMessage('Assistant conectado. Ative ou repare o capturador nesta IA.', 'warn');
  else setMessage('Pareado, mas o Assistant não confirmou a sessão.', 'warn');
}

async function refresh() {
  $('refresh').disabled = true; setMessage('Verificando Assistant, outbox e capturador…');
  try { const [status, tabContext] = await Promise.all([ask({ type: 'bridge:status' }), getTabContext()]); render(status, tabContext); }
  catch (error) { setMessage(error?.message || String(error), 'bad'); }
  finally { $('refresh').disabled = false; }
}

$('pairCode').addEventListener('input', (event) => { event.target.value = formatPairCode(event.target.value); $('pairBtn').disabled = event.target.value.replace(/\D/g, '').length !== 6; });
$('pairCode').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !$('pairBtn').disabled) $('pairBtn').click(); });
$('pairBtn').onclick = async () => { $('pairBtn').disabled = true; setPairMessage('Pareando…'); try { const result = await ask({ type: 'bridge:pair', code: $('pairCode').value }); setPairMessage(`Conectado ao Assistant v${result.assistant_version}.`, 'ok'); $('pairCode').value = ''; await refresh(); } catch (error) { setPairMessage(error?.message || String(error), 'bad'); } finally { $('pairBtn').disabled = $('pairCode').value.replace(/\D/g, '').length !== 6; } };

for (const id of ['autoSend', 'openIfClosed', 'focusOnSend']) $(id).addEventListener('change', async () => { try { await ask({ type: 'bridge:settings:set', settings: { autoSend: $('autoSend').checked, openIfClosed: $('openIfClosed').checked, focusOnSend: $('focusOnSend').checked } }); setMessage('Preferências atualizadas.', 'ok'); } catch (error) { setMessage(error?.message || String(error), 'bad'); } });

$('activateSite').onclick = async () => {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  const origin = originPattern(tab?.url || '');
  if (!tab?.id || !origin) return;
  $('activateSite').disabled = true;
  try {
    const granted = await browser.permissions.request({ origins: [origin] });
    if (!granted) throw new Error('Permissão não concedida para esta IA.');
    await injectBridge(tab.id);
    setMessage(`Bridge 2.4.1 ativado somente em ${new URL(tab.url).hostname}.`, 'ok');
    await refresh();
  } catch (error) { setMessage(error?.message || String(error), 'bad'); }
  finally { $('activateSite').disabled = false; }
};

$('repairCapture').onclick = async () => {
  const context = await getTabContext();
  if (!context.tabId) return;
  $('repairCapture').disabled = true; setMessage('Reinjetando e verificando o capturador…');
  try {
    await injectBridge(context.tabId);
    const result = await browser.tabs.sendMessage(context.tabId, { type: 'bridge:repair' });
    setMessage(`Capturador reparado · ${result?.evidence?.count || 0} print(s) preservado(s).`, 'ok');
    await refresh();
  } catch (error) { setMessage(error?.message || String(error), 'bad'); }
  finally { $('repairCapture').disabled = false; }
};

$('flushOutbox').onclick = async () => { $('flushOutbox').disabled = true; setMessage('Reenviando fila local…'); try { const result = await ask({ type: 'bridge:outbox:flush' }); setMessage(result?.pending ? `${result.pending} pacote(s) ainda aguardando ACK.` : `${result?.sent || 0} pacote(s) confirmados. Outbox vazia.`, result?.pending ? 'warn' : 'ok'); await refresh(); } catch (error) { setMessage(error?.message || String(error), 'bad'); } finally { $('flushOutbox').disabled = false; } };
$('cleanupEvidence').onclick = async () => { $('cleanupEvidence').disabled = true; setMessage('Limpando evidências expiradas…'); try { const result = await ask({ type: 'bridge:evidence:cleanup', force: false }); setMessage(`${result?.removed || 0} print(s) expirado(s) removido(s); ${result?.kept || 0} preservado(s).`, 'ok'); await refresh(); } catch (error) { setMessage(error?.message || String(error), 'bad'); } finally { $('cleanupEvidence').disabled = false; } };

async function selectedPopupImages(packetCount) {
  const picked = [...$('bridgePrints').files];
  if (!picked.length) return new Map();
  if (picked.length > 30 || picked.reduce((n, f) => n + f.size, 0) > 20 * 1024 * 1024) throw Error('Limite de 30 imagens e 20 MiB.');
  const byTicket = new Map();
  for (const f of picked) {
    if (f.size > 8 * 1024 * 1024) throw Error('Limite de 8 MiB por imagem.');
    const evidence = /(?:^|[-_ ])(E\d{2,3})(?:\.|[-_ ])/i.exec(f.name)?.[1]?.toUpperCase();
    const ticket = /(?:^|[-_ ])(\d{5,8})(?:[-_ ])/i.exec(f.name)?.[1];
    if (!evidence) throw Error('Nomeie os prints E01.png… ou 901676-E01.png.');
    if (packetCount > 1 && !ticket) throw Error('Para múltiplos chamados, nomeie cada print como 901676-E01.png para evitar associação cruzada.');
    const data = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = reject; r.readAsDataURL(f); });
    const key = ticket || '*'; if (!byTicket.has(key)) byTicket.set(key, []); byTicket.get(key).push({ id: evidence, data });
  }
  return byTicket;
}

$('sendLast').onclick = async () => {
  $('sendLast').disabled = true; setMessage('Validando os pacotes detectados…');
  try {
    const context = await getTabContext();
    if (!context.supported || !context.tabId) throw new Error('Ative o Bridge nesta IA antes de enviar.');
    const packets = await browser.tabs.sendMessage(context.tabId, { type: 'bridge:extract-all' });
    if (!packets?.length) throw new Error('Não encontrei nenhum [GLPI_ASSISTANT:<chamado>] completo nesta resposta.');
    const manualImages = await selectedPopupImages(packets.length);
    let queued = 0; let ack = 0;
    for (const packet of packets) {
      const images = manualImages.get(String(packet.ticket_id)) || manualImages.get('*');
      if (images?.length) packet.images = images;
      const result = await ask({ type: 'bridge:handoff', payload: packet, manual: true });
      if (result?.acknowledged) ack += 1; else if (result?.queued) queued += 1;
    }
    setMessage(queued ? `${ack} confirmado(s); ${queued} protegido(s) na outbox aguardando ACK.` : `${ack} chamado(s) recebidos pelo Assistant.`, queued ? 'warn' : 'ok');
    await refresh();
  } catch (error) { setMessage(error?.message || String(error), 'bad'); }
};

$('openAssistant').onclick = async () => { try { setMessage('Abrindo Assistant…'); await ask({ type: 'bridge:open-assistant' }); window.close(); } catch (error) { setMessage(error?.message || String(error), 'bad'); } };
$('refresh').onclick = refresh;
$('disconnect').onclick = async () => { $('disconnect').disabled = true; if (!confirm('Revogar este pareamento no Assistant? A outbox local será preservada, mas não poderá ser entregue sem novo pareamento.')) { $('disconnect').disabled = false; return; } try { setMessage('Revogando pareamento…'); await ask({ type: 'bridge:disconnect' }); setMessage('Pareamento revogado.', 'ok'); await refresh(); } catch (error) { setMessage(error?.message || String(error), 'bad'); } finally { $('disconnect').disabled = false; } };
$('bridgePrints').onchange = () => { $('bridgePrintNames').textContent = [...$('bridgePrints').files].map((f) => f.name).join(' → '); };
$('captureGlpi').onclick = async () => { try { setMessage('Consultando a aba do GLPI…'); const r = await ask({ type: 'bridge:capture-glpi' }); setMessage(`Referência #${r.ticket_id} enviada.`, 'ok'); } catch (e) { setMessage(e.message, 'bad'); } };

refresh().then(() => { if (!$('pairPanel').classList.contains('hidden')) $('pairCode').focus(); });
