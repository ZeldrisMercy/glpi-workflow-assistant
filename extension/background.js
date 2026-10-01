'use strict';

// GLPI Assistant Bridge 2.4.1 background transport.
// Handoffs are first persisted to a local outbox. They leave the outbox only
// after an explicit HTTP acknowledgement from the Assistant.
const ASSISTANT_ORIGIN = 'http://127.0.0.1:8765';
const EXTENSION_VERSION = browser.runtime.getManifest().version;
const OUTBOX_KEY = 'bridgeOutbox22';
const DETECTED_KEY = 'bridgeLastDetected222';
const CAPTURE_KEY = 'captureState22';
const CAPTURE_OUTBOX_KEY = 'bridgeCaptureOutbox34';
const CAPTURE_TTL_MS = 12 * 60 * 60 * 1000;
const MAX_OUTBOX = 20;
const DEFAULT_SETTINGS = Object.freeze({ autoSend: true, openIfClosed: true, focusOnSend: false, evidenceRetentionHours: 12 });
let flushPromise = null;

async function readState() {
  const stored = await browser.storage.local.get(['bridgeToken', 'settings', 'lastSend', DETECTED_KEY, OUTBOX_KEY, CAPTURE_OUTBOX_KEY]);
  return {
    bridgeToken: stored.bridgeToken || '',
    settings: { ...DEFAULT_SETTINGS, ...(stored.settings || {}) },
    lastSend: stored.lastSend || null,
    lastDetected: stored[DETECTED_KEY] || null,
    outbox: Array.isArray(stored[OUTBOX_KEY]) ? stored[OUTBOX_KEY] : [],
    captureOutbox: Array.isArray(stored[CAPTURE_OUTBOX_KEY]) ? stored[CAPTURE_OUTBOX_KEY] : [],
  };
}

async function enqueueCapture(snapshot) {
  if (!snapshot?.prompt_id || !Array.isArray(snapshot.attachments) || !snapshot.attachments.length) return { ok: true, skipped: true };
  const state = await readState();
  const existing = state.captureOutbox.find((item) => item.prompt_id === snapshot.prompt_id);
  if (existing) return existing;
  const item = { ...snapshot, created_at: Date.now(), attempts: 0, last_error: null };
  await browser.storage.local.set({ [CAPTURE_OUTBOX_KEY]: [...state.captureOutbox.slice(-MAX_OUTBOX + 1), item] });
  return item;
}

async function flushCaptureOutbox() {
  const state = await readState();
  if (!state.bridgeToken || !state.captureOutbox.length) return { ok: true, sent: 0, pending: state.captureOutbox.length };
  const keep = [];
  let sent = 0;
  for (const item of state.captureOutbox) {
    try {
      const response = await localFetch('/api/bridge/captures', { method: 'POST', body: JSON.stringify(item) }, { token: state.bridgeToken, timeoutMs: 30000 });
      const allAcked = item.attachments.every((attachment) => attachment.digest && (response.attachments || []).some((ack) => ack.attachment_id === attachment.attachment_id && ack.digest === attachment.digest));
      if (!allAcked) keep.push({ ...item, attempts: item.attempts + 1, last_error: 'ACK parcial de captura' });
      else sent += 1;
    } catch (error) { keep.push({ ...item, attempts: item.attempts + 1, last_error: error.message, last_attempt_at: Date.now() }); }
  }
  await browser.storage.local.set({ [CAPTURE_OUTBOX_KEY]: keep });
  return { ok: keep.length === 0, sent, pending: keep.length };
}

async function writeSettings(patch) {
  const state = await readState();
  const settings = { ...state.settings, ...(patch || {}) };
  await browser.storage.local.set({ settings });
  return settings;
}

async function writeLastSend(patch) {
  const item = { at: Date.now(), ...(patch || {}) };
  await browser.storage.local.set({ lastSend: item });
  return item;
}

async function writeOutbox(items) {
  const clean = (items || []).slice(-MAX_OUTBOX);
  await browser.storage.local.set({ [OUTBOX_KEY]: clean });
  return clean;
}

