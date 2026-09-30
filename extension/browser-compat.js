'use strict';
// Chrome rolls out Promise-returning listeners gradually. Keep the callback
// channel open explicitly and preserve rejected responses for our callers.
if (!globalThis.browser && globalThis.chrome) {
  const api = globalThis.chrome;
  const listeners = new WeakMap();
  const event = api.runtime.onMessage;
  const add = event.addListener.bind(event);
  const remove = event.removeListener?.bind(event);
  event.addListener = function (listener) {
    const wrapped = function (message, sender, sendResponse) {
      try {
        const result = listener(message, sender, sendResponse);
        if (result && typeof result.then === 'function') {
          result.then(sendResponse, error => sendResponse({__glpiBridgeError: String(error?.message || 'Falha de comunicação')}));
          return true;
        }
        return result;
      } catch (error) {
        sendResponse({__glpiBridgeError: String(error?.message || 'Falha de comunicação')});
        return false;
      }
    };
    listeners.set(listener, wrapped); add(wrapped);
  };
  if (remove) event.removeListener = listener => remove(listeners.get(listener) || listener);
  for (const owner of [api.runtime, api.tabs].filter(Boolean)) {
    if (!owner.sendMessage) continue;
    const send = owner.sendMessage.bind(owner);
    owner.sendMessage = (...args) => Promise.resolve(send(...args)).then(result => {
      if (result?.__glpiBridgeError) throw Error(result.__glpiBridgeError);
      return result;
    });
  }
  globalThis.browser = api;
}
