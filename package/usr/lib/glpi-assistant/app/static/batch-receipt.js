'use strict';
// The receipt never sends data: it only reports confirmed outcomes and selects drafts.
(() => {
  const node = (tag, cls, text) => { const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n; };
  let dialog;
  function show({outcomes, pending, selectPending, createDraft}) {
    if(!dialog){
      dialog=node('dialog','batch-receipt');dialog.id='batchReceipt';
      dialog.setAttribute('aria-labelledby','batchReceiptTitle');
      document.body.append(dialog);
    }
    dialog.replaceChildren();
    const ok=outcomes.filter(x=>x.ok).length, failed=outcomes.some(x=>!x.ok);
    const head=node('header','receipt-head');
    head.append(node('span','receipt-symbol'+(failed?' attention':''),failed?'!':'✓'));
    const copy=node('div');copy.append(node('span','receipt-eyebrow','COMPROVANTE DO LOTE'));
    const title=node('h2',null,failed?'Lote interrompido':'Envio confirmado');title.id='batchReceiptTitle';copy.append(title);
    copy.append(node('p',null,failed?'Os resultados confirmados foram preservados. Confira a pendência antes de continuar.':'Os chamados enviados saíram das abas. Você pode seguir para o próximo atendimento.'));
    const close=node('button','secondary receipt-close','×');close.type='button';close.setAttribute('aria-label','Fechar comprovante');close.onclick=()=>dialog.close();head.append(copy,close);
    const stats=node('div','receipt-stats');
    for(const [count,label] of [[ok,'envios confirmados'],[outcomes.length-ok,'exigem conferência'],[pending.length,'abas pendentes']]){const item=node('div');item.append(node('strong',null,String(count)),node('span',null,label));stats.append(item);}
    const list=node('div','receipt-results');list.setAttribute('aria-label','Resultado por chamado');
    for(const result of outcomes){const row=node('article','receipt-result'+(result.ok?'':' attention'));row.append(node('span','receipt-result-icon',result.ok?'✓':'!'));const text=node('div');text.append(node('strong',null,'#'+result.id),node('p',null,result.detail));row.append(text);list.append(row);}
    dialog.append(head,stats,list);
    if(pending.length){
      const section=node('section','receipt-pending');section.append(node('h3',null,'Continuar em outro chamado'));
      const buttons=node('div','receipt-next-list');
      for(const item of pending){const button=node('button','secondary',`#${item.id || 'Novo'} · ${item.state}`);button.type='button';button.onclick=()=>{dialog.close();selectPending(item.key);};buttons.append(button);}
      section.append(buttons);dialog.append(section);
    }
    const footer=node('footer','receipt-footer');footer.append(node('span',null,'Este comprovante não dispara novos envios.'));
    const newButton=node('button',null,'Novo chamado');newButton.type='button';newButton.onclick=()=>{dialog.close();createDraft();};const buttons=node('div','receipt-footer-actions');const dismiss=node('button','secondary','Fechar');dismiss.type='button';dismiss.onclick=()=>dialog.close();buttons.append(newButton,dismiss);footer.append(buttons);dialog.append(footer);
    if(!dialog.open)dialog.showModal();close.focus();
  }
  globalThis.BatchReceipt={show};
})();
