import copy
import importlib
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'package/usr/lib/glpi-assistant/app'))
import whatsapp_auto as wa

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(wa,'resolve_chat_id',lambda phone:phone+'@c.us')
    data={'waha_settings':{'enabled':True,'generation':'g1','account':'5511000000000@c.us'}}
    monkeypatch.setattr(wa,'get_meta',lambda key,default=None:copy.deepcopy(data.get(key,default)))
    monkeypatch.setattr(wa,'set_meta',lambda key,value:data.__setitem__(key,copy.deepcopy(value)))
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'5511000000000@c.us'}})
    return data

def test_activation_and_reactivation_exclude_existing_queue(db):
    assert not wa.begin_scan('a',[1,2])
    assert wa.begin_scan('a',[1,2,3])=={3:'g1'}
    db['waha_settings']['generation']='g2'
    assert not wa.begin_scan('a',[1,2,3,4])
    assert wa.begin_scan('a',[1,2,3,4,5])=={5:'g2'}
    assert not wa.begin_scan('other',[1,2,3,4,5])

def test_reservation_before_post_and_no_resend_after_restart(db,monkeypatch):
    calls=[]
    def send(method,path,payload):
        assert db['waha_events_a']['1']['status']=='resultado incerto'
        calls.append(payload)
        return {'id':'message1'}
    monkeypatch.setattr(wa,'api',send)
    prepare=lambda:('5511000000001','Olá #1')
    wa.process('a',1,prepare,'g1')
    # Reloading the module models process restart, retaining persisted meta.
    importlib.reload(wa)
    monkeypatch.setattr(wa,'get_meta',lambda k,d=None:copy.deepcopy(db.get(k,d)))
    monkeypatch.setattr(wa,'set_meta',lambda k,v:db.__setitem__(k,copy.deepcopy(v)))
    monkeypatch.setattr(wa,'api',send)
    wa.process('a',1,prepare,'g1')
    assert len(calls)==1
    assert db['waha_events_a']['1']['status']=='aceito pelo WAHA'
    assert 'message' not in db['waha_events_a']['1']

def test_timeout_never_retries(db,monkeypatch):
    calls=[]
    def fail(*a):calls.append(a);raise TimeoutError()
    monkeypatch.setattr(wa,'api',fail)
    for _ in range(2):wa.process('a',2,lambda:('5511000000001','msg'),'g1')
    assert len(calls)==1
    assert db['waha_events_a']['2']['status']=='resultado incerto'

def test_changed_assignment_or_ambiguous_recipient_blocks_post(db,monkeypatch):
    monkeypatch.setattr(wa,'api',lambda *a:pytest.fail('Must not send'))
    def prepare():raise ValueError('Atribuição alterada')
    wa.process('a',3,prepare,'g1')
    assert db['waha_events_a']['3']['status']=='não enviado'

def test_pause_generation_race_and_changed_account(db,monkeypatch):
    monkeypatch.setattr(wa,'api',lambda *a:pytest.fail('Must not send'))
    prepare=lambda:('5511000000001','msg')
    wa.process('a',4,prepare,'old-generation')
    assert 'waha_events_a' not in db
    db['waha_settings']['enabled']=False
    wa.process('a',4,prepare,'g1')
    assert 'waha_events_a' not in db
    db['waha_settings']['enabled']=True
    monkeypatch.setattr(wa,'ready',lambda:{'me':{'id':'other'}})
    wa.process('a',4,prepare,'g1')
    assert db['waha_events_a']['4']['status']=='não enviado'

def test_literal_template_substitution():
    value=wa.render('{saudacao}, {nome}. Sou {tecnico}, #{chamado} — {assunto}',{
        'nome':'{tecnico}', 'tecnico':'Alex','chamado':42,'assunto':'VPN','empresa':'Exemplo'},'America/Sao_Paulo')
    assert '{tecnico}' in value
    assert 'Sou Alex, #42 — VPN' in value


def test_first_contact_receipt_uses_real_id_and_escapes_content(db,monkeypatch):
    import hashlib
    scope=hashlib.sha256(b'https://example|9').hexdigest()[:24]
    monkeypatch.setattr(wa,'api',lambda *a:{'id':'real-message-id','fromMe':True,'body':'Olá <script> #4','ack':2,'ackName':'DEVICE'})
    wa.process(scope,4,lambda:('5511000000001','Olá <script> #4'),'g1')
    receipt=wa.first_contact_receipt('https://example',9,4)
    assert receipt['message_id']=='real-message-id'
    html=wa.receipt_html(receipt)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'Entrega ao aparelho confirmada' in html
    with pytest.raises(ValueError,match='sem comprovante'):
        wa.first_contact_receipt('https://other',9,4)


