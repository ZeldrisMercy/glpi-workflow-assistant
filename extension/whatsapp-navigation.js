'use strict';
// Only the local Assistant page can ask its paired extension to reuse a tab.
window.addEventListener('message', async event => {
  if (event.source !== window || event.origin !== location.origin ||
      location.origin !== 'http://127.0.0.1:8765' ||
      !['glpi-assistant:open-whatsapp','glpi-assistant:whatsapp-ping'].includes(event.data?.type) ||
      typeof event.data.requestId !== 'string' || event.data.requestId.length > 80) return;
  const requestId = event.data.requestId;
  if (event.data.type === 'glpi-assistant:whatsapp-ping') {
    window.postMessage({type:'glpi-assistant:whatsapp-pong',requestId},location.origin);return;
  }
  try {
    const target = new URL(event.data.url);
    if (target.origin !== 'https://web.whatsapp.com' || target.pathname !== '/send' ||
        !/^55\d{10,11}$/.test(target.searchParams.get('phone') || '') ||
        (target.searchParams.get('text') || '').length > 2000 ||
        [...target.searchParams.keys()].some(key => !['phone','text'].includes(key))) throw Error('Destino inválido.');
    const result = await browser.runtime.sendMessage({ type:'bridge:open-whatsapp', url:target.href });
    window.postMessage({type:'glpi-assistant:open-whatsapp-result',requestId,ok:!!result?.ok,error:result?.error||''}, location.origin);
  } catch(error) {
    window.postMessage({type:'glpi-assistant:open-whatsapp-result',requestId,ok:false,error:String(error?.message||'Falha ao abrir a conversa.')}, location.origin);
  }
});
