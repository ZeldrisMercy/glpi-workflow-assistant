'use strict';

// GLPI Assistant Bridge 2.4.0
// The structured GLPI_ASSISTANT contract is the source of truth. Provider
// adapters only improve discovery/generation detection; they are not required
// for parsing or manual handoff.
(() => {
  if (globalThis.__glpiBridgeContent221) return;
  globalThis.__glpiBridgeContent221 = true;

  const PROVIDERS = Object.freeze({
    chatgpt: {
      id: 'chatgpt', label: 'ChatGPT',
      matches: () => location.hostname === 'chatgpt.com',
      selectors: ['[data-message-author-role="assistant"]'],
      contentSelectors: [],
      generationSelectors: [
        'button[data-testid="stop-button"]',
        'button[aria-label*="stop generating" i]',
        'button[aria-label*="parar" i]',
      ],
    },
    gemini: {
      id: 'gemini', label: 'Gemini',
      matches: () => location.hostname === 'gemini.google.com',
      selectors: ['model-response', '[data-test-id="model-response"]', '.model-response'],
      contentSelectors: ['message-content.model-response-text', '.model-response-text', 'message-content', '.response-content'],
      generationSelectors: [
        'button[aria-label*="stop response" i]',
        'button[aria-label*="stop" i]',
        'button[aria-label*="parar" i]',
        '[data-test-id*="stop" i]',
      ],
    },
  });

  const matchedProvider = Object.values(PROVIDERS).find((item) => item.matches()) || null;
  const provider = matchedProvider || {
    id: 'generic',
    label: location.hostname.replace(/^www\./, '') || 'IA web',
    selectors: [], contentSelectors: [], generationSelectors: [],
  };

  const detectedKeys = new Set();
  const sentKeys = new Set();
  const sendingKeys = new Set();
  const nodeState = new WeakMap();
  const debounceTimers = new WeakMap();
  const genericNodes = new Set();
  let lastGenericFullScan = 0;
  let scanTimer = null;
  let watchdogTimer = null;
  let lastMutationAt = Date.now();
  let lastEvidenceRecovery = { at: 0, ticket_id: 0, required: 0, recovered: 0, source: 'none' };

  const COMPLETE_PACKET_GRACE_MS = 600;
  const GENERATION_END_GRACE_MS = 900;
  const FALLBACK_STABLE_MS = 3000;
  const GENERATING_RECHECK_MS = 500;
  const DOM_SCAN_THROTTLE_MS = 180;
  const WATCHDOG_MS = 2500;
  const MAX_GENERIC_CANDIDATES = 12;

  function normalizeText(value) {
    let text = String(value || '')
      .replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      .replace(/[\u200B-\u200D\uFEFF]/g, '');
    // Some SPA renderers expose a fenced/code response with escaped newlines
    // literally ("\\n"). Repair only when the GLPI contract itself is escaped.
    if (/\[GLPI_ASSISTANT\s*:\s*\d+\s*\]\s*\\(?:r\\n|n|r)/i.test(text) || /\[TAREFA:T\d+\]\s*\\(?:r\\n|n|r)/i.test(text)) {
      text = text.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n').replace(/\\r/g, '\n');
    }
    return text;
  }

  function messageText(node) {
    if (!node) return '';
    if (matchedProvider?.contentSelectors?.length) {
      for (const selector of matchedProvider.contentSelectors) {
        const content = node.querySelector?.(selector);
        if (content) return normalizeText(content.innerText || content.textContent || '');
      }
    }
    return normalizeText(node.innerText || node.textContent || '');
  }

  function isVisible(element) {
    if (!(element instanceof Element)) return false;
    const style = getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function providerIsGenerating() {
    if (!matchedProvider) return false;
    for (const selector of matchedProvider.generationSelectors || []) {
      for (const element of document.querySelectorAll(selector)) if (isVisible(element)) return true;
    }
    return false;
  }

  function parseSinglePacket(source, marker, endIndex) {
    const ticketId = Number(marker[1]);
    if (!Number.isSafeInteger(ticketId) || ticketId <= 0) return null;
    const region = source.slice(marker.index + marker[0].length, endIndex);
    const taskRe = /\[TAREFA:(T\d+)\][\s\S]*?\[\/TAREFA\]/gi;
    const tasks = [];
    let match;
    while ((match = taskRe.exec(region)) !== null) {
      const id = String(match[1] || '').toUpperCase();
      if (!/^T(?:0[1-9]|[1-9][0-9]{1,2})$/.test(id)) return null;
      tasks.push({ id, block: match[0].trim() });
      if (tasks.length > 999) return null;
    }
    if (!tasks.length) return null;
    const ids = tasks.map((x) => x.id);
    if (new Set(ids).size !== ids.length) return null;
    const order = ids.map((id) => Number(id.slice(1)));
    if (order.some((value, index) => index > 0 && value < order[index - 1])) return null;

    // If a task opener/closer is still streaming, the packet is incomplete.
    const opens = region.match(/\[TAREFA:T\d+\]/gi) || [];
    const closes = region.match(/\[\/TAREFA\]/gi) || [];
    if (opens.length !== closes.length || opens.length !== tasks.length) return null;

    const intentOpen = /\[DESTINO_CHAMADO\]/i.test(region);
    const intentBlocks = [...region.matchAll(/^\s*\[DESTINO_CHAMADO\]\s*\n[\s\S]*?^\s*\[\/DESTINO_CHAMADO\]\s*$/gmi)];
    if (intentOpen && intentBlocks.length !== 1) return null;
    if (intentBlocks.length && intentBlocks[0].index < region.lastIndexOf('[/TAREFA]')) return null;

    const changesOpen = /\[ALTERACOES_CHAMADO\]/i.test(region);
    const changesMatch = /\[ALTERACOES_CHAMADO\][\s\S]*?\[\/ALTERACOES_CHAMADO\]/i.exec(region);
    if (changesOpen && !changesMatch) return null;

    let closure = `[GLPI_ASSISTANT:${ticketId}]\n\n${tasks.map((task) => task.block).join('\n\n')}`;
    if (changesMatch) closure += `\n\n${changesMatch[0].trim()}`;
    if (intentBlocks.length) closure += `\n\n${intentBlocks[0][0].trim()}`;
    return {
      provider: provider.id,
      provider_label: provider.label,
      ticket_id: ticketId,
      closure,
      task_count: tasks.length,
      task_ids: ids,
      has_changes: !!changesMatch,
      key: `${provider.id}\n${ticketId}\n${closure}`,
    };
  }

  function extractBridgePackets(text) {
    const source = normalizeText(text);
    const markers = [...source.matchAll(/\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]/gi)];
    const proactive = [];
    for (const match of source.matchAll(/\[GLPI_PROACTIVE\]([\s\S]*?)\[\/GLPI_PROACTIVE\]/g)) {
      try {
        const value=JSON.parse(match[1]);
        for (const raw of (Array.isArray(value)?value:[value])) {
          if(raw.operation!=='create_proactive'||raw.schema_version!==1||!/^[A-Za-z0-9_-]{1,64}$/.test(raw.draft_ref))return [];
          const closure='[GLPI_PROACTIVE]'+JSON.stringify(raw)+'[/GLPI_PROACTIVE]';
          proactive.push({operation:'create_proactive',draft_ref:raw.draft_ref,raw,provider:provider.id,provider_label:provider.label,ticket_id:0,closure,task_count:(raw.tasks||[]).length,task_ids:(raw.tasks||[]).map(t=>t.id),key:provider.id+'\nproactive\n'+closure});
        }
      }catch{return [];}
    }
    if(proactive.length){if(new Set(proactive.map(p=>p.draft_ref)).size!==proactive.length)return [];return proactive;}
    if (!markers.length) return [];
    const packets = [];
    for (let index = 0; index < markers.length; index += 1) {
      const marker = markers[index];
      const end = index + 1 < markers.length ? markers[index + 1].index : source.length;
      const packet = parseSinglePacket(source, marker, end);
      if (packet) packets.push(packet);
    }
    const ids = packets.map((p) => p.ticket_id);
    if (new Set(ids).size !== ids.length) return [];
    return packets;
  }

  // Isolated-world diagnostic hook used by the local QA harness. It is not
  // exposed to page JavaScript by Firefox content-script isolation.
  globalThis.__glpiBridgeTest = Object.freeze({ extractBridgePackets });

  function nearestContractContainer(start) {
    let node = start instanceof Element ? start : start?.parentElement;
    let best = null;
    for (let depth = 0; node && depth < 9; depth += 1, node = node.parentElement) {
      const text = messageText(node);
      if (!text.includes('[GLPI_ASSISTANT')) continue;
      if (text.length > 160000) break;
      best = node;
      const markers = text.match(/\[GLPI_ASSISTANT\s*:/gi) || [];
      const tasks = text.match(/\[TAREFA:/gi) || [];
      if (markers.length >= 1 && tasks.length >= 1 && text.length < 50000) return node;
    }
    return best;
  }

  function genericContractNodes({ force = false } = {}) {
    for (const node of [...genericNodes]) if (!node?.isConnected) genericNodes.delete(node);
    const cached = [...genericNodes];
    // Generic providers are opt-in. Avoid walking a large conversation DOM on
    // every watchdog tick: mutations register new containers directly, while a
    // bounded full scan is only a fallback for already-rendered/virtualized UI.
    if (!force && (cached.length || Date.now() - lastGenericFullScan < 10000)) return cached;
    lastGenericFullScan = Date.now();
    const seen = new Set(cached);
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return node.nodeValue?.includes('[GLPI_ASSISTANT') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    let textNode;
    while ((textNode = walker.nextNode()) && seen.size < MAX_GENERIC_CANDIDATES) {
      const container = nearestContractContainer(textNode);
      if (container && !seen.has(container)) { seen.add(container); genericNodes.add(container); }
    }
    return [...genericNodes].filter((node) => node.isConnected);
  }

  function allProviderNodes({ forceContractScan = false } = {}) {
    const seen = new Set();
    const nodes = [];
    if (matchedProvider) {
      for (const selector of matchedProvider.selectors) {
        for (const node of document.querySelectorAll(selector)) {
          const canonical = provider.id === 'gemini' ? (node.closest('model-response') || node) : node;
          if (!seen.has(canonical)) { seen.add(canonical); nodes.push(canonical); }
        }
      }
    }
    // Contract discovery is provider-independent. This bounded fallback keeps
    // working when ChatGPT/Gemini changes its message wrappers.
    for (const node of genericContractNodes({ force: forceContractScan || !nodes.length })) {
      if (!seen.has(node)) { seen.add(node); nodes.push(node); }
    }
    return nodes;
  }

  function findProviderNode(node) {
    const element = node instanceof Element ? node : node?.parentElement;
    if (!element) return null;
    if (!matchedProvider) {
      const candidate = nearestContractContainer(element);
      if (candidate) genericNodes.add(candidate);
      return candidate;
    }
    for (const selector of matchedProvider.selectors) {
      const candidate = element.matches?.(selector) ? element : element.closest?.(selector);
      if (candidate) return provider.id === 'gemini' ? (candidate.closest('model-response') || candidate) : candidate;
    }
    const contract = nearestContractContainer(element);
    if (contract) genericNodes.add(contract);
    return contract;
  }

  function fastHash(value) {
    const text = String(value || ''); let hash = 2166136261;
    const step = Math.max(1, Math.floor(text.length / 4096));
    for (let i = 0; i < text.length; i += step) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    hash ^= text.length; hash = Math.imul(hash, 16777619);
    return (hash >>> 0).toString(36);
  }

  function packetFingerprint(packet) { return `${packet.ticket_id}:${fastHash(packet.closure)}`; }

  function announceDetected(packet) {
    const fingerprint = packetFingerprint(packet);
    if (detectedKeys.has(fingerprint)) return;
    detectedKeys.add(fingerprint);
    void browser.runtime.sendMessage({ type: 'bridge:contract-detected', packet: {
      fingerprint, provider: packet.provider, ticket_id: packet.ticket_id, task_count: packet.task_count, task_ids: packet.task_ids,
    } }).catch(() => {});
  }

  function ensureToastHost() {
    let host = document.getElementById('glpi-assistant-bridge-toast-host');
    if (host) return host.shadowRoot;
    host = document.createElement('div');
    host.id = 'glpi-assistant-bridge-toast-host';
    host.style.cssText = 'position:fixed;right:18px;top:18px;z-index:2147483647;pointer-events:none';
    document.documentElement.appendChild(host);
    const root = host.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>
      .toast{pointer-events:none;min-width:220px;max-width:min(270px,80vw);padding:9px 12px;border-radius:13px;border:1px solid rgba(79,229,255,.34);background:linear-gradient(145deg,rgba(3,6,13,.99),rgba(8,20,38,.99) 62%,rgba(32,18,65,.98));box-shadow:0 18px 54px rgba(0,0,0,.46),0 0 34px rgba(47,180,255,.18);color:#f2fbff;font:600 13px/1.45 "Segoe UI",Inter,system-ui,sans-serif;opacity:0;transform:translateY(8px);transition:.18s ease}
      .toast.show{opacity:1;transform:translateY(0)}.row{display:flex;gap:10px;align-items:center}.mark{font-size:18px;color:#effdff;text-shadow:0 0 20px #43dfff}.title{font-weight:850}.sub{margin-top:2px;color:#b6c9df;font-size:12px}.ok{color:#80f1ca}.bad{color:#ff97b2}.warn{color:#ffd18f}
    </style><div id="toast" class="toast"><div class="row"><div class="mark">∞</div><div><div id="title" class="title"></div><div id="sub" class="sub"></div></div></div></div>`;
    return root;
  }

  let toastTimer = null;
  const toastSeen = new Map();
  const sentImageStates = new Map();
  let lastToastKey = '', lastToastAt = 0;
  function showToast(title, sub = '', kind = 'ok') {
    const key = `${title}|${sub}|${kind}`;
    if (Date.now() - (toastSeen.get(key) || 0) < 120000) return;
    toastSeen.set(key,Date.now());if(toastSeen.size>100)toastSeen.delete(toastSeen.keys().next().value);
    lastToastKey = key; lastToastAt = Date.now();
    const root = ensureToastHost();
    const toast = root.getElementById('toast');
    const titleEl = root.getElementById('title');
    titleEl.textContent = title;
    titleEl.className = `title ${kind}`;
    root.getElementById('sub').textContent = sub;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), kind === 'bad' ? 3000 : 1500);
  }

  function nearestPriorUserTurn(node) {
    const selectors = provider.id === 'chatgpt'
      ? '[data-message-author-role="user"]'
      : provider.id === 'gemini'
        ? 'user-query, [data-role="user"]'
        : '[data-message-author-role="user"], user-query, [data-role="user"]';
    const users = [...document.querySelectorAll(selectors)];
    return users.filter((u) => u !== node && (u.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)).pop() || null;
  }

  function bytesToBase64(bytes) {
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    return btoa(binary);
  }

  async function imageElementToPayload(img) {
    const src = String(img?.currentSrc || img?.src || '');
    if (!src) return null;
    try {
      if (src.startsWith('data:image/')) {
        const match = /^data:image\/(?:png|jpeg|webp);base64,(.+)$/i.exec(src);
        if (!match || match[1].length > 11 * 1024 * 1024) return null;
        return match[1];
      }
      if (/^(?:blob:|https?:)/i.test(src)) {
        const response = await fetch(src, { credentials: 'include', cache: 'no-store' });
        if (!response.ok) return null;
        const blob = await response.blob();
        if (!/^image\/(?:png|jpeg|webp)$/i.test(blob.type || '') || blob.size > 8 * 1024 * 1024) return null;
        const bytes = new Uint8Array(await blob.arrayBuffer());
        return bytesToBase64(bytes);
      }
    } catch { /* fall through to canvas */ }
    try {
      if (!img.complete || img.naturalWidth < 100 || img.naturalHeight < 70 || img.naturalWidth * img.naturalHeight > 16000000) return null;
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
      canvas.getContext('2d', { alpha: false }).drawImage(img, 0, 0);
      const value = canvas.toDataURL('image/png').split(',')[1] || '';
      return value.length <= 11 * 1024 * 1024 ? value : null;
    } catch { return null; }
  }

  function userTurnImageCandidates(node) {
    const user = nearestPriorUserTurn(node);
    if (!user) return [];
    const seen = new Set();
    const candidates = [];
    for (const img of user.querySelectorAll('img')) {
      const src = String(img.currentSrc || img.src || '');
      if (!src || seen.has(src)) continue;
      const rect = img.getBoundingClientRect?.() || { width: 0, height: 0 };
      const width = Math.max(Number(img.naturalWidth || 0), Number(rect.width || 0));
      const height = Math.max(Number(img.naturalHeight || 0), Number(rect.height || 0));
      // Ignore avatars/icons while keeping screenshot thumbnails rendered small by the composer.
      if (width < 72 || height < 52) continue;
      seen.add(src); candidates.push(img);
    }
    return candidates.slice(0, 12);
  }

  async function recoverUserTurnEvidence(node, packet, required, suppliedIds = []) {
    const supplied = new Set(suppliedIds.map((x) => String(x).toUpperCase()));
    const candidates = userTurnImageCandidates(node);
    if (!candidates.length) {
      lastEvidenceRecovery = { at: Date.now(), ticket_id: packet.ticket_id, required: required.length, recovered: 0, source: 'no-user-images' };
      return [];
    }

    // Explicit E01/E02 filenames are always safe regardless of count.
    const explicit = [];
    for (const img of candidates) {
      const id = /\b(E\d{2,3})(?:\.(?:png|jpe?g|webp)|\b)/i.exec(`${img.alt || ''} ${img.title || ''}`)?.[1]?.toUpperCase();
      if (!id || !required.includes(id) || supplied.has(id)) continue;
      const data = await imageElementToPayload(img);
      if (data) { explicit.push({ id, data }); supplied.add(id); }
    }
    if (explicit.length) { lastEvidenceRecovery = { at: Date.now(), ticket_id: packet.ticket_id, required: required.length, recovered: explicit.length, source: 'labeled-user-turn' }; return explicit; }

    lastEvidenceRecovery = { at: Date.now(), ticket_id: packet.ticket_id, required: required.length, recovered: 0, source: 'unclassified-context' };
    return [];
  }

  async function waitAndRecoverUserTurnEvidence(node, packet, required, suppliedIds = []) {
    // The first structured response can finish while ChatGPT is still replacing
    // upload thumbnails in the prior user turn. Give that DOM a short bounded
    // settle window instead of requiring the user to attach the same files twice.
    for (const delay of [0, 350, 900, 1700]) {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      const recovered = await recoverUserTurnEvidence(node, packet, required, suppliedIds);
      if (recovered.length) return recovered;
    }
    return [];
  }

  async function sendPacket(node, packet, { manual = false, packetCount = 1 } = {}) {
    if (!packet)return null;
    let proactiveCapture=null;
    if(packet.operation==='create_proactive'){
      proactiveCapture=await globalThis.glpiCapture?.proactiveFor(packet.raw,messageText(nearestPriorUserTurn(node)));
      if(!proactiveCapture?.prompt_timestamp&&!manual)return {skipped:true};
      packet={...packet,key:packet.key+'\n'+(proactiveCapture?.prompt_timestamp||'manual')};
    }
    if (sendingKeys.has(packet.key) || (sentKeys.has(packet.key) && !globalThis.glpiCapture?.hasPending())) return null;
    sendingKeys.add(packet.key);
    try {
      if(packet.operation==='create_proactive') {
        const capture=proactiveCapture;
        const result=await browser.runtime.sendMessage({type:'bridge:handoff',payload:{...packet,operation:'create_proactive',prompt_timestamp:capture?.prompt_timestamp||null,conversation_key:location.origin+location.pathname,images:capture?.images||[]},manual});
        if(!result?.skipped){sentKeys.add(packet.key);showToast('Proativo recebido',packet.draft_ref+' · revise o cadastro e as evidências na aplicação.', 'ok');}
        return result;
      }
      const captured = await globalThis.glpiCapture?.packetFor(packet.ticket_id, packet.closure, { multiTicket: Number(packetCount) > 1 });
      // Image capture can lag behind the completed text. Prefer original File
      // bytes, then labeled DOM evidence, then recover upload thumbnails from
      // the immediately preceding user turn. This last path is what makes the
      // first prompt reliable when ChatGPT clears/replaces its file input.
      let images = captured?.blocked ? [] : captured?.images?.length ? [...captured.images] : captured?.suppressRecovery ? [] : [...captureLabeledEvidence(node, packet)];
      const required = [...new Set([...packet.closure.matchAll(/\[EVID[ÊE]NCIA\s*:\s*(E\d{2,3})\s*\]/gi)].map((m) => m[1].toUpperCase()))]
        .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
      let supplied = [...new Set(images.map((item) => String(item?.id || '').toUpperCase()))]
        .filter(Boolean).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
      let missing = required.filter((id) => !supplied.includes(id));
      if (missing.length && !captured?.blocked && Number(packetCount) === 1) {
        const recovered = await waitAndRecoverUserTurnEvidence(node, packet, required, supplied);
        for (const item of recovered) if (!images.some((x) => String(x.id).toUpperCase() === item.id)) images.push(item);
        supplied = [...new Set(images.map((item) => String(item?.id || '').toUpperCase()))]
          .filter(Boolean).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
        missing = required.filter((id) => !supplied.includes(id));
      }
      const unexpected = supplied.filter((id) => !required.includes(id));
      if (unexpected.length) {
        showToast('Print sem marcador', `#${packet.ticket_id} · ${unexpected.join(', ')} não existe no fechamento. Revise no clips.`, 'warn');
        return null;
      }
      const imageState=JSON.stringify(images.map(x=>[x.id,x.data]).sort((a,b)=>a[0].localeCompare(b[0])));
      if(sentImageStates.get(packet.key)===imageState)return null;
      const result = await browser.runtime.sendMessage({
        type: 'bridge:handoff',
        payload: {
          provider: packet.provider, provider_label: packet.provider_label,
          ticket_id: packet.ticket_id, closure: packet.closure,
          task_count: packet.task_count, task_ids: packet.task_ids, images,
        },
        manual,
      });
      if (result?.skipped) {
        showToast('Fechamento detectado', 'Envio automático desativado. O pacote ficou disponível para envio manual.', 'warn');
        return result;
      }
      // queued=true means the persistent outbox owns the packet even if the Assistant is offline.
      sentKeys.add(packet.key);
      sentImageStates.set(packet.key,imageState);
      const evidencePending = !!result?.lastSend?.evidence_pending || (!!missing.length && result?.acknowledged);
      if (result?.acknowledged && !evidencePending) await globalThis.glpiCapture?.delivered(packet.ticket_id);
      const queued = !!result?.queued && !result?.acknowledged;
      const partial = evidencePending;
      showToast(
        queued ? `#${packet.ticket_id} · na fila` : partial ? `#${packet.ticket_id} · prints pendentes` : `✓ #${packet.ticket_id} recebido`,
        queued ? 'Aguardando a aplicação.' : partial ? `Faltam ${missing.join(', ')}.` : '',
        queued || partial ? 'warn' : 'ok',
      );
      return result;
    } catch (error) {
      showToast('Falha no Browser Bridge', error?.message || String(error), 'bad');
      return null;
    } finally {
      sendingKeys.delete(packet.key);
    }
  }

  async function sendPackets(node, packets, options = {}) {
    await globalThis.glpiCapture?.routePackets?.(packets);
    const packetCount = packets.length;
    for (const packet of packets) await sendPacket(node, packet, { ...options, packetCount });
  }

  function scheduleProviderNode(node, { allowInitial = false, manual = false } = {}) {
    const assistant = findProviderNode(node) || (node instanceof Element ? node : null);
    if (!assistant) return;
    const generating = providerIsGenerating();
    const state = nodeState.get(assistant) || { sawGenerating: false };
    if (generating) state.sawGenerating = true;
    nodeState.set(assistant, state);

    const packets = extractBridgePackets(messageText(assistant));
    packets.forEach(announceDetected);
    const pendingPackets = packets.filter((packet) => !sentKeys.has(packet.key) || globalThis.glpiCapture?.hasPending());
    const combinedKey = pendingPackets.map((p) => p.key).join('\n---\n');
    if (!pendingPackets.length) return;
    if (!manual && state.scheduledKey === combinedKey && debounceTimers.has(assistant)) return;
    clearTimeout(debounceTimers.get(assistant));
    debounceTimers.delete(assistant);
    state.scheduledKey = combinedKey;

    if (manual) { void sendPackets(assistant, pendingPackets, { manual: true }); return; }
    if (generating) {
      debounceTimers.set(assistant, setTimeout(() => { debounceTimers.delete(assistant); scheduleProviderNode(assistant, { allowInitial, manual }); }, GENERATING_RECHECK_MS));
      return;
    }
    const delay = pendingPackets.every((p) => p.has_changes)
      ? COMPLETE_PACKET_GRACE_MS
      : state.sawGenerating ? GENERATION_END_GRACE_MS : FALLBACK_STABLE_MS;
    debounceTimers.set(assistant, setTimeout(() => {
      debounceTimers.delete(assistant);
      const latestPackets = extractBridgePackets(messageText(assistant));
      latestPackets.forEach(announceDetected);
      const latestKey = latestPackets.filter((p) => !sentKeys.has(p.key) || globalThis.glpiCapture?.hasPending()).map((p) => p.key).join('\n---\n');
      if (!latestPackets.length) return;
      if (latestKey !== combinedKey) { scheduleProviderNode(assistant, { allowInitial, manual }); return; }
      if (providerIsGenerating() && !latestPackets.every((p) => p.has_changes)) { scheduleProviderNode(assistant, { allowInitial, manual }); return; }
      void sendPackets(assistant, latestPackets, { manual });
    }, delay));
  }

  function scanLatestResponses({ allowInitial = false, forceContractScan = false } = {}) {
    scanTimer = null;
    const nodes = allProviderNodes({ forceContractScan });
    for (const node of nodes.slice(-4)) scheduleProviderNode(node, { allowInitial });
  }
  function recoverLatestContract({ manual = false } = {}) {
    const nodes = allProviderNodes({ forceContractScan: true }).slice().reverse();
    for (const node of nodes) {
      const packets = extractBridgePackets(messageText(node));
      if (!packets.length) continue;
      packets.forEach(announceDetected);
      if (manual) void sendPackets(node, packets, { manual: true });
      else scheduleProviderNode(node, { allowInitial: true });
      return packets.length;
    }
    return 0;
  }

  function scheduleLatestScan() {
    if (scanTimer) return;
    scanTimer = setTimeout(() => scanLatestResponses(), DOM_SCAN_THROTTLE_MS);
  }

  function repairCapture() {
    try { globalThis.glpiCapture?.repair?.(); } catch {}
    if (!matchedProvider) genericContractNodes({ force: true });
    recoverLatestContract({ manual: false });
    return {
      ok: true,
      provider: provider.id,
      provider_label: provider.label,
      response_nodes: allProviderNodes().length,
      evidence: globalThis.glpiCapture?.stats?.() || { count: 0 },
    };
  }

  const observer = new MutationObserver((mutations) => {
    lastMutationAt = Date.now();
    for (const mutation of mutations) {
      const direct = findProviderNode(mutation.target);
      if (direct) scheduleProviderNode(direct);
    }
    scheduleLatestScan();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  // document_idle may run after pageshow. Recover the latest completed packet once.
  setTimeout(() => { if (!document.hidden) recoverLatestContract({ manual: false }); }, 900);

  watchdogTimer = setInterval(() => {
    // SPA frameworks replace subtrees/content scripts can miss synthetic file changes.
    // A cheap contract scan repairs discovery without requiring a page refresh.
    try { globalThis.glpiCapture?.repair?.(); } catch {}
    if (!document.hidden) {
      if (Date.now() - lastGenericFullScan >= 10000) genericContractNodes({ force: true });
      scheduleLatestScan();
      if (Date.now() - lastMutationAt > WATCHDOG_MS * 2) recoverLatestContract({ manual: false });
    }
  }, WATCHDOG_MS);

  window.addEventListener('pageshow', () => repairCapture());
  window.addEventListener('focus', () => repairCapture());
  window.addEventListener('popstate', () => setTimeout(() => repairCapture(), 250));
  window.addEventListener('hashchange', () => setTimeout(() => repairCapture(), 250));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) repairCapture(); });

  browser.runtime.onMessage.addListener((message) => {
    if (message?.type === 'bridge:evidence-cleaned') {
      return Promise.resolve(globalThis.glpiCapture?.syncFromStorage?.() || { ok: true });
    }
    if (message?.type === 'bridge:handoff-acked') {
      const ticketId = Number(message.ticket_id || 0);
      if (ticketId > 0) {
        if (message.evidence_ready !== false) {
          void globalThis.glpiCapture?.delivered?.(ticketId);
          showToast('Entrega confirmada', `Chamado #${ticketId} recebeu texto e evidências no GLPI Assistant.`, 'ok');
        } else {
          const missing = (message.missing_evidence_ids || []).join(', ') || 'prints';
          showToast('Texto confirmado · prints preservados', `#${ticketId} · aguardando ${missing}. Os arquivos locais não serão apagados.`, 'warn');
        }
      }
      return Promise.resolve({ ok: true });
    }
    if (message?.type === 'bridge:extract-all' || message?.type === 'bridge:extract-last') {
      const nodes = allProviderNodes().slice().reverse();
      for (const node of nodes) {
        const packets = extractBridgePackets(messageText(node));
        if (!packets.length) continue;
        const clean = packets.map(({ key, ...packet }) => packet);
        if (message.type === 'bridge:extract-last') return Promise.resolve(clean[clean.length - 1] || null);
        return Promise.resolve(clean);
      }
      return Promise.resolve(message.type === 'bridge:extract-all' ? [] : null);
    }
    if (message?.type === 'bridge:repair') return Promise.resolve(repairCapture());
    if (message?.type === 'bridge:health') {
      const nodes = allProviderNodes();
      let latest = [];
      for (const node of nodes.slice().reverse()) {
        latest = extractBridgePackets(messageText(node));
        if (latest.length) break;
      }
      return Promise.resolve({
        supported: true,
        generic: !matchedProvider,
        provider: provider.id,
        provider_label: provider.label,
        capture_active: true,
        response_nodes: nodes.length,
        generating: providerIsGenerating(),
        latest: latest.length ? {
          ticket_id: latest[latest.length - 1].ticket_id,
          task_count: latest[latest.length - 1].task_count,
          task_ids: latest[latest.length - 1].task_ids,
          has_changes: latest[latest.length - 1].has_changes,
          packet_count: latest.length,
          ticket_ids: latest.map((p) => p.ticket_id),
        } : null,
        evidence: globalThis.glpiCapture?.stats?.() || { count: 0 },
        evidence_recovery: lastEvidenceRecovery,
        last_mutation_ms: Date.now() - lastMutationAt,
        bridge_generation: '2.4.0',
      });
    }
    return undefined;
  });

  function captureLabeledEvidence(node, packet) {
    // Provider-independent fallback: only accept images explicitly named E01…
    // from nearby user content. Protected/cross-origin images fail closed.
    const users = [...document.querySelectorAll('[data-message-author-role="user"], user-query, [data-role="user"], article')];
    const prior = users.filter((u) => u !== node && (u.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)).pop();
    if (!prior) return [];
    const found = []; const seen = new Set(); let bytes = 0;
    for (const img of prior.querySelectorAll('img')) {
      const id = /\b(E\d{2,3})\.(?:png|jpe?g|webp)\b/i.exec(img.alt || img.title || '')?.[1]?.toUpperCase();
      if (!id || seen.has(id) || !packet.closure.includes(id) || !img.complete || img.naturalWidth < 100) continue;
      try {
        if (img.naturalWidth * img.naturalHeight > 16000000) continue;
        const canvas = document.createElement('canvas'); canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
        canvas.getContext('2d').drawImage(img, 0, 0);
        const data = canvas.toDataURL('image/png').split(',')[1];
        if (data.length > 10 * 1024 * 1024 || bytes + data.length > 26 * 1024 * 1024) continue;
        bytes += data.length; seen.add(id); found.push({ id, data });
      } catch { /* Manual clips remains the safe fallback. */ }
    }
    return found.sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
  }

  globalThis.glpiCapture?.onReady(async (id) => {
    if (providerIsGenerating()) return;
    for (const node of allProviderNodes().reverse()) {
      const packets = extractBridgePackets(messageText(node));
      const matches = Number(id) > 0 ? packets.filter((p) => p.ticket_id === Number(id)) : packets;
      if (matches.length) { await sendPackets(node, matches, { manual: true }); return; }
    }
  });
})();
