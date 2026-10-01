import base64
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock

APP = Path(__file__).resolve().parents[1] / 'package/usr/lib/glpi-assistant/app'
sys.path.insert(0, str(APP))
os.environ['GLPI_ASSISTANT_DATA'] = tempfile.mkdtemp(prefix='glpi-tests-')
import pytest
import requests
from fastapi.testclient import TestClient
import main
from parser import parse_closure, resolve_bridge_ticket_id
from store import DATA_DIR, get_meta, set_meta, connect, save_config
from workbench import stamp, whatsapp, contact_phone_from_text
from contact_template import validate_contact_template, DEFAULT_CONTACT_MESSAGE


def closure(ids=(1,)):
    return '\n\n'.join(f'[TAREFA:T{i:02d}]\nmodalidade: REMOTO\nnivel: N1\ntempo: 00:00\nestado: FEITO\nRelato técnico {i}.\n[/TAREFA]' for i in ids)


class Fake:
    base = 'https://glpi.example/apirest.php'
    def __init__(self):
        self.tickets = {1: {'id':1,'name':'Conferência backup','content':'Backup falhou','status':2,'entities_id':7,'date_mod':'2026-09-10 10:00:00'}}
        self.tasks = {}
        self.followups = {}
        self.assigned_ids={1}
        self.writes=[]
        self.links=[]
        self.fail_post=False
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def current_user_id(self): return 9
    def activate_context_for_ticket(self,tid): return self.get_ticket(tid)
    def get_ticket(self,tid): return copy.deepcopy(self.tickets[tid])
    def ticket_users(self,tid): return [{'users_id':9,'type':2}] if tid in self.assigned_ids else []
    def ticket_tasks(self,tid): return [copy.deepcopy(x) for x in self.tasks.values() if x['tickets_id']==tid]
    def ticket_task(self,tid): return copy.deepcopy(self.tasks[tid])
    def list_subitems(self,*args):
        if len(args)==3 and args[2]=='ITILFollowup': return [copy.deepcopy(r) for r in self.followups.values() if r['items_id']==args[1]]
        return []
    def list_search_options(self,*args):
        return {'2':{'table':'glpi_tickets','field':'id'},'5':{'table':'glpi_users','field':'name'},'12':{'table':'glpi_tickets','field':'status'},'80':{'table':'glpi_entities','field':'completename'},'1':{'table':'glpi_tickets','field':'name'},'15':{'table':'glpi_tickets','field':'date_mod'},'17':{'table':'glpi_tickets','field':'closedate'},'18':{'table':'glpi_tickets','field':'solvedate'}}
    def get(self,path,params=None):
        if path.startswith('ITILFollowup/'): return copy.deepcopy(self.followups[int(path.split('/')[-1])])
        if path=='search/Ticket':
            ids=[i for i in self.assigned_ids if self.tickets[i]['status']<5]
            return {'data':[{'2':i} for i in ids], 'totalcount':len(ids)}
        raise ValueError(path)
    def create_task(self,tid,content,actiontime,state,uid,gid):
        i=len(self.tasks)+100
        self.tasks[i]={'id':i,'tickets_id':tid,'content':content,'users_id':uid,'actiontime':actiontime,'state':state}
        self.writes.append(('task',tid))
        if self.fail_post: raise RuntimeError('timeout after commit')
        return i
    def post(self,path,payload):
        self.writes.append((path,payload))
        if path=='ITILFollowup':
            fid=len(self.followups)+200
            self.followups[fid]={**payload['input'],'id':fid,'users_id':9}
            if self.fail_post: raise RuntimeError('timeout after commit')
            return {'id':fid}
        if self.fail_post: raise RuntimeError('timeout')
        if path=='ITILSolution': self.tickets[payload['input']['items_id']]['status']=5
        return {'id':100}
    def put(self,path,payload):
        self.writes.append((path,payload))
        if path.startswith('ITILFollowup/'):
            self.followups[payload['input']['id']].update(payload['input']);return
        self.tickets[payload['input']['id']]['status']=payload['input']['status']
    def upload_document(self,path,entity):
        self.writes.append(('upload',path.name));return {'id':777}
    def link_document_to_task(self,did,tid):self.links.append((did,tid));return 50
    def task_documents(self,tid):return [{'documents_id':d} for d,t in self.links if t==tid]
    def update_task_content(self,tid,content):self.tasks[tid]['content']=content;self.writes.append(('update',tid))
    def update_task(self,tid,fields):self.tasks[tid].update(fields);self.writes.append(('task_fields',tid,fields))


@pytest.fixture
def env(monkeypatch):
    with connect() as con:
        con.execute('DELETE FROM meta');con.execute('DELETE FROM bridge_handoff')
    fake=Fake()
    monkeypatch.setattr(main.whatsapp_auto,'resolve_chat_id',lambda phone: phone+'@c.us')
    monkeypatch.setattr(main,'_client',lambda:fake)
    monkeypatch.setattr(main,'_ticket_snapshot',lambda g,i:{'id':i,'title':g.tickets[i]['name'],'status':g.tickets[i]['status'],'entity_id':7,'entity':{'label':'Empresa A'},'category':{'label':'Backup'},'priority':3,'requesters':[],'raw':g.get_ticket(i)})
    save_config({'url':'https://glpi.example/apirest.php','user_token':'test'})
    return TestClient(main.app, base_url="http://127.0.0.1:8765"),fake


@pytest.mark.parametrize('ids',[(1,), (2,4,5), tuple(range(1,9)), (99,100,999)])
def test_any_task_count(ids):
    assert len(parse_closure(closure(ids))['tasks'])==len(ids)


def test_categories_use_ticket_entity(env):
    client, fake = env
    entities = []
    fake.change_active_entity = lambda entity, recursive=False: entities.append((entity, recursive))
    fake.list_all = lambda kind: [{'id': 8, 'name': 'Backup'}]
    result = client.get('/api/workbench/categories?ticket_id=1&entity_id=99')
    assert result.status_code == 200
    assert entities == [(7, False)]
    assert result.json()['items'] == [{'id': 8, 'name': 'Backup'}]


@pytest.mark.parametrize('text',[closure((2,1)),closure((1,1)),closure()+ '\n[TAREFA:T02]incompleto', closure()+'[/TAREFA]'])
def test_bad_task_contract_rejected(text):
    with pytest.raises(ValueError):parse_closure(text)


def test_legacy_semicolon_groups_are_split_and_deduplicated():
    text = closure() + '''
[ALTERACOES_CHAMADO]
adicionar_grupo: REMOTO; SUPORTE N1; REMOTO
adicionar_grupo:
- SUPORTE N1
[/ALTERACOES_CHAMADO]
'''
    parsed = parse_closure(text)
    assert parsed['changes']['adicionar_grupo'] == ['REMOTO', 'SUPORTE N1']


@pytest.mark.parametrize('suffix', ['[ALTERACOES_CHAMADO]\nadicionar_grupo: REMOTO', '[/ALTERACOES_CHAMADO]'])
def test_incomplete_change_blocks_rejected(suffix):
    with pytest.raises(ValueError, match='incompleto'):
        parse_closure(closure() + suffix)


def test_duplicate_evidence_inside_one_task_rejected():
    with pytest.raises(ValueError, match='repetida'):
        parse_closure(closure().replace('Relato técnico 1.', '[EVIDÊNCIA:E01]\n[EVIDÊNCIA:E01]'))


@pytest.mark.parametrize('marker', ['[EVIDÊNCIA:E01]', '[EVIDÊNCIA: E01]', '[EVIDENCIA:E01]', '[evidencia : e01]'])
def test_evidence_marker_is_replaced_inline_for_all_accepted_forms(marker):
    rendered = f'<p>Antes {marker} depois</p>'
    result = main._replace_evidence_marker(rendered, 'E01', '<img src="x">')
    assert '<img src="x">' in result
    assert 'E01]' not in result.casefold().replace('e01]', 'E01]')


def test_duplicate_comparison_ignores_flexible_evidence_marker_spacing():
    a = '<p><strong>3. Diagnóstico</strong></p><p>Teste concluído [EVIDÊNCIA: E01]</p>'
    b = '<p><strong>3. Diagnóstico</strong></p><p>Teste concluído</p>'
    assert main._task_compare_text(a) == main._task_compare_text(b)


def test_company_search_can_match_solution(env, monkeypatch):
    c, g = env
    monkeypatch.setattr(g, 'list_subitems', lambda parent, tid, kind: [{'content':'Serviço Zebra restaurado'}] if kind=='ITILSolution' else [])
    data = c.get('/api/workbench/company-search?ticket_id=1&q=zebra').json()
    assert data['items'][0]['id'] == 1
    assert 'Zebra' in data['items'][0]['excerpt']


def test_conflicting_ticket_markers():
    with pytest.raises(ValueError):resolve_bridge_ticket_id(1,'[GLPI_ASSISTANT:1] [GLPI_ASSISTANT:2]')


