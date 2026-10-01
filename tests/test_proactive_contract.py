import sys
import json
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'package/usr/lib/glpi-assistant/app'))

def contract():
    import importlib.util
    assert importlib.util.find_spec('proactive_contract'), 'Contrato de proativos ainda não implementado'
    import proactive_contract
    return proactive_contract

def draft(ref='P01'):
    return {'schema_version':1,'operation':'create_proactive','draft_ref':ref,'title':'Inventário','description':'Documentar equipamento','entity':'Aurora Labs (example)','category':'Documentação','priority':3,'tasks':[{'id':'T01','title':'Registro','content':'Dados registrados','evidence_ids':['E01']}], 'evidence':[{'id':'E01','source_index':1,'role':'evidence'}]}

def test_multiple_proactives_keep_evidence_scoped():
    c=contract(); text='[GLPI_PROACTIVE]\n'+json.dumps([draft(),draft('P02')])+'\n[/GLPI_PROACTIVE]'
    assert [d['draft_ref'] for d in c.parse_proactive_blocks(text)]==['P01','P02']

def test_timestamp_is_prompt_time():
    c=contract(); d=c.normalize_proactive(draft(),'2026-09-30T00:12:22-03:00')
    assert d['prompt_timestamp']=='2026-09-30T00:12:22-03:00'
    assert d['type']==2

@pytest.mark.parametrize('timestamp',[None,'2026-09-30T00:12:22'])
def test_missing_offset_is_pending(timestamp):
    assert 'prompt_timestamp' in contract().normalize_proactive(draft(),timestamp)['pending_fields']

def test_high_priority_requires_explicit_choice():
    d=draft(); d['priority']=4
    assert 'priority_authorization' in contract().normalize_proactive(d,'2026-09-30T00:12:22-03:00')['pending_fields']

def test_variable_task_count():
    d=draft(); d['tasks'] += [{'id':'T02','title':'Validação','content':'Conferido'}]
    assert len(contract().normalize_proactive(d,'2026-09-30T00:12:22-03:00')['tasks'])==2

def test_duplicate_refs_rejected():
    with pytest.raises(ValueError,match='referência'):
        contract().parse_proactive_blocks('[GLPI_PROACTIVE]'+json.dumps([draft(),draft()])+'[/GLPI_PROACTIVE]')