def test_uncertain_contact_cannot_be_reported_as_sent(db,monkeypatch):
    import hashlib
    scope=hashlib.sha256(b'https://example|9').hexdigest()[:24]
    monkeypatch.setattr(wa,'api',lambda *a:(_ for _ in ()).throw(TimeoutError()))
    wa.process(scope,4,lambda:('5511000000001','Olá #4'),'g1')
    with pytest.raises(ValueError,match='sem confirmação'):
        wa.first_contact_receipt('https://example',9,4)

@pytest.mark.parametrize('ack,confirmed', [(-1,False),(0,False),(1,False),(2,True),(3,True),(4,True)])
def test_delivery_gate_exact_message_and_stops_after_confirmation(db,monkeypatch,ack,confirmed):
    import hashlib
    scope=hashlib.sha256(b'https://example|9').hexdigest()[:24]
    calls=[]
    def response(method,path,payload=None):
        calls.append((method,path))
        return {'id':'true_5511000000001@c.us_ABC','fromMe':True,'body':'Olá #4','ack':ack,'ackName':wa.ACK_NAMES[ack]}
    monkeypatch.setattr(wa,'api',response)
    wa.process(scope,4,lambda:('5511000000001','Olá #4'),'g1')
    if confirmed:
        receipt=wa.first_contact_receipt('https://example',9,4)
        assert receipt['ack']==ack
        count=len(calls)
        wa.first_contact_receipt('https://example',9,4)
        assert len(calls)==count, 'Delivery proof must stop polling'
    else:
        with pytest.raises(ValueError,match='aguardando entrega'):
            wa.first_contact_receipt('https://example',9,4)
    assert len([x for x in calls if x[0]=='POST'])==1
    reads=[x[1] for x in calls if x[0]=='GET']
    assert reads==['/api/default/chats/5511000000001%40c.us/messages/true_5511000000001%40c.us_ABC?downloadMedia=false']

@pytest.mark.parametrize('wrong', [{'id':'other'}, {'fromMe':False}, {'body':'outra mensagem'}, {'ack':True}, {'ackName':'DEVICE','ack':0}, {'to':'other@c.us'}])
def test_forged_or_mismatched_receipts_rejected(db,monkeypatch,wrong):
    import hashlib
    scope=hashlib.sha256(b'https://example|9').hexdigest()[:24]
    monkeypatch.setattr(wa,'api',lambda *a:{'id':'msg'})
    wa.process(scope,4,lambda:('5511000000001','Olá #4'),'g1')
    monkeypatch.setattr(wa,'api',lambda *a:{'id':'msg','fromMe':True,'body':'Olá #4','ack':2,'ackName':'DEVICE',**wrong})
    with pytest.raises(ValueError):wa.first_contact_receipt('https://example',9,4)


def test_delivery_window_expires_without_any_read_or_resend(db,monkeypatch):
    import hashlib
    scope=hashlib.sha256(b'https://example|9').hexdigest()[:24]
    monkeypatch.setattr(wa,'api',lambda *a:{'id':'msg'})
    wa.process(scope,4,lambda:('5511000000001','Olá #4'),'g1')
    db['waha_events_'+scope]['4']['at']-=601
    monkeypatch.setattr(wa,'api',lambda *a:pytest.fail('No network after automatic window'))
    with pytest.raises(ValueError,match='10 minutos'):wa.first_contact_receipt('https://example',9,4)


def test_pending_new_assignment_survives_scan_before_attempt(db):
    assert not wa.begin_scan('a',[1])
    assert wa.begin_scan('a',[1,2])=={2:'g1'}
    assert wa.begin_scan('a',[1,2])=={2:'g1'}

@pytest.mark.parametrize('method,path',[('GET','/api/default/chats'),('POST','/api/sendImage'),('POST','/api/media/convert'),('GET','http://evil.example'),('GET','/api/default/chats/x/messages/y?downloadMedia=true')])
def test_unnecessary_waha_routes_blocked_before_credentials(method,path):
    with pytest.raises(ValueError,match='não permitida'):wa.api(method,path)