def test_whatsapp_and_timezone():
    assert whatsapp('(11) 00000-0001',1,'Backup & rede').startswith('https://wa.me/5511000000001?text=')
    assert whatsapp('5511000000001',1,'Backup').startswith('https://wa.me/5511000000001?text=')
    # Número local sem DDD apareceu em perfis reais e não pode gerar wa.me inválido.
    assert whatsapp('9900-0109',1,'x') is None
    assert whatsapp('123',1,'x') is None
    assert stamp('2026-09-12 10:00:00','America/Sao_Paulo')==stamp('2026-09-12T13:00:00+00:00','UTC')


@pytest.mark.parametrize('text,expected',[
    ('Qual é o telefone para contato com o colaborador? : 31000000101','31000000101'),
    ('Digite o telefone para contato: (31) 00000-0102','31000000102'),
    ('Telefone para contato com o colaborador - 31.00000 0103','31000000103'),
    ('Digite o telefone para contato : 310 0000-0104','31000000104'),
    ('Digite o telefone para contato : (031) 00000-0105','31000000105'),
    ('Digite o telefone para contato : 031 0 0000-0106','31000000106'),
    ('Digite o telefone para contato : (031) 00000-0107','31000000107'),
    ('Patrimônio 901430; contato sem telefone',''),
])
def test_real_form_phone_variations(text, expected):
    assert contact_phone_from_text(text)==expected


def test_contact_template_persisted_and_bounded(env):
    c, g = env
    assert c.put('/api/workbench/settings', json={'contact_message':'Olá {nome}, chamado {chamado}.'}).status_code == 200
    assert c.get('/api/workbench').json()['settings']['contact_message'] == 'Olá {nome}, chamado {chamado}.'
    assert c.put('/api/workbench/settings', json={'contact_message':'x'*2001}).status_code == 422
    assert not g.writes


def test_auto_initial_is_enabled_by_default_but_baseline_stays_read_only(env):
    c, g = env
    data = c.get('/api/workbench').json()
    assert data['settings']['auto_initial'] is True
    first = c.post('/api/workbench/sync')
    assert first.status_code == 200
    assert not g.writes
    assert first.json()['items'][0]['initial'] == 'base existente'


def test_partial_settings_update_preserves_saved_values(env):
    c,g=env
    full={'enabled':True,'auto_initial':False,'stale_hours':36,'interval':300,'timezone':'America/Sao_Paulo','country_code':'55','contact_message':'Chamado {chamado}.','contact_name':'Teste'}
    assert c.put('/api/workbench/settings',json=full).status_code==200
    assert c.put('/api/workbench/settings',json={'auto_initial':True}).status_code==200
    saved=c.get('/api/workbench').json()['settings']
    assert saved['auto_initial'] is True
    assert saved['stale_hours']==36 and saved['interval']==300
    assert saved['contact_name']=='Teste' and saved['contact_message']=='Chamado {chamado}.'


def test_rc1_safety_gate_is_reenabled_once_on_rc2_startup(env):
    c,g=env
    set_meta('workbench_3_1_rc1_safety_applied', True)
    set_meta('workbench_settings', {'auto_initial': False, 'interval': 300})
    with TestClient(main.app, base_url="http://127.0.0.1:8765") as started:
        settings=started.get('/api/workbench').json()['settings']
        assert settings['auto_initial'] is True
        assert settings['interval']==300
    assert get_meta('workbench_3_1_rc2_auto_initial_applied') is True


@pytest.mark.parametrize('template',['{Chamado}','sem número','{chamado','{chamado} {tecncio}','{{chamado}}','Chamado 170424 e {chamado}'])
def test_invalid_contact_template_preserves_saved_model(env,template):
    c,g=env
    before=c.get('/api/workbench').json()['settings']['contact_message']
    assert c.put('/api/workbench/settings',json={'contact_message':template}).status_code==400
    assert c.get('/api/workbench').json()['settings']['contact_message']==before


def test_contact_alias_and_profile(env,monkeypatch):
    c,g=env
    assert validate_contact_template('Olá, chamado |/Chamado')=='Olá, chamado {chamado}'
    old=g.get
    monkeypatch.setattr(g,'get',lambda path,params=None: {'firstname':'Alex','realname':'Exemplo'} if path=='User/9' else old(path,params))
    assert c.get('/api/workbench/contact-profile').json()['name']=='Alex Exemplo'


def test_my_queue_searches_tasks_and_trusts_native_assignment_filter(env,monkeypatch):
    c,g=env
    g.tasks[100]={'id':100,'tickets_id':1,'content':'Outlook autenticação corrigida','users_id':9,'date':'2026-09-12 09:00:00'}
    r=c.get('/api/workbench/my-tickets?q=outlook')
    assert r.status_code==200,r.text
    assert r.json()['items'][0]['match_source']=='Tarefa #100'
    assert r.json()['items'][0]['last_own_update'] is not None
    # A busca do GLPI já filtrou o técnico; a fila não faz um Ticket_User extra por linha.
    monkeypatch.setattr(g,'ticket_users',lambda tid:(_ for _ in ()).throw(AssertionError('redundant assignment read')))
    assert [x['id'] for x in c.get('/api/workbench/my-tickets').json()['items']]==[1]


def test_my_queue_default_page_defers_timeline_reads(env, monkeypatch):
    c, g = env
    def unnecessary(*args):
        raise AssertionError('Timeline must be lazy on an unfiltered queue page')
    monkeypatch.setattr(g, 'ticket_tasks', unnecessary)
    response = c.get('/api/workbench/my-tickets')
    assert response.status_code == 200, response.text
    assert [item['id'] for item in response.json()['items']] == [1]


def test_personal_closures_follow_solution_authorship_not_final_approver(env, monkeypatch):
    c,g=env
    g.tickets[1].update(status=5,solvedate='2026-09-18 09:00:00',closedate=None,users_id_lastupdater=9)
    old=g.get
    monkeypatch.setattr(g,'get',lambda path,params=None: {'data':[{'2':1}],'totalcount':1} if path=='search/Ticket' else old(path,params))
    mine=[{'id':77,'users_id':9,'users_id_editor':0,'content':'Solução aplicada pelo técnico','date_creation':'2026-09-18 09:00:00'}]
    monkeypatch.setattr(g,'list_subitems',lambda parent,tid,child: mine if child=='ITILSolution' else [])
    solved=c.get('/api/workbench/my-tickets?view=solved&days=0')
    assert solved.status_code==200, solved.text
    assert [x['id'] for x in solved.json()['items']]==[1]
    assert solved.json()['items'][0]['status']==5
    assert 'Solução registrada por você' in solved.json()['items'][0]['authorship']

    # A aprovação/fechamento pode ser feita por cliente ou automação. O chamado
    # continua no histórico técnico porque a solução é do usuário autenticado.
    g.tickets[1].update(status=6,closedate='2026-09-18 10:00:00')
    closed=c.get('/api/workbench/my-tickets?view=closed&days=0')
    assert closed.status_code==200, closed.text
    assert [x['id'] for x in closed.json()['items']]==[1]
    assert 'Solução técnica registrada por você' in closed.json()['items'][0]['authorship']


def test_my_queue_excludes_solved_even_if_still_assigned(env, monkeypatch):
    c,g=env
    g.tickets[1]['status']=5
    # Simula um search/Ticket permissivo/antigo devolvendo o ID mesmo assim;
    # a camada local deve falhar fechada e remover status Solucionado.
    old=g.get
    monkeypatch.setattr(g,'get',lambda path,params=None: {'data':[{'2':1}],'totalcount':1} if path=='search/Ticket' else old(path,params))
    result=c.get('/api/workbench/my-tickets?view=assigned')
    assert result.status_code==200, result.text
    assert result.json()['items']==[]


def test_company_search_task_terms_and_strict_entity(env):
    c, g = env
    g.tasks[100] = {'id':100, 'tickets_id':1, 'content':'Autenticação do Outlook corrigida', 'state':2}
    g.tickets[2] = {**g.tickets[1], 'id':2, 'entities_id':8, 'content':'Autenticação Outlook'}
    g.assigned_ids.add(2)
    r = c.get('/api/workbench/company-search', params={'ticket_id':1,'q':'outlook autenticacao'})
    assert r.status_code == 200, r.text
    assert [x['id'] for x in r.json()['items']] == [1]
    assert 'Outlook' in r.json()['items'][0]['excerpt']
    assert sum(x['count'] for x in r.json()['categories']) == 1
    assert not g.writes


def test_company_search_filters_and_validation(env):
    c, g = env
    assert c.get('/api/workbench/company-search').status_code == 400
    assert c.get('/api/workbench/company-search?ticket_id=1&days=0').status_code == 400
    assert c.get('/api/workbench/company-search?ticket_id=1&status=6').json()['items'] == []
    assert c.get('/api/workbench/company-search?ticket_id=1&q=inexistente').json()['items'] == []


def test_recent_edits_fallback_and_parent_ticket(env):
    c, g = env
    g.tasks[100] = {'id':100, 'tickets_id':1, 'content':'Conferência realizada', 'state':2}
    r = c.get('/api/workbench/recent-edits')
    assert r.status_code == 200, r.text
    assert 'outras pessoas' in r.json()['scope']
    assert r.json()['items'][0]['tasks'][0]['ticket_id'] == 1
    assert not g.writes


