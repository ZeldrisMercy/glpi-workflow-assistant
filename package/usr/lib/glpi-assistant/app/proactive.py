"""Creation orchestration, separated from closure execution."""
from __future__ import annotations
import hashlib
import html
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from proactive_contract import normalize_proactive
from proactive_store import get_operation, update_operation

EXECUTION_LOCK=threading.RLock()
MARKER='[GLPI_PROACTIVE:'

def is_proactive(ticket:dict)->bool:
    return bool(re.search(r'\[GLPI_PROACTIVE:[a-f0-9]{32}\]',str(ticket.get('content') or '')))

def digest(value:dict)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def paragraph(text)->str:
    return '<p>'+html.escape(str(text or '')).replace('\n','<br>')+'</p>'

def build_proactive_plan(raw:dict,prompt_timestamp:str|None,resolve,user_id:int,scope:str,timezone:str,images:dict)->dict:
    draft=normalize_proactive(raw,prompt_timestamp)
    pending=list(draft['pending_fields']); resolved={}
    for field,kind in [('entity','Entity'),('category','ITILCategory'),('requester','User'),('assignee','User')]:
        query=draft.get(field)
        if field in ('requester','assignee') and not query:
            resolved[field]={'id':user_id,'name':'Usuário autenticado'}; continue
        if not query: continue
        try: resolved[field]=resolve(kind,str(query),resolved.get('entity',{}).get('id'))
        except Exception as exc: pending.append(field+': '+str(exc))
    groups=[]
    for query in draft.get('groups',[]):
        try: groups.append(resolve('Group',str(query),resolved.get('entity',{}).get('id')))
        except Exception as exc: pending.append('groups: '+str(exc))
    for task in draft['tasks']:
        if task.get('mode'):
            try: task['modality_group_id']=int(resolve('Group',str(task['mode']),resolved.get('entity',{}).get('id'))['id'])
            except Exception as exc: pending.append(task['id']+' modalidade: '+str(exc))
    used={eid for t in draft['tasks'] for eid in t.get('evidence_ids',[])}
    for e in draft['evidence']:
        if e.get('role','evidence')=='evidence' and e['id'] not in used: pending.append('evidence_unassigned:'+e['id'])
        if e.get('role','evidence')=='evidence' and e['id'] not in images: pending.append('evidence:'+e['id'])
    timestamp=draft['prompt_timestamp']
    fields={'name':draft.get('title',''),'content':paragraph(draft.get('description','')),'type':2,'priority':draft['priority'],'status':2}
    if timestamp: fields['date']=datetime.fromisoformat(timestamp.replace('Z','+00:00')).astimezone(ZoneInfo(timezone)).strftime('%Y-%m-%d %H:%M:%S')
    if 'entity' in resolved: fields['entities_id']=int(resolved['entity']['id'])
    if 'category' in resolved: fields['itilcategories_id']=int(resolved['category']['id'])
    for key,field in [('requester','_users_id_requester'),('assignee','_users_id_assign')]:
        if key in resolved: fields[field]=int(resolved[key]['id'])
    if groups: fields['_groups_id_assign']=[int(g['id']) for g in groups]
    return {'scope':scope,'user_id':user_id,'draft_ref':draft['draft_ref'],'draft':draft,'input':fields,'resolved':resolved,'groups':groups,'images':images,'pending_fields':pending,'source_digest':digest({'draft':normalize_proactive(raw,prompt_timestamp),'images':images}), 'digest':digest({'draft':draft,'input':fields,'images':images,'scope':scope})}