@pytest.mark.parametrize('result,expected', [
    ({'numberExists':True,'chatId':'5500999990000@c.us'}, '5500999990000@c.us'),
    ({'numberExists':True,'chatId':'550099990000@c.us'}, '550099990000@c.us'),
    ({'numberExists':True,'chatId':'1234567890123@lid','pn':'550099990000@c.us'}, '1234567890123@lid'),
    ({'numberExists':False}, None),
    ({'numberExists':True,'chatId':'5500888880000@c.us'}, None),
    ({'numberExists':True,'chatId':'1234567890123@lid'}, None),
    ({'numberExists':True,'chatId':'5500999990000@g.us'}, None),
])
def test_resolve_recipient_without_guessing(monkeypatch, result, expected):
    calls=[]
    monkeypatch.setattr(wa,'api',lambda *args: calls.append(args) or result)
    if expected:
        assert wa.resolve_chat_id('5500999990000') == expected
    else:
        with pytest.raises(ValueError): wa.resolve_chat_id('5500999990000')
    expected_calls = [('GET','/api/contacts/check-exists?phone=5500999990000&session=default')]
    if result.get('chatId', '').endswith('@lid') and result.get('pn') is None:
        expected_calls.append(('GET','/api/default/lids/1234567890123'))
    assert calls == expected_calls


@pytest.mark.parametrize('error,code', [('http','HTTP_422'),('timeout','TIMEOUT'),('connection','CONNECTION'),('invalid','INVALID_RESPONSE')])
def test_send_diagnostic_preserves_cause_without_secrets(db, monkeypatch, error, code):
    error={'http':wa.WahaAPIError(422),'timeout':TimeoutError('SECRET'),'connection':ConnectionError('SECRET'),'invalid':ValueError('SECRET')}[error]
    monkeypatch.setattr(wa,'api',lambda *args: (_ for _ in ()).throw(error))
    wa.process('diag',1,lambda:('5531000000000','Olá #1'),'g1')
    event=db['waha_events_diag']['1']
    assert event['status']=='resultado incerto' and event['error_code']==code
    assert 'SECRET' not in event['detail']


@pytest.mark.parametrize('mapping,ok', [
    ({'lid':'900000000000001@lid','pn':'550099000111@c.us'}, True),
    ({'lid':'900000000000001@lid','pn':'5500999000111@c.us'}, True),
    ({'lid':'900000000000001@lid','pn':'5500999999999@c.us'}, False),
    ({'lid':'900000000000002@lid','pn':'550099000111@c.us'}, False),
    ({'lid':'900000000000001@lid','pn':None}, False),
    ([], False),
])
def test_lid_lookup_matches_exact_recipient(monkeypatch, mapping, ok):
    calls=[]
    def api(method, path):
        calls.append((method,path))
        return {'numberExists':True,'chatId':'900000000000001@lid'} if len(calls)==1 else mapping
    monkeypatch.setattr(wa,'api',api)
    if ok:
        assert wa.resolve_chat_id('550099000111') == '900000000000001@lid'
    else:
        with pytest.raises(ValueError): wa.resolve_chat_id('550099000111')
    assert calls == [('GET','/api/contacts/check-exists?phone=550099000111&session=default'),('GET','/api/default/lids/900000000000001')]

@pytest.mark.parametrize('path', ['/api/default/lids', '/api/default/lids/12345?all=true', '/api/other/lids/12345', '/api/default/lids/../contacts'])
def test_lid_route_does_not_allow_broad_queries(path):
    with pytest.raises(ValueError, match='não permitida'): wa.api('GET',path)


def test_old_ticket_disappears_and_returns_is_not_new(db):
    wa.begin_scan('a',[1,2])
    wa.begin_scan('a',[2])
    assert not wa.begin_scan('a',[1,2])

def test_resume_discards_old_pending_and_retryable(db):
    wa.begin_scan('a',[1])
    assert wa.begin_scan('a',[1,2]) == {2:'g1'}
    db['waha_events_a']={'2':{'ticket_id':2,'generation':'g1','status':'não enviado','at':0}}
    wa.reset_monitor_baseline()
    assert not wa.begin_scan('a',[1,2])
    assert not wa.begin_scan('a',[1,2])
    assert set(wa.begin_scan('a',[1,2,3])) == {3}

def test_prior_manual_send_prevents_automatic_first_contact(db, monkeypatch):
    wa.begin_scan('a',[1])
    db['waha_events_a']={'resume:x':{'ticket_id':2,'status':'aceito pelo WAHA','message_id':'already'}}
    assert not wa.begin_scan('a',[1,2])
    monkeypatch.setattr(wa,'api',lambda *a:pytest.fail('duplicate send'))
    wa.process('a',2,lambda:('5511000000001','hello'),'g1')

def test_upgrade_baselines_existing_queue(db):
    db['waha_seen_a']={'generation':'g1','ids':[1],'pending':[2]}
    assert not wa.begin_scan('a',[1,2,3])
    assert not wa.begin_scan('a',[1,2,3])