def test_monitor_baseline_then_new_once(env):
    c,g=env
    assert c.put('/api/workbench/settings',json={'enabled':True,'auto_initial':True}).status_code==200
    r=c.post('/api/workbench/sync');assert r.status_code==200,r.text
    assert g.writes==[]
    g.tickets[2]={**g.tickets[1],'id':2};g.assigned_ids.add(2)
    assert c.post('/api/workbench/sync').status_code==200
    assert len(g.followups)==1 and g.tasks=={}, 'Responder deve existir antes da entrega'
    assert next(iter(g.followups.values()))['is_private']==0
    delivered_contact(g,2)
    c.post('/api/workbench/sync')
    assert len(g.followups)==1 and len(g.writes)==2
    assert 'Entrega ao aparelho confirmada' in next(iter(g.followups.values()))['content']
    c.post('/api/workbench/sync');assert len(g.writes)==2


def test_central_persists_failed_attempt_for_reload(env, monkeypatch):
    c,g=env
    monkeypatch.setattr(g, 'get', lambda path, params=None: (_ for _ in ()).throw(RuntimeError('consulta atribuída indisponível')) if path=='search/Ticket' else Fake.get(g,path,params))
    response=c.post('/api/workbench/sync')
    assert response.status_code==502
    state=c.get('/api/workbench').json()
    assert state['last_attempt'] is not None
    assert 'consulta atribuída indisponível' in state['monitor_error']


def test_uncertain_initial_post_reconciles_without_duplicate(env):
    c,g=env;c.put('/api/workbench/settings',json={'auto_initial':True});c.post('/api/workbench/sync')
    g.tickets[2]={**g.tickets[1],'id':2};g.assigned_ids.add(2);g.fail_post=True
    delivered_contact(g,2)
    c.post('/api/workbench/sync');c.post('/api/workbench/sync')
    assert len([w for w in g.writes if w[0]=='ITILFollowup'])==1
    assert len(g.followups)==1


def test_solution_batch_is_one_use(env):
    c,g=env
    g.tasks[100] = {'id':100, 'tickets_id':1, 'content':'Atendimento realizado', 'actiontime':600, 'state':2}
    p=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Backup conferido e validado.'}],'target':'close'})
    assert p.status_code==200,p.text
    r=c.post('/api/workbench/solution/apply',json={'plan_id':p.json()['plan_id']})
    assert r.status_code==200 and r.json()['ok'],r.text
    assert g.tickets[1]['status']==6
    assert c.post('/api/workbench/solution/apply',json={'plan_id':p.json()['plan_id']}).status_code==409
    assert len(g.writes)==2


def test_two_tickets_closed_in_one_review(env):
    c,g=env
    g.tickets[2]={**g.tickets[1], 'id':2}
    g.assigned_ids.add(2)
    g.tasks[100] = {'id':100, 'tickets_id':1, 'content':'Atendimento realizado', 'actiontime':600, 'state':2}
    g.tasks[101] = {'id':101, 'tickets_id':2, 'content':'Atendimento realizado', 'actiontime':600, 'state':2}
    p=c.post('/api/workbench/solution/plan',json={'items':[
        {'ticket_id':1,'content':'Backup conferido e validado na empresa A.'},
        {'ticket_id':2,'content':'Backup conferido e validado no segundo chamado.'}], 'target':'close'})
    assert p.status_code==200,p.text
    result=c.post('/api/workbench/solution/apply',json={'plan_id':p.json()['plan_id']})
    assert result.json()['ok'],result.text
    assert len(result.json()['results'])==2
    assert g.tickets[1]['status']==g.tickets[2]['status']==6


def test_closing_without_recorded_time_is_blocked_before_glpi_write(env):
    c, g = env
    response = c.post('/api/workbench/solution/plan', json={
        'items': [{'ticket_id': 1, 'content': 'Atendimento validado para encerramento.'}],
        'target': 'close',
    })
    assert response.status_code == 409
    assert 'exige duração' in response.text
    assert not g.writes


def test_changed_review_prevents_all_writes(env):
    c,g=env
    g.tasks[100]={'id':100,'tickets_id':1,'content':'Atendimento','state':2,'actiontime':60}
    p=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Backup conferido e validado.'}]}).json()
    g.tickets[1]['name']='Mudou'
    assert c.post('/api/workbench/solution/apply',json={'plan_id':p['plan_id']}).status_code==409
    assert g.writes==[]


def test_solution_requires_assignment(env):
    c,g=env;g.assigned_ids.clear()
    assert c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Backup conferido e validado.'}]}).status_code==403


def test_cross_origin_write_blocked(env):
    c,g=env
    assert c.put('/api/workbench/settings',headers={'Origin':'https://evil.example'},json={}).status_code==403


def test_bridge_partial_and_many_tasks(env):
    c,g=env;set_meta('bridge_token','test-token')
    for ids in [(2,),tuple(range(1,9))]:
        r=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':closure(ids)})
        assert r.status_code==200,r.text


def test_bridge_images_must_match_slots(env):
    c,g=env;set_meta('bridge_token','test-token')
    headers={'Authorization':'Bearer test-token'}
    img={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nexample').decode()}
    payload={'ticket_id':1,'closure':closure(),'images':[img]}
    assert c.post('/api/bridge/handoff',headers=headers,json=payload).status_code==400
    payload['closure']=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDENCIA:E01]')
    r=c.post('/api/bridge/handoff',headers=headers,json=payload);assert r.status_code==200,r.text
    inbox=c.get('/api/bridge/inbox').json()['items'][0]
    assert inbox['images'][0]['id']=='E01'
    assert c.get(f"/api/bridge/images/{inbox['id']}/E01").content.startswith(b'\x89PNG')


def test_bridge_accepts_text_before_declared_evidence_binary(env):
    c,g=env;set_meta('bridge_token','test-token')
    text=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDÊNCIA:E01]')
    result=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':text})
    assert result.status_code==200,result.text
    assert result.json()['evidence_ready'] is False
    assert result.json()['missing_evidence_ids']==['E01']
    inbox=c.get('/api/bridge/inbox').json()['items']
    assert len(inbox)==1 and inbox[0]['evidence_ready'] is False
    assert inbox[0]['missing_evidence_ids']==['E01']


def test_bridge_partial_text_is_upgraded_in_place_when_evidence_arrives(env):
    c,g=env;set_meta('bridge_token','test-token')
    headers={'Authorization':'Bearer test-token'}
    text=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDÊNCIA:E01]')
    first=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text})
    assert first.status_code==200
    hid=first.json()['handoff']['id']
    c.put(f'/api/bridge/handoff/{hid}/state',json={'status':'imported'})
    image={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nlate').decode()}
    second=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text,'images':[image]})
    assert second.status_code==200,second.text
    assert second.json()['handoff']['id']==hid
    assert second.json()['updated'] is True
    assert second.json()['handoff']['evidence_ready'] is True
    inbox=c.get('/api/bridge/inbox').json()['items']
    row=next(x for x in inbox if x['id']==hid)
    assert row['status']=='pending' and row['evidence_ready'] is True


def test_bridge_same_closure_updates_existing_handoff_when_print_changes(env):
    c,g=env;set_meta('bridge_token','test-token')
    headers={'Authorization':'Bearer test-token'}
    text=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDÊNCIA: E01]')
    first={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nfirst').decode()}
    second={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nsecond').decode()}
    a=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text,'images':[first]})
    handoff_id=a.json()['handoff']['id']
    first_hash=get_meta(f'bridge_images_{handoff_id}')[0]['hash']
    first_path=DATA_DIR/'bridge-images'/first_hash
    assert first_path.exists()
    b=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text,'images':[second],'manual':True})
    assert a.status_code==b.status_code==200
    assert not first_path.exists()
    assert b.json()['updated'] is True and b.json()['duplicate'] is False
    inbox=c.get('/api/bridge/inbox').json()['items']
    assert len(inbox)==1 and inbox[0]['status']=='pending'
    image_response=c.get(f"/api/bridge/images/{inbox[0]['id']}/E01")
    assert image_response.content.endswith(b'second')
    assert image_response.headers['cache-control']=='no-store'
    assert image_response.headers['cross-origin-resource-policy']=='same-origin'
    assert image_response.headers['x-content-type-options']=='nosniff'
    # Repetir exatamente o mesmo pacote volta a ser idempotente.
    again=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text,'images':[second],'manual':True})
    assert again.json()['duplicate'] is True and again.json()['updated'] is False