function sampledHash(text) {
  const value = String(text || '');
  let hash = 2166136261;
  const step = Math.max(1, Math.floor(value.length / 4096));
  for (let i = 0; i < value.length; i += step) {
    hash ^= value.charCodeAt(i); hash = Math.imul(hash, 16777619);
  }
  hash ^= value.length; hash = Math.imul(hash, 16777619);
  return (hash >>> 0).toString(36);
}

function payloadFingerprint(payload) {
  const images = (payload?.images || []).map((x) => `${x.id || ''}:${sampledHash(x.data || '')}`).join('|');
  return `${payload?.conversation_key||''}:${payload?.operation||''}:${Number(payload?.ticket_id || 0)}:${sampledHash(payload?.closure || '')}:${sampledHash(images)}`;
}

async function localFetch(path, options = {}, { token = null, timeoutMs = 7000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${ASSISTANT_ORIGIN}${path}`, { ...options, headers, signal: controller.signal, cache: 'no-store' });
    let data = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) data = await response.json();
    else data = { detail: await response.text() };
    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : `HTTP ${response.status}`;
      const error = new Error(detail); error.status = response.status; throw error;
    }
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error('Tempo esgotado ao acessar o GLPI Assistant local.');
    throw error;
  } finally { clearTimeout(timer); }
}

async function assistantInfo() {
  try { return { reachable: true, info: await localFetch('/api/bridge/info', { method: 'GET' }, { timeoutMs: 3000 }) }; }
  catch (error) { return { reachable: false, error: error.message }; }
}

function knownProviderUrl(url = '') {
  return /^https:\/\/(?:chatgpt\.com|gemini\.google\.com)\//i.test(String(url || ''));
}

function sitePattern(url = '') {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return '';
    return `${parsed.origin}/*`;
  } catch { return ''; }
}

async function injectGenericBridge(tabId, url) {
  if (!tabId || knownProviderUrl(url)) return false;
  const origin = sitePattern(url);
  if (!origin) return false;
  try {
    const allowed = await browser.permissions.contains({ origins: [origin] });
    if (!allowed) return false;
    await browser.scripting.executeScript({ target: { tabId }, files: ['capture.js'] });
    await browser.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    return true;
  } catch { return false; }
}

async function restoreGenericBridges() {
  try {
    const tabs = await browser.tabs.query({});
    await Promise.allSettled((tabs || []).filter((tab) => tab?.id && tab?.url).map((tab) => injectGenericBridge(tab.id, tab.url)));
  } catch {}
}

async function setToolbarState(state) {
  const map = {
    connected: { text: '∞', color: '#2fcfff', title: 'GLPI Assistant Bridge · conectado' },
    queued: { text: '↻', color: '#8a65ff', title: 'GLPI Assistant Bridge · envio na fila local' },
    offline: { text: '!', color: '#8a65ff', title: 'GLPI Assistant Bridge · Assistant offline' },
    unpaired: { text: '', color: '#2fcfff', title: 'GLPI Assistant Bridge · não pareado' },
    sending: { text: '↗', color: '#54e4ff', title: 'GLPI Assistant Bridge · enviando' },
  };
  const item = map[state] || map.unpaired;
  try {
    await browser.action.setBadgeText({ text: item.text });
    if (item.text) await browser.action.setBadgeBackgroundColor({ color: item.color });
    await browser.action.setTitle({ title: item.title });
  } catch {}
}

async function ping(token = null) {
  const bridgeToken = token ?? (await readState()).bridgeToken;
  if (!bridgeToken) return { ok: false, paired: false };
  try {
    const data = await localFetch('/api/bridge/ping', { method: 'POST', body: JSON.stringify({ extension_version: EXTENSION_VERSION }) }, { token: bridgeToken, timeoutMs: 3500 });
    const { outbox } = await readState();
    await setToolbarState(outbox.length ? 'queued' : 'connected');
    return { ok: true, paired: true, data };
  } catch (error) {
    if (error.status === 401) {
      if (browser.storage.local.remove) await browser.storage.local.remove('bridgeToken');
      await setToolbarState('unpaired');
      return { ok: false, paired: false, invalidToken: true, error: error.message };
    }
    await setToolbarState('offline');
    return { ok: false, paired: true, error: error.message };
  }
}

async function pair(code) {
  const digits = String(code || '').replace(/\D/g, '');
  if (digits.length !== 6) throw new Error('Digite os 6 dígitos exibidos no GLPI Assistant.');
  const data = await localFetch('/api/bridge/pair', { method: 'POST', body: JSON.stringify({ code: digits, extension_version: EXTENSION_VERSION }) }, { timeoutMs: 5000 });
  if (!data.bridge_token) throw new Error('O Assistant não retornou o Bridge Token.');
  await browser.storage.local.set({ bridgeToken: data.bridge_token });
  await setToolbarState('connected');
  void flushOutbox();
  return data;
}

async function disconnect() {
  const { bridgeToken } = await readState();
  if (!bridgeToken) { await setToolbarState('unpaired'); return { ok: true, alreadyUnpaired: true }; }
  try { await localFetch('/api/bridge/unpair', { method: 'POST' }, { token: bridgeToken, timeoutMs: 3500 }); }
  catch (error) {
    const wrapped = new Error(`Não foi possível revogar o pareamento no Assistant: ${error.message} O token local foi mantido.`);
    wrapped.code = 'revocation-failed'; throw wrapped;
  }
  if (browser.storage.local.remove) await browser.storage.local.remove(['bridgeToken', 'lastSend']);
  else await browser.storage.local.set({ bridgeToken: '', lastSend: null });
  await setToolbarState('unpaired');
  return { ok: true };
}

async function findAssistantTabs() {
  const tabs = await browser.tabs.query({ url: ['http://127.0.0.1/*'] });
  return tabs.filter((tab) => String(tab.url || '').startsWith(`${ASSISTANT_ORIGIN}/`));
}

async function ensureAssistantTab(settings) {
  const tabs = await findAssistantTabs();
  if (tabs.length) {
    const tab = tabs[0];
    if (settings.focusOnSend) await browser.tabs.update?.(tab.id, { active: true });
    return { reused: true, opened: false, tabId: tab.id };
  }
  if (!settings.openIfClosed) return { reused: false, opened: false, tabId: null };
  const tab = await browser.tabs.create({ url: `${ASSISTANT_ORIGIN}/`, active: !!settings.focusOnSend });
  return { reused: false, opened: true, tabId: tab.id };
}

function validatePayload(payload) {
  const closure = String(payload?.closure || '').trim();
  if(payload?.operation==='create_proactive'){
    if(!closure.includes('[GLPI_PROACTIVE]')||!payload.conversation_key)throw new Error('Proativo sem referência de origem');
    return {closure,ticketId:0};
  }
  if (!closure) throw new Error('Nenhum fechamento estruturado foi detectado.');
  const markerIds = [...new Set([...closure.matchAll(/\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]/gi)].map((m) => Number(m[1])))];
  const suppliedId = Number(payload?.ticket_id || 0);
  if (markerIds.length > 1 || (suppliedId && markerIds.length && suppliedId !== markerIds[0])) throw new Error('Os números do chamado divergem no fechamento. Corrija antes de enviar.');
  const ticketId = suppliedId || markerIds[0];
  if (!Number.isSafeInteger(ticketId) || ticketId <= 0) throw new Error('Número ausente. Peça à IA para iniciar com [GLPI_ASSISTANT:<número real>].');
  return { closure, ticketId };
}

async function enqueueHandoff(payload, manual) {
  const { closure, ticketId } = validatePayload(payload);
  const normalized = {
    version: 2,
    ...(payload.operation==='create_proactive'?{operation:payload.operation,prompt_timestamp:payload.prompt_timestamp,conversation_key:payload.conversation_key}:{}),
    source: `${String(payload?.provider || 'ai').replace(/[^a-z0-9_-]/gi, '') || 'ai'}-firefox-extension`,
    ticket_id: ticketId,
    closure,
    images: payload.images || [],
    manual: !!manual,
  };
  const key = payloadFingerprint(normalized);
  const state = await readState();
  const existing = state.outbox.find((item) => item.key === key);
  if (existing) return existing;
  const item = { key, created_at: Date.now(), attempts: 0, last_error: null, provider: payload?.provider || 'ai', task_count: Number(payload?.task_count || 0), payload: normalized };
  if (state.outbox.length >= MAX_OUTBOX) throw new Error(`A fila local do Bridge atingiu ${MAX_OUTBOX} envios. Abra o Assistant e use “Reenviar fila” antes de continuar.`);
  await writeOutbox([...state.outbox, item]);
  return item;
}

async function noteDetectedContract(packet = {}) {
  const ticketId = Number(packet.ticket_id || 0);
  if (!Number.isSafeInteger(ticketId) || ticketId <= 0) return { ok: false };
  const item = {
    at: Date.now(),
    ticket_id: ticketId,
    provider: String(packet.provider || 'ai').slice(0, 40),
    task_count: Number(packet.task_count || 0),
    task_ids: Array.isArray(packet.task_ids) ? packet.task_ids.slice(0, 30) : [],
    fingerprint: String(packet.fingerprint || '').slice(0, 120),
  };
  const previous = (await browser.storage.local.get(DETECTED_KEY))[DETECTED_KEY];
  if (!previous || previous.fingerprint !== item.fingerprint || previous.ticket_id !== item.ticket_id) {
    await browser.storage.local.set({ [DETECTED_KEY]: item });
  }
  return { ok: true, detected: item };
}

function captureSignature(data) {
  const value = String(data || '');
  return `${value.length}:${sampledHash(value)}`;
}

async function cleanupExpiredEvidence({ force = false } = {}) {
  const state = await readState();
  const stored = (await browser.storage.local.get(CAPTURE_KEY))[CAPTURE_KEY];
  if (!stored || !Array.isArray(stored.files)) return { ok: true, removed: 0, kept: 0 };
  const protectedHashes = new Set();
  for (const item of state.outbox) for (const image of item?.payload?.images || []) protectedHashes.add(captureSignature(image?.data));
  const retentionHours = Math.min(72, Math.max(1, Number(state.settings.evidenceRetentionHours || 12)));
  const cutoff = Date.now() - retentionHours * 60 * 60 * 1000;
  const fallbackTime = Number(stored.updated_at || 0) || Date.now();
  const kept = [];
  let removed = 0;
  for (const file of stored.files) {
    const createdAt = Number(file?.created_at || fallbackTime);
    const protectedByOutbox = protectedHashes.has(captureSignature(file?.data));
    if (!force && (protectedByOutbox || createdAt >= cutoff)) kept.push(file);
    else if (force && protectedByOutbox) kept.push(file);
    else removed += 1;
  }
  if (kept.length) await browser.storage.local.set({ [CAPTURE_KEY]: { ...stored, files: kept, updated_at: Date.now() } });
  else await browser.storage.local.remove(CAPTURE_KEY);
  const result = { ok: true, removed, kept: kept.length, retention_hours: retentionHours, protected: protectedHashes.size };
  if (removed) {
    try {
      const tabs = await browser.tabs.query({});
      await Promise.allSettled((tabs || []).filter(t => t.id).map(t => browser.tabs.sendMessage?.(t.id, { type: 'bridge:evidence-cleaned', result })));
    } catch {}
  }
  return result;
}

async function cleanupCapturedEvidence(item) {
  const images = item?.payload?.images || [];
  if (!images.length) return;
  try {
    const key = 'captureState22';
    const stored = (await browser.storage.local.get(key))[key];
    if (!stored || !Array.isArray(stored.files)) return;
    const delivered = new Set(images.map((img) => {
      const data = String(img?.data || '');
      return `${data.length}:${sampledHash(data)}`;
    }));
    const files = stored.files.filter((file) => {
      const data = String(file?.data || '');
      return !delivered.has(`${data.length}:${sampledHash(data)}`);
    });
    if (files.length === stored.files.length) return;
    if (files.length) await browser.storage.local.set({ [key]: { ...stored, files, updated_at: Date.now() } });
    else await browser.storage.local.remove(key);
  } catch { /* Content script cleanup is still attempted through notifyAck. */ }
}

