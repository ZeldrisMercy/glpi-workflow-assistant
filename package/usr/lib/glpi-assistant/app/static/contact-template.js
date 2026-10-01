'use strict';
// Literal replacement only. Ticket content is never interpreted as a template.
(() => {
  const labels={saudacao:'Saudação',nome:'Contato',tecnico:'Técnico',chamado:'Nº do chamado',assunto:'Assunto',empresa:'Empresa'};
  const defaultMessage='{saudacao}, tudo bem? Sou {tecnico}, da Equipe de Suporte. Estou entrando em contato referente ao chamado #{chamado} – {assunto}. Podemos prosseguir por aqui?';
  const defaultContinuationMessage='{saudacao}, tudo bem? Sou {tecnico}, da Equipe de Suporte. Estou dando continuidade ao atendimento referente ao chamado #{chamado} – {assunto}. Podemos prosseguir por aqui?';
  function normalize(text){return String(text??'').replace(/\|\/Chamado\b/gi,'{chamado}');}
  function validate(text){
    text=normalize(text);
    if(!text.trim()||text.length>2000)throw Error('A mensagem deve conter entre 1 e 2000 caracteres.');
    const tokens=[...text.matchAll(/\{([^{}]*)\}/g)].map(m=>m[1]);
    const invalid=tokens.find(t=>!Object.hasOwn(labels,t));
    if(invalid!==undefined)throw Error(`Marcador não reconhecido: {${invalid}}. Use os botões de inserção.`);
    const rest=text.replace(/\{[^{}]*\}/g,'');
    if(/[{}]/.test(rest)||rest.includes('|/'))throw Error('Há um marcador incompleto. Use os botões para inseri-lo novamente.');
    if(!tokens.includes('chamado'))throw Error('Mantenha {chamado} no texto para preencher o número automaticamente.');
    if(/\b(?:chamado|ticket)\s*#?\s*\d+/i.test(text))throw Error('Troque o número fixo do chamado por {chamado}.');
    return text;
  }
  function greeting(now=new Date(),timeZone='America/Sao_Paulo'){
    const parts=new Intl.DateTimeFormat('pt-BR',{timeZone,hour:'numeric',hourCycle:'h23'}).formatToParts(now);
    const hour=Number(parts.find(p=>p.type==='hour').value);
    return hour>=5&&hour<12?'Bom dia':hour>=12&&hour<18?'Boa tarde':'Boa noite';
  }
  function render(template,context,now=new Date(),timeZone='America/Sao_Paulo'){
    const text=validate(template);
    const id=Number(context.chamado);
    if(!Number.isSafeInteger(id)||id<=0)throw Error('Selecione um chamado válido para o contato.');
    const values={...context,chamado:String(id),saudacao:greeting(now,timeZone)};
    return text.replace(/\{([^{}]*)\}/g,(_,key)=>{
      const value=values[key];
      if(value===undefined||value===null||!String(value).trim())throw Error(`Preencha o campo ${labels[key]} antes de abrir a conversa.`);
      return String(value); // Replacement callback preserves $, braces and HTML as plain data.
    });
  }
  globalThis.ContactTemplate=Object.freeze({labels,defaultMessage,defaultContinuationMessage,normalize,validate,greeting,render});
})();