def test_bridge_delete_cleans_private_image_bytes(env):
    c,g=env;set_meta('bridge_token','test-token')
    text=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDÊNCIA:E01]')
    img={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nprivate-delete').decode()}
    r=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':text,'images':[img]})
    hid=r.json()['handoff']['id']
    digest=get_meta(f'bridge_images_{hid}')[0]['hash']
    path=DATA_DIR/'bridge-images'/digest
    assert path.exists()
    denied=c.delete(f'/api/bridge/handoff/{hid}',headers={'Origin':'https://evil.example'})
    assert denied.status_code==403 and path.exists()
    ok=c.delete(f'/api/bridge/handoff/{hid}')
    assert ok.status_code==200 and not path.exists()
    assert get_meta(f'bridge_images_{hid}',None) is None


def test_main_local_mutation_routes_reject_foreign_origin(env):
    c,g=env
    response=c.post('/api/setup/test',headers={'Origin':'https://evil.example'},json={
        'url':'https://glpi.example/apirest.php','user_token':'x','app_token':'','verify_tls':True
    })
    assert response.status_code==403


def test_security_headers_protect_local_ui_and_api(env):
    c,g=env
    page=c.get('/')
    assert page.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    api=c.get('/api/status')
    assert api.headers['cache-control']=='no-store'
    assert api.headers['x-content-type-options']=='nosniff'


def test_existing_template_keeps_original_and_state(env):
    c,g=env;g.create_task(1,'<p>Backup <b>diário</b></p>',300,1,9,0);g.writes.clear()
    png=b'\x89PNG\r\n\x1a\nexample'
    edits=[{'task_id':100,'text':'Backup diário','files':[0]}]
    p=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps(edits)},files=[('files',('print.png',png,'image/png'))])
    assert p.status_code==200,p.text
    assert not p.json()['rows'][0]['edited']
    r=c.post('/api/templates/apply',data={'plan_id':p.json()['id']},files=[('files',('print.png',png,'image/png'))])
    assert r.status_code==200 and r.json()['ok'],r.text
    assert '<b>diário</b>' in g.tasks[100]['content']
    assert g.tasks[100]['state']==1 and g.tasks[100]['actiontime']==300
    assert len(g.tasks)==1 and g.links==[(777,100)]


def test_template_rejects_files_changed_after_review(env):
    c,g=env;g.create_task(1,'Backup',300,1,9,0);g.writes.clear()
    png=b'\x89PNG\r\n\x1a\nexample'
    p=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps([{'task_id':100,'text':'Backup','files':[0]}])},files=[('files',('a.png',png,'image/png'))]).json()
    r=c.post('/api/templates/apply',data={'plan_id':p['id']},files=[('files',('b.png',png+b'changed','image/png'))])
    assert r.status_code==409 and g.writes==[]


def test_backup_template_never_gets_extra_initial_task(env):
    c,g=env;c.put('/api/workbench/settings',json={'auto_initial':True});c.post('/api/workbench/sync')
    g.tickets[2]={**g.tickets[1],'id':2};g.assigned_ids.add(2)
    g.create_task(2,'Conferir backup e anexar prints',300,1,9,0);g.writes.clear()
    r=c.post('/api/workbench/sync')
    assert r.status_code==200 and not g.writes
    assert len(g.tasks)==1
    assert 'modelo de backup existente' in next(i for i in r.json()['items'] if i['id']==2)['initial']


def test_semantic_problema_informado_prevents_duplicate_t01(env):
    c,g=env;c.put('/api/workbench/settings',json={'auto_initial':True});c.post('/api/workbench/sync')
    g.tickets[2]={**g.tickets[1],'id':2,'name':'Outlook indisponível'};g.assigned_ids.add(2)
    g.create_task(2,'<p><strong>1. Problema Informado</strong></p><p>Falha relatada.</p>',120,2,9,0);g.writes.clear()
    r=c.post('/api/workbench/sync')
    assert r.status_code==200 and not g.writes
    assert len([t for t in g.tasks.values() if t['tickets_id']==2])==1
    assert next(i for i in r.json()['items'] if i['id']==2)['initial']=='existente'


def test_backup_closure_blocks_state_zero_too(env):
    c,g=env;g.create_task(1,'Verificar backup',300,0,9,0)
    r=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Conferência realizada e verificada.'}],'target':'close'})
    assert r.status_code==409 and '100' in r.json()['detail']


def test_batch_stops_after_uncertain_first_write(env):
    c,g=env;g.tickets[2]={**g.tickets[1],'id':2};g.assigned_ids.add(2)
    for tid in (1,2):g.tasks[100+tid]={'id':100+tid,'tickets_id':tid,'content':'Atendimento','state':2,'actiontime':60}
    p=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':i,'content':'Backup validado pelo técnico.'} for i in (1,2)]}).json()
    g.fail_post=True
    r=c.post('/api/workbench/solution/apply',json={'plan_id':p['plan_id']})
    assert r.status_code==200 and not r.json()['ok']
    assert len(g.writes)==1
    assert 'Não executado' in r.json()['results'][1]['error']


def test_backup_task_completed_only_after_evidence_verified(env):
    c,g=env;g.create_task(1,'Conferir NAT',300,1,9,0);g.writes.clear()
    png=b'\x89PNG\r\n\x1a\nexample'
    p=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps([{'task_id':100,'text':'Conferir NAT','files':[0],'complete':True}])},files=[('files',('a.png',png,'image/png'))]).json()
    r=c.post('/api/templates/apply',data={'plan_id':p['id']},files=[('files',('a.png',png,'image/png'))])
    assert r.json()['ok'] and g.tasks[100]['state']==2
    assert g.tasks[100]['actiontime']==300
    assert [w[0] for w in g.writes]==['upload','update','task_fields']
    assert c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Conferência realizada e verificada.'}]}).status_code==200


def test_failed_upload_never_completes_backup_task(env,monkeypatch):
    c,g=env;g.create_task(1,'Conferir NAT',300,1,9,0);g.writes.clear()
    def fail(*args):raise RuntimeError('Upload falhou')
    monkeypatch.setattr(g,'upload_document',fail)
    png=b'\x89PNG\r\n\x1a\nexample'
    p=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps([{'task_id':100,'text':'Conferir NAT','files':[0],'complete':True}])},files=[('files',('a.png',png,'image/png'))]).json()
    r=c.post('/api/templates/apply',data={'plan_id':p['id']},files=[('files',('a.png',png,'image/png'))])
    assert not r.json()['ok'] and g.tasks[100]['state']==1 and not g.writes


def test_backup_closure_blocked_with_unchecked_tasks(env):
    c,g=env;g.create_task(1,'Verificar datastore',300,1,9,0)
    r=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Conferência realizada e verificada.'}],'target':'close'})
    assert r.status_code==409 and '100' in r.json()['detail']


def test_queue_preserves_ticket_when_optional_resources_denied(env,monkeypatch):
    c,g=env
    def denied(*args): raise RuntimeError('GLPI HTTP 403 ERROR_RIGHT_MISSING')
    monkeypatch.setattr(g,'list_subitems',denied)
    monkeypatch.setattr(g,'ticket_tasks',denied)
    monkeypatch.setattr(g,'ticket_users',denied)
    mine=c.get('/api/workbench/my-tickets?q=backup').json()
    assert [x['id'] for x in mine['items']]==[1]
    assert {x['resource'] for x in mine['warnings']} >= {'TicketTask','ITILFollowup','ITILSolution'}
    central=c.post('/api/workbench/sync').json()
    assert [x['id'] for x in central['items']]==[1]
    assert central['errors']==[]
    assert not g.writes


def test_monitor_preserves_all_entity_context_during_scan(env,monkeypatch):
    c,g=env
    # get_ticket já funciona no escopo all; não pode estreitar entidade a cada ticket.
    monkeypatch.setattr(g,'activate_context_for_ticket',lambda tid:(_ for _ in ()).throw(AssertionError('context thrash')))
    assert len(c.post('/api/workbench/sync').json()['items'])==1


def test_search_follows_server_capped_pages(env,monkeypatch):
    from workbench import search_ids
    c,g=env;calls=[]
    def get(path,params=None):
        start=int(params['range'].split('-')[0]);calls.append(start)
        return {'totalcount':5,'data':[{'2':i} for i in range(start+1,min(start+3,6))]}
    monkeypatch.setattr(g,'get',get)
    assert search_ids(g,[],limit=10)==([1,2,3,4,5],False)
    assert calls==[0,2,4]


def test_search_repeated_page_is_not_reported_complete(env,monkeypatch):
    from workbench import search_ids
    c,g=env
    monkeypatch.setattr(g,'get',lambda *args:{'totalcount':100,'data':[{'2':1}]})
    with pytest.raises(ValueError,match='repetiu'):search_ids(g,[],limit=10)


def test_subitems_follow_actual_content_range():
    from glpi import GlpiClient,GlpiConfig
    g=GlpiClient(GlpiConfig('https://glpi.example','test'));calls=[]
    class Response:
        headers={'Content-Range':'0-1/5'}
        def __init__(self,start):self.start=start
        def json(self):return [{'id':i} for i in range(self.start,min(self.start+2,5))]
    def get(path,params=None,raw=False):
        start=int(params['range'].split('-')[0]);calls.append(start);return Response(start)
    g.get=get
    assert len(g.list_subitems('Ticket',1,'Log'))==5
    assert calls==[0,2,4]


def test_metadata_cache_saves_reads_but_ticket_stays_fresh():
    from glpi import GlpiClient,GlpiConfig
    g=GlpiClient(GlpiConfig('https://glpi.example','test'));calls=[];writes=[]
    def get(path,params=None):
        calls.append(path)
        return {'session':{'glpiID':9}} if path=='getFullSession' else {'id':1,'status':2} if path=='Ticket/1' else {'2':{'field':'id'}}
    g.get=get;g.post=lambda path,payload:writes.append((path,payload))
    for _ in range(10):g.current_user_id();g.list_search_options('Ticket');g.change_active_entity(7)
    assert len(calls)==2 and len(writes)==1
    g.change_active_profile(2);g.list_search_options('Ticket');g.change_active_entity(7)
    assert len(calls)==3 and len(writes)==3
    g.get_ticket(1);g.get_ticket(1)
    assert calls[-2:]==['Ticket/1','Ticket/1']


