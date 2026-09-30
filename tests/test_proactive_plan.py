from test_proactive_contract import contract,draft
import pytest

def test_entity_not_inherited_and_requester_is_self():
    import proactive
    raw=draft(); calls=[]
    def resolve(kind,q,entity):
        calls.append((kind,q,entity))
        return {'id':7 if kind=='Entity' else 9,'name':q}
    p=proactive.build_proactive_plan(raw,'2026-09-30T00:12:22-03:00',resolve,42,'u1','America/Sao_Paulo',{'E01':{'hash':'abc'}})
    assert p['input']['entities_id']==7
    assert p['input']['_users_id_requester']==42
    assert p['input']['date']=='2026-09-30 00:12:22'
    assert calls[1]==('ITILCategory','Documentação',7)

def test_ambiguous_entity_blocks_creation():
    import proactive
    def resolve(*args): raise ValueError('ambíguo')
    p=proactive.build_proactive_plan(draft(),'2026-09-30T00:12:22-03:00',resolve,42,'u1','America/Sao_Paulo',{})
    assert any(x.startswith('entity:') for x in p['pending_fields'])

def test_marker_identifies_proactive_for_monitor():
    import proactive
    assert proactive.is_proactive({'content':'<p>[GLPI_PROACTIVE:'+'a'*32+']</p>'})
    assert not proactive.is_proactive({'content':'Chamado comum'})