async function notifyAck(item, result) {
  try {
    const tabs = await browser.tabs.query({});
    const evidenceReady = result?.handoff?.evidence_ready !== false && result?.evidence_ready !== false;
    const missingEvidenceIds = result?.handoff?.missing_evidence_ids || result?.missing_evidence_ids || [];
    await Promise.allSettled((tabs || []).filter((t) => t.id).map((t) => browser.tabs.sendMessage?.(t.id, {
      type: 'bridge:handoff-acked', ticket_id: item.payload.ticket_id, handoff_id: result?.handoff?.id || null,
      evidence_ready: evidenceReady, missing_evidence_ids: missingEvidenceIds,
    })));
  } catch {}
}

async function deliverOutboxItem(item, bridgeToken) {
  return localFetch(item.payload.operation==='create_proactive'?'/api/bridge/proactive':'/api/bridge/handoff', { method: 'POST', body: JSON.stringify(item.payload) }, { token: bridgeToken, timeoutMs: 30000 });
}

function retryableError(error) {
  if (!error?.status) return true;
  return error.status === 408 || error.status === 429 || error.status >= 500;
}

async function _flushOutbox() {
  let state = await readState();
  if (!state.bridgeToken || !state.outbox.length) return { ok: true, sent: 0, pending: state.outbox.length };
  let sent = 0;
  for (const original of [...state.outbox]) {
    state = await readState();
    const current = state.outbox.find((x) => x.key === original.key);
    if (!current) continue;
    try {
      await setToolbarState('sending');
      const result = await deliverOutboxItem(current, state.bridgeToken);
      const latest = await readState();
      await writeOutbox(latest.outbox.filter((x) => x.key !== current.key));
      sent += 1;
      const evidencePending = result?.handoff?.evidence_ready === false || result?.evidence_ready === false;
      // ACK of the text is not ACK of the complete evidence set. Preserve every
      // captured print until the Assistant confirms all E-IDs are persisted.
      if (!evidencePending) await cleanupCapturedEvidence(current);
      await writeLastSend({ ok: true, acknowledged: true, ticket_id: current.payload.ticket_id, provider: current.provider, task_count: current.task_count || result?.handoff?.task_count || 0, duplicate: !!result?.duplicate, handoff_id: result?.handoff?.id || null, evidence_pending: evidencePending, missing_evidence_ids: result?.handoff?.missing_evidence_ids || result?.missing_evidence_ids || [] });
      await notifyAck(current, result);
    } catch (error) {
      const latest = await readState();
      if (!retryableError(error)) {
        await writeOutbox(latest.outbox.filter((x) => x.key !== current.key));
        await writeLastSend({ ok: false, rejected: true, ticket_id: current.payload.ticket_id, provider: current.provider, task_count: current.task_count, error: error.message });
        throw error;
      }
      const next = latest.outbox.map((x) => x.key === current.key ? { ...x, attempts: Number(x.attempts || 0) + 1, last_error: error.message, last_attempt_at: Date.now() } : x);
      await writeOutbox(next);
      await writeLastSend({ ok: false, queued: true, ticket_id: current.payload.ticket_id, provider: current.provider, task_count: current.task_count, error: error.message });
      await setToolbarState('queued');
      return { ok: false, sent, pending: next.length, error: error.message };
    }
  }
  const after = await readState();
  await setToolbarState(after.outbox.length ? 'queued' : 'connected');
  return { ok: true, sent, pending: after.outbox.length };
}