def test_company_title_match_does_not_fetch_tasks(env,monkeypatch):
    c,g=env
    def forbidden(*args):raise AssertionError('Unnecessary task read')
    monkeypatch.setattr(g,'ticket_tasks',forbidden)
    d=c.get('/api/workbench/company-search?ticket_id=1&q=conferencia+de+backup').json()
    assert len(d['items'])==1 and not d['errors']


def test_closing_log_new_id_and_localized_value():
    from workbench import closing_actor
    base={'itemtype':'Ticket','items_id':1,'id_search_option':12,'user_name':'Alex (9)','new_value':'Fechado','id':1}
    assert closing_actor([base],1,12)==9
    assert closing_actor([{**base,'new_id':6,'new_value':'unfamiliar label'}],1,12)==9
    assert closing_actor([{**base,'new_id':5}],1,12) is None


def test_task_list_defers_documents_until_requested(env,monkeypatch):
    c,g=env;g.create_task(1,'Testar serviço',60,2,9,0)
    calls=[]
    monkeypatch.setattr(g,'task_documents',lambda tid:(calls.append(tid) or []))
    d=c.get('/api/ticket/1/tasks').json()
    assert d['tasks'][0]['documents_loaded'] is False
    assert calls==[]
    assert c.get('/api/ticket/1/tasks/100/documents').json()['documents']==[]
    assert calls==[100]


def test_backup_duration_is_recorded_before_completion(env):
    c,g=env;g.create_task(1,'Verificar armazenamento',0,1,9,0);g.writes.clear()
    change={'task_id':100,'text':'Verificar armazenamento','files':[],'complete':True,'actiontime':300}
    p=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps([change])}).json()
    d=c.post('/api/templates/apply',data={'plan_id':p['id']}).json()
    assert d['ok'] and g.tasks[100]['actiontime']==300 and g.tasks[100]['state']==2
    assert g.writes[0][2]=={'actiontime':300}
    assert g.writes[1][2]=={'state':2}


def test_diagnostic_identifies_resource_without_ticket_content(env,monkeypatch):
    c,g=env
    def read(parent,tid,child):
        if child=='ITILSolution':raise RuntimeError('403 ERROR_RIGHT_MISSING')
        return []
    monkeypatch.setattr(g,'list_subitems',read)
    d=c.get('/api/workbench/diagnostics/1').json()
    assert any(x['resource']=='ITILSolution' and not x['ok'] for x in d['checks'])
    assert g.tickets[1]['content'] not in json.dumps(d)


def test_real_search_options_never_use_unsupported_status_range():
    from workbench import equals_any, query_params, searchtype
    raw = {
        '2': {'table':'glpi_tickets','field':'id','available_searchtypes':['contains','notcontains']},
        '5': {'table':'glpi_users','field':'name','available_searchtypes':['contains','notcontains','equals','notequals']},
        '12': {'table':'glpi_tickets','field':'status','available_searchtypes':['equals']},
    }
    assert searchtype(raw, 2, 'equals', 'contains') == 'contains'
    assert searchtype(raw, 12, 'equals', 'lessthan') == 'equals'
    params = query_params([equals_any(12, (1,2,3,4,5)), (5,'equals',5470)])
    status_types = [v for k,v in params.items() if k.endswith('[searchtype]') and '[criteria]' in k]
    assert status_types == ['equals'] * 5
    assert 'lessthan' not in params.values()


def test_numeric_ticket_filter_uses_declared_contains_and_is_exact_client_side(env, monkeypatch):
    c,g=env
    opts=g.list_search_options()
    opts['2']['available_searchtypes']=['contains','notcontains']
    opts['12']['available_searchtypes']=['equals']
    opts['5']['available_searchtypes']=['equals']
    monkeypatch.setattr(g,'list_search_options',lambda *a:opts)
    g.tickets[11]={**g.tickets[1],'id':11,'name':'Outro'};g.assigned_ids.add(11)
    calls=[]
    def get(path,params=None):
        if path=='search/Ticket':
            calls.append(params.copy())
            return {'data':[{'2':1},{'2':11}], 'totalcount':2}
        raise ValueError(path)
    monkeypatch.setattr(g,'get',get)
    r=c.get('/api/workbench/my-tickets?q=1')
    assert r.status_code==200,r.text
    assert [x['id'] for x in r.json()['items']] == [1]
    assert any(v=='contains' for k,v in calls[0].items() if k.endswith('[searchtype]'))


def test_contact_phone_falls_back_to_ticket_form_when_user_lookup_denied(env, monkeypatch):
    c,g=env
    g.tickets[1]['content']='Falha no Outlook. Digite o telefone para contato: (31) 00000-0102'
    monkeypatch.setattr(g,'ticket_users',lambda tid:[{'users_id':9,'type':2},{'users_id':77,'type':1,'label':'Cliente'}])
    old=g.get
    def get(path,params=None):
        if path=='User/77': raise RuntimeError('GLPI HTTP 403: ERROR_RIGHT_MISSING')
        return old(path,params)
    monkeypatch.setattr(g,'get',get)
    data=c.post('/api/workbench/sync').json()
    contact=data['items'][0]['contacts'][0]
    assert contact['phone']=='5531000000102'
    assert contact['whatsapp'].startswith('https://wa.me/5531000000102?')


def test_ticket_form_phone_precedes_incomplete_profile_phone(env, monkeypatch):
    c,g=env
    g.tickets[1]['content']='Digite o telefone para contato com o colaborador? : 3100000108'
    monkeypatch.setattr(g,'ticket_users',lambda tid:[{'users_id':9,'type':2},{'users_id':77,'type':1,'label':'Cliente'}])
    old=g.get
    def get(path,params=None):
        if path=='User/77': return {'id':77,'firstname':'Ana','realname':'Silva','mobile':'9900-0109','phone':'3300-0110'}
        return old(path,params)
    monkeypatch.setattr(g,'get',get)
    contact=c.post('/api/workbench/sync').json()['items'][0]['contacts'][0]
    assert contact['phone']=='553100000108' and contact['phone_source']=='descricao'
    assert contact['whatsapp'].startswith('https://wa.me/553100000108?')


def test_requester_user_lookup_is_cached_during_sync(env, monkeypatch):
    c,g=env
    g.tickets[2]={**g.tickets[1],'id':2};g.assigned_ids.add(2)
    monkeypatch.setattr(g,'ticket_users',lambda tid:[{'users_id':9,'type':2},{'users_id':77,'type':1,'label':'Cliente'}])
    old=g.get;calls=[]
    def get(path,params=None):
        if path=='User/77':
            calls.append(path)
            return {'id':77,'firstname':'Ana','realname':'Silva','mobile':'31000000000'}
        return old(path,params)
    monkeypatch.setattr(g,'get',get)
    data=c.post('/api/workbench/sync').json()
    assert len(data['items'])==2
    assert calls==['User/77']


def test_get_retries_only_transient_reads(monkeypatch):
    from glpi import GlpiClient, GlpiConfig, GlpiError
    g=GlpiClient(GlpiConfig('https://glpi.example','test'))
    g.session_token='session'
    class Response:
        def __init__(self,status,payload=None):
            self.status_code=status;self._payload=payload;self.headers={};self.ok=200<=status<300;self.text='busy'
        def json(self): return self._payload
    monkeypatch.setattr('glpi.time.sleep',lambda *_:None)
    g.http.get=Mock(side_effect=[requests.Timeout('slow'),Response(503),Response(200,{'ok':True})])
    assert g.get('getFullSession')=={'ok':True}
    assert g.http.get.call_count==3
    g.http.post=Mock(side_effect=requests.Timeout('write timeout'))
    with pytest.raises(GlpiError):g.post('TicketTask',{'input':{}})
    assert g.http.post.call_count==1


def test_template_backup_lists_existing_documents_for_visual_review(env):
    c, g = env
    g.tasks[100] = {'id': 100, 'tickets_id': 1, 'content': 'Conferir backup', 'users_id': 9, 'state': 1, 'actiontime': 300}
    g.links.append((777, 100))
    result = c.get('/api/templates/1')
    assert result.status_code == 200, result.text
    task = result.json()['tasks'][0]
    assert task['id'] == 100
    assert task['documents'][0]['id'] == 777
    assert task['documents'][0]['name'] == 'Documento 777'


