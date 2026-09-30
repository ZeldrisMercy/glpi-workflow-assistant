import importlib.util
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'package/usr/lib/glpi-assistant/app'))

class Remote:
    def __init__(self): self.tickets={}; self.posts=0
    def post(self,path,payload):
        self.posts+=1
        self.tickets[42]={'id':42,**payload['input']}
        raise TimeoutError('Resposta perdida depois de criar')
    def find_proactive(self,marker,entity):
        return [t for t in self.tickets.values() if marker in t['content'] and t['entities_id']==entity]
    def get_ticket(self,tid): return self.tickets[tid]
    def change_active_entity(self,*a,**kw): pass
    def ticket_tasks(self,tid): return []

def test_creation_timeout_never_posts_twice(tmp_path):
    assert importlib.util.find_spec('proactive'), 'Executor ainda não implementado'
    import proactive as p
    import proactive_store as s
    db=tmp_path/'state.db'; g=Remote()
    plan={'scope':'u1','draft_ref':'P01','digest':'abc','input':{'name':'Inventário','content':'Descrição','entities_id':3,'type':2,'priority':3,'status':2},'draft':{'tasks':[],'target':'active','evidence':[]},'user_id':1}
    op=s.save_operation(plan,db)
    first=p.execute_operation(g,op['operation_id'],db)
    assert first['status']=='uncertain'
    second=p.execute_operation(g,op['operation_id'],db)
    assert second['ticket_id']==42 and second['status']=='completed'
    assert g.posts==1

def test_server_actor_mismatch_does_not_claim_complete(tmp_path):
    import proactive as p
    import proactive_store as s
    class G(Remote):
        def post(self,path,payload):self.tickets[42]={'id':42,**payload['input']};return {'id':42}
        def ticket_users(self,tid):return []
    g=G();db=tmp_path/'actors.db'
    plan={'scope':'u1','draft_ref':'P01','digest':'abc','input':{'name':'x','content':'y','entities_id':3,'status':2,'_users_id_requester':1,'_users_id_assign':1},'draft':{'tasks':[],'target':'active','evidence':[]},'user_id':1}
    result=p.execute_operation(g,s.save_operation(plan,db)['operation_id'],db)
    assert result['status']=='partial'
    assert 'atores' in result['error']

def test_evidence_is_inline_in_its_task(tmp_path):
    import proactive as p
    import proactive_store as s
    class G(Remote):
        def __init__(self):super().__init__();self.tasks={}
        def post(self,path,payload):self.tickets[42]={'id':42,**payload['input']};return {'id':42}
        def create_task(self,tid,content,*args):self.tasks[11]=content;return 11
        def upload_document(self,path,entity):return {'id':22}
        def link_document_to_task(self,doc,task):return 33
        def update_task_content(self,task,content):self.tasks[task]=content
        def ticket_task(self,task):return {'id':task,'content':self.tasks[task]}
    g=G();db=tmp_path/'images.db'
    task={'id':'T01','content':'feito','actiontime':0,'evidence_ids':['E01']}
    plan={'scope':'u1','draft_ref':'P01','digest':'abc','input':{'name':'x','content':'y','entities_id':3,'status':2},'draft':{'tasks':[task],'target':'active','evidence':[{'id':'E01'}]},'images':{'E01':{'path':str(tmp_path/'img.png')}},'user_id':1}
    result=p.execute_operation(g,s.save_operation(plan,db)['operation_id'],db)
    assert result['status']=='completed',result
    assert 'docid=22' in g.tasks[11]
    assert '<img ' in g.tasks[11]

def test_server_priority_override_is_visible_as_partial(tmp_path):
    import proactive as p
    import proactive_store as s
    class G(Remote):
        def post(self,path,payload):self.tickets[42]={'id':42,**payload['input'],'priority':4};return {'id':42}
    plan={'scope':'u1','draft_ref':'P01','digest':'abc','input':{'name':'x','content':'y','entities_id':3,'status':2,'priority':3},'draft':{'tasks':[],'target':'active','evidence':[]},'user_id':1}
    db=tmp_path/'rule.db';g=G();result=p.execute_operation(g,s.save_operation(plan,db)['operation_id'],db)
    assert result['status']=='partial'
    assert 'priority' in result['error']


def test_task_timeout_reconciles_without_recreation(tmp_path):
    import proactive as p
    import proactive_store as s
    class G(Remote):
        def __init__(self):super().__init__();self.tasks=[];self.task_posts=0
        def post(self,path,payload):self.tickets[42]={'id':42,**payload['input']};return {'id':42}
        def create_task(self,tid,content,*args):
            self.task_posts+=1;self.tasks.append({'id':11,'content':content})
            raise TimeoutError('Resposta da tarefa perdida')
        def ticket_tasks(self,tid):return self.tasks
    g=G();db=tmp_path/'task.db'
    plan={'scope':'u1','draft_ref':'P01','digest':'abc','input':{'name':'x','content':'y','entities_id':3,'status':2},'draft':{'tasks':[{'id':'T01','content':'Atividade feita','actiontime':0,'evidence_ids':[]}],'target':'active','evidence':[]},'user_id':1}
    op=s.save_operation(plan,db)
    assert p.execute_operation(g,op['operation_id'],db)['status']=='partial'
    assert p.execute_operation(g,op['operation_id'],db)['status']=='completed'
    assert g.task_posts==1