async function flushOutbox() {
  if (!flushPromise) flushPromise = _flushOutbox().finally(() => { flushPromise = null; });
  return flushPromise;
}

async function sendHandoff(payload, { manual = false } = {}) {
  const { bridgeToken, settings } = await readState();
  if (!bridgeToken) throw new Error('Browser Bridge não pareado. Abra o popup da extensão e informe o código exibido no Assistant.');
  if (!manual && !settings.autoSend) return { ok: true, skipped: true, reason: 'auto-disabled' };
  const { ticketId } = validatePayload(payload);
  const item = await enqueueHandoff(payload, manual);
  const flush = await flushOutbox();
  const after = await readState();
  const stillQueued = after.outbox.some((x) => x.key === item.key);
  let tab = null; let tabError = null;
  try { tab = await ensureAssistantTab(settings); } catch (error) { tabError = error?.message || String(error); }
  if (stillQueued) {
    await setToolbarState('queued');
    return { ok: true, queued: true, acknowledged: false, ticket_id: ticketId, outbox_count: after.outbox.length, error: flush?.error || null, tab, tab_error: tabError };
  }
  const lastSend = (await readState()).lastSend;
  return { ok: true, queued: false, acknowledged: true, duplicate: !!lastSend?.duplicate, handoff: { id: lastSend?.handoff_id || null }, ticket_id: ticketId, outbox_count: after.outbox.length, tab, tab_error: tabError, lastSend };
}