def test_waha_monitor_end_to_end(env, monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda method,path,payload=None,**kw: calls.append((method,path,payload)) or {'id':'wa-message'})
    c.put('/api/workbench/settings',json={'auto_initial':False,'contact_name':'Alex'})
    assert c.put('/api/whatsapp/settings',json={'enabled':True}).status_code==200
    c.post('/api/workbench/sync')
    assert not calls  # Existing assignments are only baseline.
    g.tickets[2]={**g.tickets[1],'id':2,'name':'Acesso VPN','content':'Telefone: (31) 00000-0000'}
    g.assigned_ids.add(2)
    assert c.post('/api/workbench/sync').status_code==200
    assert len(calls)==1
    assert calls[0][2]['chatId']=='5531000000000@c.us'
    assert '#2' in calls[0][2]['text'] and 'Alex' in calls[0][2]['text']
    c.post('/api/workbench/sync')
    g.assigned_ids.remove(2);c.post('/api/workbench/sync')
    g.assigned_ids.add(2);c.post('/api/workbench/sync')
    assert len(calls)==1  # Reassignment does not duplicate first contact.
    response=c.put('/api/whatsapp/settings',json={'enabled':False},headers={'Origin':'https://untrusted.example'})
    assert response.status_code==403


def test_waha_resume_one_click_and_idempotency(env, monkeypatch):
    import whatsapp_auto as wa
    import uuid
    c,g=env
    g.tickets[1]['content']='Telefone: (31) 00000-0000'
    c.put('/api/workbench/settings',json={'contact_name':'Alex','continuation_message':'Olá, sou {tecnico}. Retorno sobre #{chamado}: {assunto}.'})
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda *args,**kwargs:calls.append(args) or {'id':'resume1'})
    payload={'ticket_id':1,'request_id':str(uuid.uuid4())}
    response=c.post('/api/whatsapp/resume',json=payload)
    assert response.status_code==200,response.text
    assert 'Retorno sobre #1' in calls[0][2]['text']
    assert c.post('/api/whatsapp/resume',json=payload).status_code==200
    assert len(calls)==1
    assert c.post('/api/whatsapp/resume',json={**payload,'request_id':str(uuid.uuid4())}).status_code==409
    assert len(calls)==1


def test_waha_resume_revalidates_recipient_and_assignment(env,monkeypatch):
    import whatsapp_auto as wa
    import uuid
    c,g=env
    g.tickets[1]['content']='Telefone: (31) 00000-0000'
    c.put('/api/workbench/settings',json={'contact_name':'Alex'})
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    monkeypatch.setattr(wa,'api',lambda *a,**kw:pytest.fail('Must not send'))
    payload={'ticket_id':1,'request_id':str(uuid.uuid4())}
    g.assigned_ids.clear()
    assert c.post('/api/whatsapp/resume',json=payload).status_code==409
    g.assigned_ids.add(1)
    g.ticket_users=lambda tid:[{'users_id':9,'type':2},{'users_id':10,'type':1},{'users_id':11,'type':1}]
    g.tickets[1]['content']='Contato: (31) 00000-0000 ou (31) 00000-0001'
    assert c.post('/api/whatsapp/resume',json=payload).status_code==409
    # An explicit, unique description contact is primary even with multiple requesters.
    g.tickets[1]['content']='Contato: (31) 00000-0000'
    sent=[]
    monkeypatch.setattr(wa,'api',lambda *args,**kwargs: (sent.append(args) or {'id':'msg-primary'}))
    assert c.post('/api/whatsapp/resume',json=payload).status_code==200
    assert sent[0][2]['chatId']=='5531000000000@c.us'


def test_waha_resume_custom_text_and_uncertain_result(env,monkeypatch):
    import whatsapp_auto as wa
    import uuid
    c,g=env
    g.tickets[1]['content']='Telefone: (31) 00000-0000'
    c.put('/api/workbench/settings',json={'contact_name':'Alex'})
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    def fail(*args,**kwargs):calls.append(args);raise TimeoutError()
    monkeypatch.setattr(wa,'api',fail)
    payload={'ticket_id':1,'request_id':str(uuid.uuid4()),'text':'Retorno personalizado #1. Podemos prosseguir?'}
    assert c.post('/api/whatsapp/resume',json={**payload,'text':'Sem número'}).status_code==400
    response=c.post('/api/whatsapp/resume',json=payload)
    assert response.json()['status']=='resultado incerto'
    assert calls[0][2]['text']==payload['text']
    c.post('/api/whatsapp/resume',json=payload)
    assert len(calls)==1


def test_completed_packets_do_not_return_with_late_evidence(env):
    c,g=env;set_meta('bridge_token','test-token')
    headers={'Authorization':'Bearer test-token'}
    text=closure().replace('Relato técnico 1.','Relato técnico 1. [EVIDENCIA:E01]')
    first=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text}).json()
    main._remember_applied(1,text)
    img={'id':'E01','data':base64.b64encode(b'\x89PNG\r\n\x1a\nexample').decode()}
    second=c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':text,'images':[img]}).json()
    assert second['completed'] and second['evidence_ready']
    assert c.get('/api/bridge/inbox').json()['items']==[]
    c.put(f"/api/bridge/handoff/{first['handoff']['id']}/state",json={'status':'pending'})
    assert c.get('/api/bridge/inbox').json()['items']==[]


def test_completed_subset_suppressed_but_new_task_allowed(env):
    c,g=env;set_meta('bridge_token','test-token')
    main._remember_applied(1,closure((1,2,3)))
    headers={'Authorization':'Bearer test-token'}
    assert c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':closure((1,2))}).json()['completed']
    assert c.post('/api/bridge/handoff',headers=headers,json={'ticket_id':1,'closure':closure((4,))}).json()['created']


def test_legacy_closed_ticket_is_removed_from_inbox(env):
    c,g=env;set_meta('bridge_token','test-token')
    first=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':closure()}).json()
    c.put(f"/api/bridge/handoff/{first['handoff']['id']}/state",json={'status':'imported'})
    main._BRIDGE_RECONCILE_AT.clear()
    g.tickets[1]['status']=6
    assert c.get('/api/bridge/inbox').json()['items']==[]


def test_offline_legacy_packet_preserved(env,monkeypatch):
    c,g=env;set_meta('bridge_token','test-token')
    first=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':closure()}).json()
    c.put(f"/api/bridge/handoff/{first['handoff']['id']}/state",json={'status':'imported'})
    main._BRIDGE_RECONCILE_AT.clear()
    monkeypatch.setattr(g,'get_ticket',lambda tid:(_ for _ in ()).throw(RuntimeError('offline')))
    assert len(c.get('/api/bridge/inbox').json()['items'])==1


def test_execute_adds_contact_receipt_and_retires_only_confirmed_packet(env,monkeypatch):
    import hashlib
    c,g=env
    monkeypatch.setattr(main,'_resolve_catalog_live',lambda *a:{'id':7,'full_name':'REMOTO'})
    monkeypatch.setattr(main,'_apply_ticket_changes',lambda *a:None)
    original=g.create_task
    monkeypatch.setattr(g,'create_task',lambda **kw:original(kw['ticket_id'],kw['content'],kw['actiontime'],kw['state'],kw['tech_user_id'],kw['group_id']))
    scope=hashlib.sha256(f'{g.base}|9'.encode()).hexdigest()[:24]
    delivered_contact(g,1)
    text=closure()
    planned=c.post('/api/plan',json={'ticket_id':1,'text':text,'evidence_map':{}})
    assert planned.status_code==200,planned.text
    assert planned.json()['contact_receipt']['message_id']=='real-api-id'
    result=c.post('/api/execute',data={'ticket_id':'1','text':text,'evidence_map':'{}','plan_id':planned.json()['plan_id']})
    assert result.status_code==200,result.text
    assert result.json()['ok'],result.text
    assert 'Primeiro contato pelo WhatsApp' in next(iter(g.tasks.values()))['content']
    assert 'real-api-id' not in next(iter(g.tasks.values()))['content']
    assert main._already_applied(1,text,parse_closure(text))


def delivered_contact(g, tid):
    import hashlib
    scope=hashlib.sha256(f'{g.base}|9'.encode()).hexdigest()[:24]
    set_meta('waha_events_'+scope,{str(tid):{'ticket_id':tid,'status':'aceito pelo WAHA','message_id':'real-api-id','at':time.time(),'phone':'••••8888','message_text':f'Olá #{tid}','delivery_ack':2,'delivery_name':'DEVICE','delivery_observed_at':time.time()}})

@pytest.mark.parametrize('headers,code',[
    ({'Host':'evil.example'},400),
    ({'Origin':'https://evil.example'},403),
    ({'Sec-Fetch-Site':'cross-site'},403),
    ({'Host':'127.0.0.1.evil.example:8765'},400),
])
def test_local_boundary_blocks_rebinding_and_cross_site_reads(env,headers,code):
    c,g=env
    assert c.get('/api/status',headers=headers).status_code==code
    assert not g.writes


def test_extension_can_pair_but_cannot_access_local_controls(env):
    c,g=env
    headers={'Origin':'moz-extension://test-id'}
    assert c.get('/api/bridge/info',headers=headers).status_code==200
    assert c.post('/api/bridge/pair',headers=headers,json={'code':'000000'}).status_code in (410,401)
    assert c.put('/api/whatsapp/settings',headers=headers,json={'enabled':False}).status_code==403


def test_oversized_body_rejected_before_parse(env):
    c,g=env
    assert c.post('/api/parse',content=b'x'*(1024*1024+1)).status_code==413


def test_plan_consumption_only_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    main._PLAN_CACHE['security-one-use']={'created_at':time.time()}
    def consume():
        try:main._consume_plan('security-one-use');return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:consume(),range(2)))==[False,True]

