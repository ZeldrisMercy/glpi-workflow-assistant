"""Short-lived send authorization for the optional WAHA restricted profile v2."""
import base64
import hashlib
import hmac
import json
import re
import time


def sign_permit(settings, payload, operation, now=None):
    if settings.get('restricted_profile') != 2:
        return {}
    key = settings.get('permit_key', '')
    if not re.fullmatch(r'[a-f0-9]{64}', key) or not isinstance(operation, dict):
        raise ValueError('Autorização WAHA ausente; envio bloqueado antes da conexão.')
    scope, ticket, kind, request = (operation.get(k) for k in ('scope', 'ticket', 'kind', 'operation'))
    if not isinstance(scope, str) or not re.fullmatch(r'[a-f0-9]{24}', scope) or type(ticket) is not int or ticket <= 0 or kind not in ('first', 'resume'):
        raise ValueError('Contexto de envio inválido.')
    if (kind == 'first' and request != 'first') or (kind == 'resume' and (not isinstance(request, str) or not re.fullmatch(r'[a-f0-9-]{36}', request))):
        raise ValueError('Identificador de envio inválido.')
    now = int(time.time()) if now is None else now
    claims = {'v': 1, 'iat': now, 'exp': now + 90, 'scope': scope, 'ticket': ticket,
              'kind': kind, 'operation': request, 'session': payload['session'], 'chat': payload['chatId'],
              'text_sha256': hashlib.sha256(payload['text'].encode('utf-8')).hexdigest()}
    encoded = base64.urlsafe_b64encode(json.dumps(claims, separators=(',', ':')).encode()).rstrip(b'=').decode()
    signature = hmac.new(bytes.fromhex(key), encoded.encode(), hashlib.sha256).hexdigest()
    return {'X-Assistant-Permit': encoded + '.' + signature}
