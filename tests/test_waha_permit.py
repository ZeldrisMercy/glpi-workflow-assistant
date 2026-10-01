import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'package/usr/lib/glpi-assistant/app'))
from waha_permit import sign_permit
import whatsapp_auto as wa

BODY = {'session': 'default', 'chatId': '900000000000001@lid', 'text': 'Olá 👋 #123', 'linkPreview': False}
OP = {'scope': 'a' * 24, 'ticket': 123, 'kind': 'first', 'operation': 'first'}
CFG = {'restricted_profile': 2, 'permit_key': 'ab' * 32, 'api_key': 'client-key-' * 4}


def test_signature_matches_exact_utf8_and_scope():
    token = sign_permit(CFG, BODY, OP, now=100)['X-Assistant-Permit']
    encoded, signature = token.split('.')
    assert hmac.compare_digest(signature, hmac.new(bytes.fromhex(CFG['permit_key']), encoded.encode(), hashlib.sha256).hexdigest())
    claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    assert claims['text_sha256'] == hashlib.sha256(BODY['text'].encode()).hexdigest()
    assert claims['chat'] == BODY['chatId'] and claims['exp'] == 190 and claims['ticket'] == 123


@pytest.mark.parametrize('operation', [None, {}, {**OP, 'ticket': True}, {**OP, 'scope': 'bad'}, {**OP, 'kind': 'resume', 'operation': 'first'}])
def test_invalid_context_fails_before_transport(operation):
    with pytest.raises(ValueError): sign_permit(CFG, BODY, operation)


def test_existing_installation_unchanged():
    assert sign_permit({'api_key': 'legacy'}, BODY, None) == {}


def test_transport_strips_private_metadata_and_signs_only_send(tmp_path, monkeypatch):
    (tmp_path / 'waha.json').write_text(json.dumps(CFG))
    monkeypatch.setattr(wa, 'DATA_DIR', tmp_path)
    calls = []
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, url, **kwargs):
            calls.append(kwargs)
            class Response:
                status_code = 200
                def json(self): return {'id': 'test-message'}
            return Response()
    monkeypatch.setattr(wa.requests, 'Session', Session)
    wa.api('POST', '/api/sendText', {**BODY, '_assistant_operation': OP})
    assert calls[0]['json'] == BODY
    assert 'X-Assistant-Permit' in calls[0]['headers']
    assert CFG['permit_key'] not in str(calls[0])
    wa.api('GET', '/api/sessions/default')
    assert 'X-Assistant-Permit' not in calls[1]['headers']
    with pytest.raises(ValueError): wa.api('POST', '/api/sendText', BODY)
    assert len(calls) == 2