@pytest.mark.parametrize('url,tls', [('http://glpi.example',True),('https://user:secret@glpi.example',True),('https://glpi.example',False)])
def test_glpi_refuses_credential_exposure_or_tls_bypass(url,tls):
    from glpi import GlpiConfig,GlpiClient,GlpiError
    with pytest.raises(GlpiError):GlpiClient(GlpiConfig(url=url,user_token='test',verify_tls=tls))


def test_backup_plan_accepts_same_image_size_as_apply(env):
    c,g=env
    g.create_task(1,'Conferir backup',300,1,9,0)
    # The route limit must allow a screenshot larger than the default JSON cap.
    png=b'\x89PNG\r\n\x1a\n'+b'\0'*(1024*1024+100)
    edits=[{'task_id':100,'text':'Conferir backup','files':[0],'complete':True}]
    planned=c.post('/api/templates/plan',data={'ticket_id':1,'edits':json.dumps(edits)},files=[('files',('E01.png',png,'image/png'))])
    assert planned.status_code==200,planned.text
    result=c.post('/api/templates/apply',data={'plan_id':planned.json()['id']},files=[('files',('E01.png',png,'image/png'))])
    assert result.status_code==200,result.text
    assert result.json()['ok']
    assert g.tasks[100]['state']==2


def test_glpi_get_refuses_redirect_response(monkeypatch):
    from glpi import GlpiClient,GlpiConfig,GlpiError
    client=GlpiClient(GlpiConfig(url='https://glpi.example/apirest.php',user_token='test'))
    response=Mock(status_code=302,ok=True)
    response.json.return_value={'redirected':True}
    monkeypatch.setattr(client.http,'get',lambda *a,**kw:response)
    with pytest.raises(GlpiError):client.get('Ticket/1')


@pytest.mark.parametrize('payload',[{}, {'id':2,'status':2}, {'id':1,'status':None}, {'id':1,'status':True}, ['ERROR']])
def test_partial_ticket_response_never_becomes_actionable(monkeypatch,payload):
    from glpi import GlpiClient,GlpiConfig,GlpiError
    client=GlpiClient(GlpiConfig(url='https://glpi.example/apirest.php',user_token='test'))
    monkeypatch.setattr(client,'get',lambda *a,**kw:payload)
    with pytest.raises(GlpiError):client.get_ticket(1)


@pytest.mark.parametrize('status',[403,404])
def test_sanitized_http_errors_preserve_profile_fallback(monkeypatch,status):
    from glpi import GlpiClient,GlpiConfig,_api_error
    client=GlpiClient(GlpiConfig(url='https://glpi.example/apirest.php',user_token='test'))
    response=Mock(status_code=status);response.json.return_value={'private':'not-exposed'}
    err=_api_error(response)
    assert 'not-exposed' not in str(err)
    monkeypatch.setattr(client,'get_ticket',lambda tid:(_ for _ in ()).throw(err))
    assert client._try_ticket(1) is None


def test_entity_activation_failure_blocks_context_use(monkeypatch):
    from glpi import GlpiClient,GlpiConfig,GlpiError
    client=GlpiClient(GlpiConfig(url='https://glpi.example/apirest.php',user_token='test'))
    monkeypatch.setattr(client,'_try_ticket',lambda tid:{'id':1,'status':2,'entities_id':7})
    monkeypatch.setattr(client,'change_active_entity',lambda *a,**kw:(_ for _ in ()).throw(GlpiError('denied',403)))
    with pytest.raises(GlpiError):client.activate_context_for_ticket(1)


def test_proactive_self_only_can_plan_without_waha(env, monkeypatch):
    from contact_policy import self_only_ticket
    c, g = env
    g.tickets[1]['name'] = 'Revisão interna proativa'
    g.tickets[1]['content'] = 'Conferência preventiva dos logs.'
    monkeypatch.setattr(g, 'ticket_users', lambda tid: [{'users_id':9,'type':1}, {'users_id':9,'type':2}])
    assert self_only_ticket(g,g.tickets[1],9)
    monkeypatch.setattr(main,'_resolve_catalog_live',lambda *a:{'id':7,'full_name':'REMOTO'})
    result=c.post('/api/plan',json={'ticket_id':1,'text':closure(),'evidence_map':{}})
    assert result.status_code==200,result.text
    assert result.json()['contact_receipt'] is None
    assert self_only_ticket(g,{**g.tickets[1], 'content':'Contato: (31) 00000-0000'},9) is False
    assert self_only_ticket(g,g.tickets[1],9,[{'users_id':9,'type':1},{'users_id':9,'type':2},{'users_id':10,'type':3}]) is False
    assert self_only_ticket(g,g.tickets[1],9,[{'users_id':9,'type':2}]) is False
    assert self_only_ticket(g,g.tickets[1],9,[{'users_id':9,'type':1}]) is False


def test_proactive_self_only_auto_initial_without_send(env,monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(g,'ticket_users',lambda tid: [{'users_id':9,'type':1},{'users_id':9,'type':2}] if tid==2 else [{'users_id':9,'type':2}])
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda *args,**kwargs:calls.append(args) or {'id':'unexpected'})
    c.put('/api/workbench/settings',json={'enabled':True,'auto_initial':True})
    assert c.put('/api/whatsapp/settings',json={'enabled':True}).status_code==200
    assert c.post('/api/workbench/sync').status_code==200
    g.tickets[2]={**g.tickets[1],'id':2,'name':'Revisão interna proativa','content':'Conferência preventiva dos logs.'}
    g.assigned_ids.add(2)
    response=c.post('/api/workbench/sync')
    assert response.status_code==200,response.text
    assert len(g.followups)==1 and not g.tasks
    assert calls==[]
    assert 'Registro do primeiro contato via WhatsApp' not in next(iter(g.followups.values()))['content']


def test_bridge_handoff_carries_review_only_completion_intent(env):
    from closure_intent import parse_intent
    c, g = env
    set_meta('bridge_token','test-token')
    text='[GLPI_ASSISTANT:1]\n'+closure()+'\n[DESTINO_CHAMADO]\nacao: fechar\nincluir_no_lote: sim\nsolucao: Serviço restaurado e testes locais concluídos.\n[/DESTINO_CHAMADO]'
    result=c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':text})
    assert result.status_code==200,result.text
    assert result.json()['handoff']['intent']=={'target':'close','solution':'Serviço restaurado e testes locais concluídos.','include_in_batch':True}
    assert not g.writes
    assert parse_intent(text.replace('acao: fechar','acao: solucionar').replace('incluir_no_lote: sim','incluir_no_lote: nao'))['target']=='solve'
    for bad in ('[/DESTINO_CHAMADO]', 'acao: desconhecido\nincluir_no_lote: sim\nsolucao: Texto válido o bastante.'):
        changed=text.replace('acao: fechar\nincluir_no_lote: sim\nsolucao: Serviço restaurado e testes locais concluídos.\n[/DESTINO_CHAMADO]', bad)
        assert c.post('/api/bridge/handoff',headers={'Authorization':'Bearer test-token'},json={'ticket_id':1,'closure':changed}).status_code==400


def test_bridge_capture_ack_persists_prompt_scoped_context(env):
    c, _ = env
    set_meta('bridge_token', 'test-token')
    raw = b'\x89PNG\r\n\x1a\n' + (b'\0' * 16)
    data = base64.b64encode(raw).decode()
    digest = hashlib.sha256(raw).hexdigest()

    result = c.post('/api/bridge/captures', headers={'Authorization': 'Bearer test-token'}, json={
        'prompt_id': 'prompt-123',
        'conversation_id': 'https://chatgpt.com/c/example',
        'provider': 'chatgpt',
        'prompt_timestamp': '2026-10-01T11:50:00Z',
        'attachments': [{
            'attachment_id': 'att-1',
            'ordinal': 1,
            'name': 'context.png',
            'type': 'image/png',
            'data': data,
            'digest': digest,
            'role': 'context',
            'state': 'queued',
        }],
    })

    assert result.status_code == 200, result.text
    assert result.json()['attachments'] == [{'attachment_id': 'att-1', 'digest': digest, 'stored': True}]
    stored = get_meta('bridge_capture_prompt-123')
    assert stored['attachments'][0]['digest'] == digest
    assert stored['attachments'][0]['role'] == 'context'
    assert stored['attachments'][0]['path'].endswith(digest)


def test_waha_activation_baselines_before_return_then_sends_new_assignment(env,monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda method,path,payload=None,**kw:calls.append((method,path,payload)) or {'id':'wa-confirmed'})
    g.tickets[1]['content']='Contato: (31) 00000-0000'
    c.put('/api/workbench/settings',json={'enabled':True,'auto_initial':False,'contact_name':'Alex'})
    enabled=c.put('/api/whatsapp/settings',json={'enabled':True})
    assert enabled.status_code==200,enabled.text
    assert c.get('/api/whatsapp').json()['baseline_ready'] is True
    assert not [call for call in calls if call[0]=='POST']
    g.tickets[2]={**g.tickets[1],'id':2}
    g.assigned_ids.add(2)
    assert c.post('/api/workbench/sync').status_code==200
    posts=[call for call in calls if call[0]=='POST']
    assert len(posts)==1 and posts[0][2]['chatId']=='5531000000000@c.us'
    assert c.post('/api/workbench/sync').status_code==200
    assert len([call for call in calls if call[0]=='POST'])==1


