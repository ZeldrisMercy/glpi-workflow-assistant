"""Local UI and paired Bridge endpoints for proactive drafts."""
import hashlib
import secrets
import time
from pathlib import Path
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from evidence_bridge import validate_images
from proactive_contract import parse_proactive_blocks, normalize_proactive
from proactive import build_proactive_plan, digest, execute_operation, EXECUTION_LOCK
from proactive_store import save_draft, list_drafts, save_operation, get_operation
from store import DATA_DIR, get_meta, set_meta

class Receive(BaseModel):
    closure:str
    prompt_timestamp:str|None=None
    conversation_key:str=Field(min_length=1,max_length=128)
    images:list[dict]=[]
    version:int=2
    source:str='ai'
    ticket_id:int|None=None
    manual:bool=False

class Review(BaseModel):
    prompt_timestamp:str|None=None
    id:str
    draft:dict
    priority_confirmed:bool=False

class Apply(BaseModel):
    plan_id:str
    digest:str


def register(app,client,resolve,local_guard,bridge_guard,settings):
    def identity(glpi): return hashlib.sha256(f'{glpi.base}|{glpi.current_user_id()}'.encode()).hexdigest()[:24]
    def scope_prefix():
        with client() as g: return identity(g)+':'
    def owned(did):
        prefix=scope_prefix()
        if not did.startswith(prefix): raise HTTPException(403,'Rascunho de outra conta')
        value=next((x for x in list_drafts() if x['id']==did),None)
        if not value: raise HTTPException(404,'Proativo não encontrado')
        return value
    def ingest(payload):
        rows=parse_proactive_blocks(payload.closure)
        # Image IDs are globally keyed by draft_ref:E-ID only for transport.
        with client() as g: scope=identity(g)
        result=[]
        directory=DATA_DIR/'proactive-images'; directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if sum(len(str(i.get('data') or '')) for i in payload.images)>28*1024*1024: raise ValueError('Imagens excedem o limite total do envio')
        if len(payload.images)>30: raise ValueError('Até 30 imagens por envio')
        for raw in rows:
            normalized=normalize_proactive(raw,payload.prompt_timestamp)
            did=scope+':'+hashlib.sha256((payload.conversation_key+'|'+normalized['draft_ref']).encode()).hexdigest()
            existing=next((x for x in list_drafts() if x['id']==did),{})
            if existing.get('completed') or existing.get('operation_id'): result.append(existing); continue
            timestamp=existing.get('prompt_timestamp') or payload.prompt_timestamp
            images=dict(existing.get('images',{}))
            supplied=[{'id':x.get('id'),'data':x.get('data')} for x in payload.images if x.get('draft_ref')==normalized['draft_ref']]
            expected={e['id'] for e in normalized['evidence'] if e.get('role','evidence')=='evidence'}
            for item in validate_images(supplied):
                if item['id'] not in expected: raise ValueError('Print não previsto no proativo')
                if len(item['data'])>4*1024*1024: raise ValueError('Print excede limite GLPI de 4 MiB')
                imagepath=directory/(item['hash']+'.'+item['name'].split('.')[-1])
                if not imagepath.exists(): imagepath.write_bytes(item['data']); imagepath.chmod(0o600)
                images[item['id']]={k:v for k,v in item.items() if k!='data'}
                images[item['id']]['path']=str(imagepath)
            value={'draft':raw,'prompt_timestamp':timestamp,'images':images,'completed':False,'received_at':time.time(),'conversation_key':payload.conversation_key,'operation_id':existing.get('operation_id')}
            save_draft(did,value); result.append({'id':did,**value})
        return {'ok':True,'drafts':result,'evidence_ready':all(all(e['id'] in r.get('images',{}) for e in r.get('draft',{}).get('evidence',[]) if e.get('role','evidence')=='evidence') for r in result)}
    @app.post('/api/bridge/proactive')
    def receive_bridge(payload:Receive,request:Request):
        bridge_guard(request)
        try: return ingest(payload)
        except HTTPException: raise
        except Exception as exc: raise HTTPException(400,str(exc))
    @app.post('/api/proactive/receive')
    def receive_ui(payload:Receive,request:Request):
        local_guard(request)
        try:return ingest(payload)
        except HTTPException:raise
        except Exception as exc:raise HTTPException(400,str(exc))
    @app.get('/api/proactive/drafts')
    def drafts(request:Request):
        local_guard(request); prefix=scope_prefix()
        return {'items':[d for d in list_drafts() if d['id'].startswith(prefix) and not d.get('completed')]}
    @app.get('/api/proactive/image/{draft_id}/{eid}')
    def image(draft_id:str,eid:str,request:Request):
        local_guard(request); value=owned(draft_id); item=value['images'].get(eid)
        if not item: raise HTTPException(404,'Imagem não encontrada')
        from fastapi.responses import FileResponse
        return FileResponse(item['path'],media_type=item['type'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Cross-Origin-Resource-Policy':'same-origin'})
    @app.post('/api/proactive/plan')
    def review(payload:Review,request:Request):
        local_guard(request); stored=owned(payload.id)
        if stored.get('operation_id'): raise HTTPException(409,'Execução iniciada. Continue a operação existente.')
        if not stored.get('prompt_timestamp') and payload.prompt_timestamp:
            stored['prompt_timestamp']=payload.prompt_timestamp
        raw=dict(payload.draft)
        # High priority authorization is a local review action, never an AI-provided flag.
        raw['priority_explicit']=payload.priority_confirmed
        with client() as g:
            scope=identity(g)
            def real_resolve(kind,query,entity):
                item=resolve(g,kind,query,entity)
                if kind=='Entity':
                    g.change_active_entity(int(item['id']),recursive=True)
                    live=g.get('Entity/'+str(item['id']))
                else: live=g.get(kind+'/'+str(item['id']))
                if int(live.get('id') or 0)!=int(item['id']): raise ValueError('Cadastro não confirmado no GLPI')
                if kind=='ITILCategory' and live.get('entities_id') is not None and int(live['entities_id']) not in (0,int(entity or 0)) and not live.get('is_recursive'):
                    raise ValueError('Categoria pertence a outra entidade')
                return item
            try: plan=build_proactive_plan(raw,stored.get('prompt_timestamp'),real_resolve,g.current_user_id(),scope,settings()['timezone'],stored['images'])
            except (ValueError,TypeError,KeyError) as exc: raise HTTPException(400,str(exc))
        plan['draft_ref']=payload.id  # durable identity includes account + conversation + local reference
        plan['id']=payload.id; plan['expires']=time.time()+600
        pid=secrets.token_urlsafe(24); set_meta('proactive_plan_'+pid,plan)
        save_draft(payload.id,{**stored,'draft':raw,'plan_id':pid})
        return {'plan_id':pid,**plan}
    @app.post('/api/proactive/execute')
    def apply(payload:Apply,request:Request):
        local_guard(request)
        with EXECUTION_LOCK,client() as g:
            plan=get_meta('proactive_plan_'+payload.plan_id,{})
            if not plan or plan['scope']!=identity(g) or plan['digest']!=payload.digest or plan['expires']<time.time(): raise HTTPException(409,'Revise novamente este proativo')
            if plan['pending_fields']: raise HTTPException(400,'Resolva as pendências')
            stored=owned(plan['id'])
            if digest({'draft':normalize_proactive(stored['draft'],stored['prompt_timestamp']),'images':stored['images']})!=plan['source_digest']: raise HTTPException(409,'Rascunho ou evidências alterados; revise novamente')
            op=save_operation(plan); save_draft(plan['id'],{**stored,'operation_id':op['operation_id']})
            outcome=execute_operation(g,op['operation_id'])
            save_draft(plan['id'],{**stored,'operation_id':op['operation_id'],'completed':outcome['status']=='completed','outcome':outcome})
            outcome['url']=g.base.removesuffix('/apirest.php')+'/front/ticket.form.php?id='+str(outcome['ticket_id']) if outcome.get('ticket_id') else None
            return outcome
    @app.post('/api/proactive/resume/{draft_id}')
    def resume(draft_id:str,request:Request):
        local_guard(request); stored=owned(draft_id)
        if not stored.get('operation_id'): raise HTTPException(400,'Operação não iniciada')
        with client() as g:
            op=get_operation(stored['operation_id'])
            if op['plan']['scope']!=identity(g): raise HTTPException(403,'Operação de outra conta')
            outcome=execute_operation(g,op['operation_id'])
        save_draft(draft_id,{**stored,'completed':outcome['status']=='completed','outcome':outcome})
        return outcome