async function getStatus() {
  const state = await readState();
  const [assistant, pingResult] = await Promise.all([assistantInfo(), state.bridgeToken ? ping(state.bridgeToken) : Promise.resolve({ ok: false, paired: false })]);
  return { extensionVersion: EXTENSION_VERSION, bridgeGeneration: '2.4.1', paired: state.bridgeToken ? !pingResult.invalidToken : false, settings: state.settings, assistant, ping: pingResult, lastSend: state.lastSend, lastDetected: state.lastDetected, outbox: { count: state.outbox.length, items: state.outbox.map((x) => ({ key: x.key, ticket_id: x.payload.ticket_id, attempts: x.attempts || 0, last_error: x.last_error, created_at: x.created_at })) }, captures: { count: state.captureOutbox.length } };
}

browser.runtime.onMessage.addListener((message, sender) => {
  const type = message?.type;
  if (sender.id !== browser.runtime.id) return Promise.reject(new Error('Origem inválida'));
  if (type === 'bridge:capture-glpi') return captureGlpi();
  if (type === 'bridge:status') return getStatus();
  if (type === 'bridge:pair') return pair(message.code);
  if (type === 'bridge:disconnect') return disconnect();
  if (type === 'bridge:settings:get') return readState().then((x) => x.settings);
  if (type === 'bridge:settings:set') return writeSettings(message.settings || {});
  if (type === 'bridge:open-whatsapp') return openExistingWhatsapp(message.url, sender);
  if (type === 'bridge:contract-detected') return noteDetectedContract(message.packet || {});
  if (type === 'bridge:handoff') return sendHandoff(message.payload, { manual: !!message.manual });
  if (type === 'bridge:capture:enqueue') return enqueueCapture(message.snapshot || {}).then((item) => flushCaptureOutbox().then((result) => ({ item, result })));
  if (type === 'bridge:capture:flush') return flushCaptureOutbox();
  if (type === 'bridge:outbox:flush') return flushOutbox();
  if (type === 'bridge:evidence:cleanup') return cleanupExpiredEvidence({ force: !!message.force });
  if (type === 'bridge:open-assistant') return readState().then(({ settings }) => ensureAssistantTab({ ...settings, openIfClosed: true, focusOnSend: true }));
  return undefined;
});