def test_waha_retries_preflight_only_after_contact_is_corrected(env,monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda method,path,payload=None,**kw:calls.append(payload) or {'id':'wa-confirmed'})
    c.put('/api/workbench/settings',json={'enabled':True,'auto_initial':False,'contact_name':'Alex'})
    assert c.put('/api/whatsapp/settings',json={'enabled':True}).status_code==200
    g.tickets[2]={**g.tickets[1],'id':2,'name':'Acesso remoto','content':'Contato: sem número'}
    g.assigned_ids.add(2)
    assert c.post('/api/workbench/sync').status_code==200
    assert calls==[]
    import hashlib
    scope=hashlib.sha256(f'{g.base}|9'.encode()).hexdigest()[:24]
    events=get_meta('waha_events_'+scope)
    assert events['2']['status']=='não enviado'
    events['2']['at']-=121
    set_meta('waha_events_'+scope,events)
    g.tickets[2]['content']='Contato: (31) 00000-0000'
    assert c.post('/api/workbench/sync').status_code==200
    assert len(calls)==1, get_meta('waha_events_'+scope)['2'].get('detail')
    assert get_meta('waha_events_'+scope)['2']['status']=='aceito pelo WAHA'
    assert c.post('/api/workbench/sync').status_code==200 and len(calls)==1


def test_waha_enable_fails_closed_when_baseline_unavailable(env,monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    monkeypatch.setattr(g,'get',lambda path,params=None: (_ for _ in ()).throw(RuntimeError('GLPI fora')) if path=='search/Ticket' else Fake.get(g,path,params))
    assert c.put('/api/whatsapp/settings',json={'enabled':True}).status_code==503
    assert c.get('/api/whatsapp').json()['enabled'] is False


@pytest.mark.parametrize('action,final_status', [('fechar', 6), ('solucionar', 5)])
def test_completion_intent_survives_tasks_only_and_offline(env, monkeypatch, action, final_status):
    client, fake = env
    text = closure() + f"\n[DESTINO_CHAMADO]\nacao: {action}\nincluir_no_lote: sim\nsolucao: Atendimento validado e finalizado.\n[/DESTINO_CHAMADO]"
    main._remember_applied(1, text)
    assert not main._already_applied(1, text, parse_closure(text))
    fake.tickets[1]['status'] = final_status
    assert main._already_applied(1, text, parse_closure(text))
    if action == 'fechar':
        fake.tickets[1]['status'] = 5
        assert not main._already_applied(1, text, parse_closure(text))
    monkeypatch.setattr(main, '_client', Mock(side_effect=RuntimeError('offline')))
    assert not main._already_applied(1, text, parse_closure(text))


def test_waha_failed_refresh_never_undoes_concurrent_pause(env, monkeypatch):
    import whatsapp_auto as wa
    c, g = env
    monkeypatch.setattr(wa, 'ready', lambda: {'me': {'id': '5511000000000@c.us'}})
    assert c.put('/api/whatsapp/settings', json={'enabled': True}).status_code == 200
    def unavailable(path, params=None):
        if path == 'search/Ticket':
            paused = wa.config().copy()
            paused['enabled'] = False
            set_meta('waha_settings', paused)
            raise RuntimeError('GLPI fora após pausa')
        return Fake.get(g, path, params)
    monkeypatch.setattr(g, 'get', unavailable)
    assert c.put('/api/whatsapp/settings', json={'enabled': True}).status_code == 503
    assert wa.config()['enabled'] is False


def test_initial_reply_delivery_update_preserves_human_text_and_deduplicates_t01(env):
    c, g = env
    c.post('/api/workbench/sync')
    g.tickets[2] = {**g.tickets[1], 'id': 2, 'content': 'Erro <script>alert(1)</script>'}
    g.assigned_ids.add(2)
    c.post('/api/workbench/sync')
    reply = next(iter(g.followups.values()))
    assert '<script>' not in reply['content']
    reply['content'] += '<p>Texto literal: &lt;script&gt;</p>'
    reply['content'] += '<p>Complemento escrito pelo técnico.</p>'
    c.put('/api/workbench/settings', json={'auto_initial': False})
    delivered_contact(g, 2)
    c.post('/api/workbench/sync')
    assert 'Complemento escrito pelo técnico.' in reply['content']
    assert '<script>' not in reply['content']
    # Task and follow-up IDs occupy separate GLPI namespaces.
    g.tasks[reply['id']] = {'id': reply['id'], 'tickets_id': 2, 'content': '<!-- glpi-assistant:3.3.6:T02 -->Teste'}
    missing, skipped = main._partition_incoming_tasks(parse_closure(closure((1, 2, 3)))['tasks'], main._existing_task_candidates(g, 2))
    assert [t['id'] for t in missing] == ['T03']
    assert {s['existing_resource'] for s in skipped} == {'ITILFollowup', 'TicketTask'}
    c.post('/api/workbench/sync')
    assert len(g.followups) == 1 and len(g.writes) == 2


def test_initial_reply_precedes_uncertain_whatsapp_send(env, monkeypatch):
    import whatsapp_auto as wa
    c, g = env
    c.put('/api/workbench/settings', json={'enabled':True, 'auto_initial':True, 'contact_name':'Alex'})
    monkeypatch.setattr(wa, 'ready', lambda: {'me':{'id':'5511000000000@c.us'}})
    c.put('/api/whatsapp/settings', json={'enabled':True})
    g.tickets[2] = {**g.tickets[1], 'id':2, 'content':'Contato: (31) 00000-0000'}
    g.assigned_ids.add(2)
    def fail_send(*args):
        assert len(g.followups) == 1, 'Public reply must already exist when WhatsApp starts sending'
        raise TimeoutError('simulated')
    monkeypatch.setattr(wa, 'api', fail_send)
    assert c.post('/api/workbench/sync').status_code == 200
    assert len(g.followups) == 1 and not g.tasks
    assert 'Entrega ao aparelho confirmada' not in next(iter(g.followups.values()))['content']


@pytest.mark.parametrize('event', [None, {'status':'resultado incerto'}, {'status':'não enviado'}, {'status':'aceito pelo WAHA','message_id':'pending-id','delivery_ack':1}])
def test_plan_unblocked_without_whatsapp_delivery(env, monkeypatch, event):
    import hashlib
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(main,'_resolve_catalog_live',lambda *a:{'id':7,'full_name':'REMOTO'})
    monkeypatch.setattr(main,'_apply_ticket_changes',lambda *a:None)
    original=g.create_task
    monkeypatch.setattr(g,'create_task',lambda **kw:original(kw['ticket_id'],kw['content'],kw['actiontime'],kw['state'],kw['tech_user_id'],kw['group_id']))
    scope=hashlib.sha256(f'{g.base}|9'.encode()).hexdigest()[:24]
    set_meta('waha_settings', {'enabled':True,'generation':'test'})
    if event: set_meta('waha_events_'+scope, {'1':{'ticket_id':1,'at':time.time(),**event}})
    monkeypatch.setattr(wa,'api',lambda *args:pytest.fail('Review must not contact WAHA'))
    response=c.post('/api/plan',json={'ticket_id':1,'text':closure().replace('00:00','00:02'),'evidence_map':{}})
    assert response.status_code==200,response.text
    assert response.json()['contact_receipt'] is None
    assert response.json()['has_actionable_operations'] is True
    applied=c.post('/api/execute',data={'ticket_id':'1','text':closure().replace('00:00','00:02'),'evidence_map':'{}','plan_id':response.json()['plan_id']})
    assert applied.status_code==200 and applied.json()['ok'],applied.text
    planned=c.post('/api/workbench/solution/plan',json={'items':[{'ticket_id':1,'content':'Problema corrigido e funcionamento validado.'}],'target':'close'})
    assert planned.status_code==200,planned.text
    finished=c.post('/api/workbench/solution/apply',json={'plan_id':planned.json()['plan_id']})
    assert finished.status_code==200 and finished.json()['ok'],finished.text
    assert g.tickets[1]['status']==6


def test_proactive_new_assignment_suppresses_initial_reply_and_waha(env,monkeypatch):
    import whatsapp_auto as wa
    c,g=env
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    calls=[]
    monkeypatch.setattr(wa,'api',lambda method,path,payload=None,**kw:calls.append((method,path,payload)) or {'id':'wa-confirmed'})
    c.put('/api/workbench/settings',json={'enabled':True,'auto_initial':True,'contact_name':'Alex'})
    assert c.put('/api/whatsapp/settings',json={'enabled':True}).status_code==200
    g.tickets[2]={**g.tickets[1],'id':2,'content':'Contato: (31) 00000-0000 [GLPI_PROACTIVE:'+'a'*32+']'}
    g.assigned_ids.add(2)
    assert c.post('/api/workbench/sync').status_code==200
    assert not g.followups
    assert not [call for call in calls if call[0]=='POST']
    assert c.post('/api/workbench/sync').status_code==200
    assert not g.followups
