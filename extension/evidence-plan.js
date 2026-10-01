'use strict';
// Pure evidence-assignment planner. Kept dependency-free so the exact browser
// policy can be regression-tested in Node without a DOM.
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.GLPiEvidencePlan=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  function normId(v){const m=/^E(\d{2,3})$/i.exec(String(v||''));return m?`E${m[1]}`.toUpperCase():'';}
  function plan(requiredIds,files){
    const required=[...new Set((requiredIds||[]).map(normId).filter(Boolean))].sort((a,b)=>Number(a.slice(1))-Number(b.slice(1)));
    const scoped=(Array.isArray(files)?files:[]).filter(f=>f?.id !== '' && f?.role !== 'context');
    const explicit=scoped.filter(f=>normId(f?.id)&&String(f.id).toLowerCase()!=='auto').map(f=>({...f,id:normId(f.id)}));
    // Unclassified screenshots are never evidence merely because counts match.
    const automatic=scoped.filter(f=>f?.role==='evidence' && !normId(f?.id));
    const counts=new Map();for(const f of explicit)counts.set(f.id,(counts.get(f.id)||0)+1);
    const safeExplicit=explicit.filter(f=>required.includes(f.id)&&counts.get(f.id)===1);
    const assigned=safeExplicit.map(f=>({file:f,id:f.id,mode:'explicit'}));
    const missing=required.filter(id=>!assigned.some(x=>x.id===id));
    let ambiguous=false;
    if(automatic.length&&automatic.length<=missing.length){
      automatic.forEach((f,i)=>assigned.push({file:f,id:missing[i],mode:'ordered-partial'}));
    }else if(automatic.length){
      ambiguous=true;
    }
    if(safeExplicit.length!==explicit.length)ambiguous=true;
    const supplied=new Set(assigned.map(x=>x.id));
    const remaining=required.filter(id=>!supplied.has(id));
    return {assigned,remaining,pending:remaining.length>0,ambiguous,required};
  }
  function route(packets,files){
    const claims=new Map(),targets=new Map(),issues=[];
    for(const p of packets){
      const required=new Set([...String(p.closure).matchAll(/\[EVID[ÊE]NCIA\s*:\s*(E\d{2,3})\s*\]/gi)].map(m=>m[1].toUpperCase()));
      for(const m of String(p.closure).matchAll(/^\s*EVIDENCIA_ANEXO\s*:\s*(E\d{2,3})\s*\|\s*(A\d{2,4})\s*$/gmi)){
        const evidence=m[1].toUpperCase(),ref=m[2].toUpperCase(),ticket=Number(p.ticket_id);
        if(!required.has(evidence)||!Number.isSafeInteger(ticket)||ticket<=0)continue;
        const claim={ticket,evidence,ref},target=ticket+':'+evidence;
        if(!claims.has(ref))claims.set(ref,new Map());claims.get(ref).set(target,claim);
        if(!targets.has(target))targets.set(target,new Set());targets.get(target).add(ref);
      }
    }
    const assignments=[];
    for(const [ref,choices] of claims){
      const matches=files.filter(f=>f.ref===ref),c=[...choices.values()][0];
      if(choices.size!==1||targets.get(c.ticket+':'+c.evidence).size!==1||matches.length!==1){issues.push(ref);continue;}
      const f=matches[0];
      if(f.id===''||f.role==='context'||(f.ticket_id&&Number(f.ticket_id)!==c.ticket)||(f.id!=='auto'&&f.id!==c.evidence)){issues.push(ref);continue;}
      assignments.push({...c,key:f.key});
    }
    return {assignments,issues};
  }
  function resolveManifest(requiredIds,attachments,claims){
    const required=new Set((requiredIds||[]).map(normId).filter(Boolean));
    const assigned=[],unresolved=[],issues=[],seenAttachments=new Set(),seenTargets=new Set();
    for(const claim of claims||[]){
      const source=Number(claim?.source_index),ticket=Number(claim?.ticket_id),evidence=normId(claim?.evidence_id);
      const attachment=(attachments||[])[source-1];
      const target=`${ticket}:${evidence}`;
      if(!Number.isInteger(source)||!attachment||!Number.isSafeInteger(ticket)||ticket<=0||!required.has(evidence)){issues.push('associação inválida');continue;}
      if(attachment.role==='context'||attachment.classification==='context'){issues.push('contexto não pode ser evidência');continue;}
      if(seenAttachments.has(attachment.attachment_id)||seenTargets.has(target)){issues.push('associação duplicada');continue;}
      seenAttachments.add(attachment.attachment_id);seenTargets.add(target);
      assigned.push({attachment_id:attachment.attachment_id,source_index:source,ticket_id:ticket,evidence_id:evidence,task_id:String(claim.task_id||'').toUpperCase()});
    }
    for(const attachment of attachments||[])if(!assigned.some(x=>x.attachment_id===attachment.attachment_id)&&attachment.role!=='context'&&attachment.classification!=='context')unresolved.push(attachment);
    return {assignments:assigned,unresolved,issues};
  }
  return Object.freeze({plan,route,resolveManifest});
});