def execute_operation(glpi,operation_id:str,path=None)->dict:
    with EXECUTION_LOCK:
        op=get_operation(operation_id,path); plan=op['plan']; marker=MARKER+operation_id+']'
        if op['status']=='completed': return op
        if plan.get('pending_fields'): raise ValueError('Resolva as pendências antes de criar')
        def save(**changes):
            nonlocal op
            op=update_operation(operation_id,changes,path)
        glpi.change_active_entity(plan['input']['entities_id'],recursive=True)
        try:
            if not op['ticket_id']:
                if op['status'] in ('creating','uncertain'):
                    found=glpi.find_proactive(marker,plan['input']['entities_id'])
                    if len(found)!=1:
                        save(status='uncertain',error='Criação sem confirmação. Confira o GLPI; não haverá nova criação automática.')
                        return op
                    save(ticket_id=int(found[0]['id']),status='partial',error=None)
                else:
                    save(status='creating',error=None)
                    result=glpi.post('Ticket',{'input':{**plan['input'],'content':plan['input']['content']+paragraph(marker)}})
                    save(ticket_id=int(result['id']),status='partial')
            tid=op['ticket_id']; ticket=glpi.get_ticket(tid)
            if marker not in html.unescape(str(ticket.get('content') or '')) or int(ticket.get('entities_id') or 0)!=plan['input']['entities_id']:
                raise ValueError('O chamado não corresponde à operação/entidade revisada')
            if plan['input'].get('_users_id_requester') or plan['input'].get('_users_id_assign'):
                actors=glpi.ticket_users(tid)
                for field,actor_type in [('_users_id_requester',1),('_users_id_assign',2)]:
                    wanted=plan['input'].get(field)
                    if wanted and not any(int(a.get('users_id') or 0)==int(wanted) and int(a.get('type') or 0)==actor_type for a in actors):
                        raise ValueError('GLPI não confirmou os atores revisados. Confira requerente e técnico no chamado.')
            steps=op['steps']
            def step(key,find,write):
                if key in steps and steps[key].get('confirmed'): return steps[key]['id']
                if key in steps:
                    rows=find()
                    if len(rows)!=1: raise ValueError('Resultado incerto na etapa '+key+'. Confira antes de continuar.')
                    value=int(rows[0]['id'])
                else:
                    steps[key]={'confirmed':False}; save(steps=steps)
                    value=int(write())
                steps[key]={'confirmed':True,'id':value}; save(steps=steps)
                return value
            for task in plan['draft']['tasks']:
                task_marker=marker+':'+task['id']
                content=paragraph(task.get('title',''))+paragraph(task['content'])+paragraph(task_marker)
                taskid=step('task:'+task['id'],lambda m=task_marker:[t for t in glpi.ticket_tasks(tid) if m in html.unescape(str(t.get('content') or ''))],lambda t=task,c=content:glpi.create_task(tid,c,t['actiontime'],2,int(plan['input'].get('_users_id_assign') or plan['user_id']),int(t.get('modality_group_id') or 0)))
                for eid in task.get('evidence_ids',[]):
                    image=plan['images'][eid]; document_key='document:'+eid
                    # Uploads have no reliable lookup token in all GLPI versions: stop after uncertain upload instead of duplicating.
                    doc=step(document_key,lambda:[],lambda i=image:glpi.upload_document(Path(i['path']),plan['input']['entities_id'])['id'])
                    step('link:'+task['id']+':'+eid,lambda d=doc,i=taskid:[r for r in glpi.task_documents(i) if int(r.get('documents_id') or 0)==d],lambda d=doc,i=taskid:glpi.link_document_to_task(d,i))
                if task.get('evidence_ids'):
                    rendered=content
                    for eid in task['evidence_ids']:
                        doc=steps['document:'+eid]['id']
                        url=f'/front/document.send.php?docid={doc}&itemtype=Ticket&items_id={tid}'
                        rendered+=f'<p><a href="{html.escape(url,quote=True)}" target="_blank"><img alt="{html.escape(eid)}" src="{html.escape(url,quote=True)}"></a></p>'
                    # Repeating this PUT is safe; it rewrites the same task, never creates another.
                    glpi.update_task_content(taskid,rendered)
                    observed=html.unescape(str(glpi.ticket_task(taskid).get('content') or ''))
                    if any('docid='+str(steps['document:'+eid]['id']) not in observed for eid in task['evidence_ids']):
                        raise ValueError('GLPI não confirmou os prints na tarefa '+task['id'])
            target=plan['draft']['target']
            if target!='active':
                solmarker=marker+':solution'
                step('solution',lambda:[s for s in glpi.list_subitems('Ticket',tid,'ITILSolution') if solmarker in html.unescape(str(s.get('content') or ''))],lambda:glpi.post('ITILSolution',{'input':{'itemtype':'Ticket','items_id':tid,'content':paragraph(plan['draft']['solution'])+paragraph(solmarker)}})['id'])
                current=glpi.get_ticket(tid)
                if int(current.get('status') or 0) not in (5,6): raise ValueError('GLPI não confirmou a solução')
                if target=='close' and int(current['status'])!=6: glpi.put('Ticket/'+str(tid),{'input':{'id':tid,'status':6}})
            verified=glpi.get_ticket(tid)
            expected=6 if target=='close' else 5 if target=='solve' else 2
            if int(verified.get('status') or 0)!=expected: raise ValueError('Status final diferente do solicitado; confira o GLPI')
            for field in ('entities_id','itilcategories_id','priority','type','date'):
                if field in plan['input'] and str(verified.get(field))!=str(plan['input'][field]):
                    raise ValueError('GLPI alterou o campo '+field+' em relação à revisão. Confira o chamado criado.')
            save(status='completed',error=None,verified_ticket={k:verified.get(k) for k in ('id','name','status','entities_id','itilcategories_id','priority','date','type')})
        except Exception as exc:
            save(status='partial' if op['ticket_id'] else 'uncertain',error=str(exc)[:400])
        return op