async function openExistingWhatsapp(rawUrl, sender) {
  const result = whatsappNavigationQueue.then(() => navigateWhatsapp(rawUrl, sender));
  whatsappNavigationQueue = result.catch(() => {});
  return result;
}
let whatsappNavigationQueue = Promise.resolve();
async function navigateWhatsapp(rawUrl, sender) {
  if (!/^http:\/\/127\.0\.0\.1:8765\//.test(sender.tab?.url || '')) throw Error('Origem local inválida.');
  const target = new URL(rawUrl);
  if (target.origin !== 'https://web.whatsapp.com' || target.pathname !== '/send' ||
      !/^55\d{10,11}$/.test(target.searchParams.get('phone') || '') ||
      (target.searchParams.get('text') || '').length > 2000 ||
      [...target.searchParams.keys()].some(key => !['phone','text'].includes(key))) throw Error('Conversa inválida.');
  const openTabs = await browser.tabs.query({url:'https://web.whatsapp.com/*'});
  const sameContainer = openTabs.filter(tab => !!tab.incognito === !!sender.tab.incognito && (!sender.tab.cookieStoreId || tab.cookieStoreId === sender.tab.cookieStoreId));
  const existing = sameContainer.find(tab => tab.windowId === sender.tab.windowId) || sameContainer[0];
  if (existing) {
    await browser.tabs.update(existing.id, {url:target.href,active:true});
    if (existing.windowId !== sender.tab.windowId) await browser.windows.update(existing.windowId,{focused:true});
    return {ok:true,reused:true};
  }
  await browser.tabs.create({url:target.href,active:true,windowId:sender.tab.windowId,...(sender.tab.cookieStoreId ? {cookieStoreId:sender.tab.cookieStoreId} : {})});
  return {ok:true,reused:false};
}

async function captureGlpi() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/^https?:\/\//.test(tab.url || '')) throw Error('Abra um chamado no GLPI.');
  const { bridgeToken } = await readState();
  const config = await localFetch('/api/bridge/glpi-origin', {}, { token: bridgeToken });
  const current = new URL(tab.url); const base = new URL(config.url);
  if (current.origin !== base.origin || !/\/front\/ticket\.form\.php$/.test(current.pathname) || !/^\d+$/.test(current.searchParams.get('id') || '')) throw Error('Abra um chamado no servidor GLPI configurado.');
  const results = await browser.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ ticket_id: Number(new URL(location.href).searchParams.get('id')), url: location.href, title: document.title.slice(0, 500), text: (document.querySelector('main')?.innerText || document.querySelector('.page-body')?.innerText || '').slice(0, 16000) }) });
  return localFetch('/api/bridge/context', { method: 'POST', body: JSON.stringify(results[0].result) }, { token: bridgeToken, timeoutMs: 60000 });
}

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  void injectGenericBridge(tabId, tab?.url || changeInfo.url || '');
});

