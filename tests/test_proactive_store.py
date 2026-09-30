import importlib.util
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'package/usr/lib/glpi-assistant/app'))

def test_operation_survives_restart_and_deduplicates(tmp_path):
    assert importlib.util.find_spec('proactive_store'), 'Persistência ainda não implementada'
    import proactive_store as s
    db=tmp_path/'proactive.db'
    a=s.save_operation({'scope':'user1','draft_ref':'P01','digest':'abc'},db)
    b=s.save_operation({'scope':'user1','draft_ref':'P01','digest':'abc'},db)
    assert a['operation_id']==b['operation_id']
    s.update_operation(a['operation_id'],{'ticket_id':42,'status':'partial'},db)
    assert s.get_operation(a['operation_id'],db)['ticket_id']==42
