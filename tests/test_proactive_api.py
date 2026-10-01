import sys
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]/'package/usr/lib/glpi-assistant/app'))

def test_review_then_apply_uses_server_evidence_and_self_requester(tmp_path,monkeypatch):
    import proactive_api as a
    import proactive_store as s
    import store
    monkeypatch.setattr(a,'DATA_DIR',tmp_path)
    monkeypatch.setattr(s,'DATA_DIR',tmp_path)
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'meta.db');store.ensure_storage()
    class G:
        base='https://glpi.test/apirest.php'
        def current_user_id(self):return 42
        def change_active_entity(self,*args,**kw):pass
        def get(self,path):return {'id':int(path.split('/')[-1]),'entities_id':7}
        def post(self,path,payload):self.ticket={'id':100,**payload['input']};return {'id':100}
        def get_ticket(self,id):return self.ticket
        def ticket_users(self,id):return [{'users_id':42,'type':1},{'users_id':42,'type':2}]
    g=G()
    @contextmanager
    def client():yield g
    app=FastAPI();a.register(app,client,lambda g,k,q,e:{'id':7 if k=='Entity' else 9,'name':q},lambda r:None,lambda r:None,lambda:{'timezone':'America/Sao_Paulo'})
    c=TestClient(app)
    import json
    raw={'schema_version':1,'operation':'create_proactive','draft_ref':'P01','title':'Teste','description':'Registro','entity':'Empresa','category':'Categoria','priority':3,'tasks':[],'evidence':[]}
    result=c.post('/api/proactive/receive',json={'closure':'[GLPI_PROACTIVE]'+json.dumps(raw)+'[/GLPI_PROACTIVE]','prompt_timestamp':'2026-09-30T00:12:22-03:00','conversation_key':'conv1'});assert result.status_code==200
    did=result.json()['drafts'][0]['id']
    plan=c.post('/api/proactive/plan',json={'id':did,'draft':raw});assert plan.status_code==200,plan.text
    p=plan.json();assert p['input']['_users_id_requester']==42
    invalid=c.post('/api/proactive/execute',json={'plan_id':p['plan_id'],'digest':'tampered'});assert invalid.status_code==409
    assert not hasattr(g,'ticket')
    high=c.post('/api/proactive/plan',json={'id':did,'draft':{**raw,'priority':4,'priority_explicit':True}}).json()
    assert 'priority_authorization' in high['pending_fields']
    assert c.post('/api/proactive/execute',json={'plan_id':high['plan_id'],'digest':high['digest']}).status_code==400
    # Review modified the persisted draft: the previous review cannot be used.
    assert c.post('/api/proactive/execute',json={'plan_id':p['plan_id'],'digest':p['digest']}).status_code==409
    p=c.post('/api/proactive/plan',json={'id':did,'draft':raw}).json()
    result=c.post('/api/proactive/execute',json={'plan_id':p['plan_id'],'digest':p['digest']})
    assert result.status_code==200,result.text
    assert result.json()['status']=='completed',result.text
    assert c.get('/api/proactive/drafts').json()['items']==[]