function ensureAlarms() {
  browser.alarms.create('bridge-ping', { periodInMinutes: 1 });
  browser.alarms.create('bridge-outbox', { periodInMinutes: 1 });
  browser.alarms.create('bridge-evidence-cleanup', { periodInMinutes: 60 });
}

browser.runtime.onInstalled.addListener(async () => {
  const state = await readState();
  await browser.storage.local.set({ settings: state.settings, [OUTBOX_KEY]: state.outbox });
  ensureAlarms(); await ping(state.bridgeToken); void restoreGenericBridges(); void flushOutbox(); void flushCaptureOutbox(); void cleanupExpiredEvidence();
});
browser.runtime.onStartup.addListener(async () => { ensureAlarms(); const { bridgeToken } = await readState(); await ping(bridgeToken); void restoreGenericBridges(); void flushOutbox(); void flushCaptureOutbox(); void cleanupExpiredEvidence(); });
browser.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'bridge-ping') { const { bridgeToken } = await readState(); await ping(bridgeToken); }
  if (alarm.name === 'bridge-outbox') { void flushOutbox(); void flushCaptureOutbox(); }
  if (alarm.name === 'bridge-evidence-cleanup') void cleanupExpiredEvidence();
});

readState().then(({ bridgeToken, outbox }) => setToolbarState(outbox.length ? 'queued' : bridgeToken ? 'offline' : 'unpaired'));
