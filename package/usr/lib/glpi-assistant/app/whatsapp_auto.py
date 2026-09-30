"""Local WAHA integration. Persistent at-most-once attempt per scope/ticket.
No automatic retry after a possibly committed POST; never infer delivery from acceptance.
"""
import json
import secrets
import threading
import time
import re
from urllib.parse import quote
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from uuid import UUID
from store import DATA_DIR, get_meta, set_meta
from contact_template import validate_contact_template

LOCK = threading.RLock()
BASE = 'http://127.0.0.1:3000'


class WahaAPIError(ValueError):
    def __init__(self, status_code):
        self.status_code = status_code
        hints = {
            401: 'Chave de acesso recusada. A configuração do Assistant não corresponde ao WAHA.',
            403: 'Acesso recusado pelo WAHA. Confira a configuração de autenticação local.',
            404: 'Sessão ou recurso não encontrado no WAHA.',
            409: 'A sessão já existe ou está mudando de estado. Atualize o status antes de tentar novamente.',
            422: 'O WAHA recusou a operação no estado atual da sessão. Atualize o status.',
        }
        super().__init__(f"WAHA HTTP {status_code}: " + hints.get(status_code, 'O serviço retornou erro. Confira os logs locais do container.'))


def config():
    return get_meta('waha_settings', {}) or {}


def api(method, path, payload=None, image=False):
    allowed = {
        ('GET', '/api/sessions/default'), ('GET', '/api/sessions?all=true'),
        ('POST', '/api/sessions'), ('POST', '/api/sessions/default/start'),
        ('POST', '/api/sessions/default/restart'),
        ('GET', '/api/default/auth/qr'), ('POST', '/api/sendText'),
    }
    message_read = method == 'GET' and re.fullmatch(r'/api/default/chats/[A-Za-z0-9%._-]+/messages/[A-Za-z0-9%._-]+\?downloadMedia=false', path)
    contact_read = method == 'GET' and re.fullmatch(r'/api/contacts/check-exists\?phone=55[0-9]{10,11}&session=default', path)
    lid_read = method == 'GET' and re.fullmatch(r'/api/default/lids/[0-9]{5,20}', path)
    if (method, path) not in allowed and not message_read and not contact_read and not lid_read:
        raise ValueError('Rota WAHA não permitida nesta integração.')
    operation = payload.get('_assistant_operation') if isinstance(payload, dict) else None
    if method == 'POST' and path == '/api/sendText':
        if not isinstance(payload, dict) or payload.get('session') != 'default' or not re.fullmatch(r'(?:[0-9]{10,15}@c\.us|[0-9]{5,20}@lid)', str(payload.get('chatId', ''))) or not isinstance(payload.get('text'), str) or not 1 <= len(payload['text']) <= 4000:
            raise ValueError('Mensagem ou destinatário inválido.')
        payload = {key: payload[key] for key in ('session', 'chatId', 'text')}
        payload['linkPreview'] = False
    try:
        transport_settings = json.loads((DATA_DIR / 'waha.json').read_text())
        key = transport_settings['api_key']
    except (OSError, ValueError, KeyError):
        raise ValueError('Instale o WAHA local pelo instalador incluído no pacote.')
    permit_headers = {}
    if method == 'POST' and path == '/api/sendText':
        from waha_permit import sign_permit
        permit_headers = sign_permit(transport_settings, payload, operation)
    # Fixed loopback target, no redirects, no proxy inheritance or automatic retries.
    with requests.Session() as session:
        session.trust_env = False
        try:
            r = session.request(method, BASE + path, json=payload,
                                headers={'X-Api-Key': key, 'Accept': 'image/png' if image else 'application/json', **permit_headers},
                                timeout=(3, 60 if method == 'POST' and path == '/api/sendText' else 15), allow_redirects=False)
        except requests.exceptions.Timeout:
            raise TimeoutError('WAHA não respondeu dentro do prazo.') from None
        except requests.exceptions.ConnectionError:
            raise ConnectionError('WAHA local indisponível.') from None
    if not 200 <= r.status_code < 300:
        raise WahaAPIError(r.status_code)
    if image:
        if not r.content.startswith(b'\x89PNG\r\n\x1a\n') or len(r.content) > 2_000_000:
            raise ValueError('WAHA não retornou um QR Code PNG válido.')
        return r.content
    return r.json()


def resolve_chat_id(phone):
    if not re.fullmatch(r'55[0-9]{10,11}', phone):
        raise ValueError('Telefone brasileiro incompleto; confira DDD e número.')
    result = api('GET', '/api/contacts/check-exists?phone=' + phone + '&session=default')
    if not isinstance(result, dict) or result.get('numberExists') is not True:
        raise ValueError('WAHA não confirmou WhatsApp para o telefone informado. Nenhuma mensagem enviada.')
    chat = result.get('chatId')
    if not isinstance(chat, str) or not re.fullmatch(r'(?:[0-9]{10,15}@c\.us|[0-9]{5,20}@lid)', chat):
        raise ValueError('Identificador de conversa não reconhecido; envio bloqueado.')
    pn = chat if chat.endswith('@c.us') else result.get('pn')
    if chat.endswith('@lid') and pn is None:
        mapping = api('GET', '/api/default/lids/' + chat.split('@', 1)[0])
        if not isinstance(mapping, dict) or mapping.get('lid') != chat:
            raise ValueError('WAHA não confirmou o vínculo do identificador consultado; envio bloqueado.')
        pn = mapping.get('pn')
    allowed = {phone + '@c.us'}
    if len(phone) == 13 and phone[4] == '9' and phone[5] in '6789':
        allowed.add(phone[:4] + phone[5:] + '@c.us')
    elif len(phone) == 12 and phone[4] in '6789':
        allowed.add(phone[:4] + '9' + phone[4:] + '@c.us')
    if pn not in allowed:
        raise ValueError('WAHA devolveu destino sem vínculo verificável com o telefone; envio bloqueado.')
    return chat


def ready():
    value = api('GET', '/api/sessions/default')
    if value.get('status') != 'WORKING':
        raise ValueError('WhatsApp desconectado. Conecte pelo QR Code e atualize o status.')
    return value


def begin_scan(scope, ids):
    """A new enable generation first observes the entire queue without sending."""
    with LOCK:
        cfg = config()
        if not cfg.get('enabled'):
            return []
        key = 'waha_seen_' + scope
        old = get_meta(key, {}) or {}
        same = old.get('generation') == cfg.get('generation') and old.get('policy') == 2
        # A cumulative set prevents a disappearing/reappearing old ticket becoming new.
        known = set(old.get('known_ids', old.get('ids', [])))
        current = set(ids)
        candidates = set(old.get('candidate_ids', [])) if same else set()
        if same:
            candidates.update(current - known)
        pending = ((set(old.get('pending', [])) if same else set()) | (current - known if same else set())) & current
        events = get_meta('waha_events_' + scope, {}) or {}
        retryable = {int(tid) for tid, event in events.items() if str(tid).isdigit()
                     and int(tid) in candidates and same
                     and event.get('generation') == cfg['generation']
                     and event.get('status') == 'não enviado'
                     and time.time() - event.get('at', 0) >= 120}
        attempted = {int(event['ticket_id']) for event in events.values()
                     if str(event.get('ticket_id', '')).isdigit()
                     and (event.get('message_id') or event.get('status') in ('aceito pelo WAHA', 'resultado incerto'))}
        pending = {tid for tid in (pending | retryable) & current & candidates
                   if tid not in attempted and (str(tid) not in events or tid in retryable)}
        set_meta(key, {'policy': 2, 'generation': cfg['generation'], 'ids': ids,
                      'known_ids': sorted(known | current), 'candidate_ids': sorted(candidates),
                      'pending': sorted(pending), 'last_scan': time.time(),
                      'baseline_at': old.get('baseline_at') if same else time.time(), 'count': len(ids)})
        set_meta('waha_current_scope', scope)
        return {tid: cfg['generation'] for tid in sorted(pending)}


def reset_monitor_baseline():
    with LOCK:
        cfg = config().copy()
        if cfg.get('enabled'):
            cfg['generation'] = secrets.token_hex(16)
            set_meta('waha_settings', cfg)


def render(template, values, timezone):
    template = validate_contact_template(template)
    hour = datetime.now(ZoneInfo(timezone)).hour
    values = {**values, 'saudacao': 'Bom dia' if 5 <= hour < 12 else 'Boa tarde' if 12 <= hour < 18 else 'Boa noite'}
    # One pass: values cannot introduce further substitutions.
    import re
    return re.sub(r'\{([^{}]+)\}', lambda m: str(values[m[1]]), template)


def process(scope, tid, prepare, generation):
    """prepare rereads GLPI assignment and contacts immediately before submission."""
    with LOCK:
        cfg = config()
        if not cfg.get('enabled') or cfg.get('generation') != generation:
            return
        key = 'waha_events_' + scope
        events = get_meta(key, {}) or {}
        baseline = get_meta('waha_seen_' + scope, {}) or {}
        if baseline and (baseline.get('policy') != 2 or baseline.get('generation') != generation
                         or tid not in baseline.get('candidate_ids', [])):
            return
        if any(e.get('ticket_id') == tid and (e.get('message_id') or e.get('status') in
               ('aceito pelo WAHA', 'resultado incerto')) for e in events.values()):
            return
        if str(tid) in events and not (events[str(tid)].get('status') == 'não enviado'
            and events[str(tid)].get('generation') == generation
            and time.time() - events[str(tid)].get('at', 0) >= 120):
            return
        record = {'ticket_id': tid, 'at': time.time(), 'generation': generation, 'status': 'verificando'}
        events[str(tid)] = record
        def save():
            set_meta(key, events)
            set_meta('waha_current_scope', scope)
        try:
            info = ready()
            account = str((info.get('me') or {}).get('id') or '')
            if not account or account != cfg.get('account'):
                raise ValueError('A conta conectada mudou. Desative e ative novamente após conferir o número.')
            phone, message = prepare()
            chat_id = resolve_chat_id(phone)
            record['phone'] = '••••' + phone[-4:]
            record['message_text'] = message
            record['chat_id'] = chat_id
            record['account'] = account
            record['status'] = 'resultado incerto'
            record['detail'] = 'Tentativa reservada. Confira o WhatsApp antes de qualquer envio manual.'
            save()  # Durable reservation BEFORE POST. A crash never causes automatic resend.
        except Exception as exc:
            record.update(status='não enviado', detail=str(exc)[:200] if isinstance(exc, ValueError) else 'Falha na validação ou conexão. Confira o contato manualmente.')
            save()
            return
        try:
            result = api('POST', '/api/sendText', {'session': 'default', 'chatId': chat_id, 'text': message, '_assistant_operation': {'scope': scope, 'ticket': tid, 'kind': 'first', 'operation': 'first'}})
            if not isinstance(result, dict) or not result.get('id'):
                raise ValueError('Sem identificador de mensagem')
            record.update(status='aceito pelo WAHA', message_id=message_id(result['id']), detail='Envio aceito; entrega e leitura não verificadas.')
        except Exception as exc:
            record.update(status='resultado incerto', **send_failure(exc))
        save()


class Toggle(BaseModel):
    enabled: bool


class Resume(BaseModel):
    ticket_id: int = Field(gt=0)
    request_id: UUID
    text: str | None = Field(None, min_length=1, max_length=4000)


def register(app, guard, monitor_settings, prepare_resume, sync_now=None):
    @app.get('/api/whatsapp')
    def status(request: Request):
        guard(request)
        cfg = config()
        result = {'enabled': bool(cfg.get('enabled')), 'account': cfg.get('account', ''), 'status': 'não instalado'}
        try:
            value = api('GET', '/api/sessions/default')
            result.update(status=value.get('status', 'desconhecido'), connected_account=(value.get('me') or {}).get('id', ''))
        except WahaAPIError as exc:
            result['status'] = 'NEEDS_SESSION' if exc.status_code == 404 else 'UNAVAILABLE'
            result['detail'] = 'Clique em Conectar WhatsApp para criar a sessão.' if exc.status_code == 404 else str(exc)
        except Exception as exc:
            result['status'] = 'UNAVAILABLE'
            result['detail'] = str(exc)[:240] if isinstance(exc, ValueError) else 'WAHA indisponível. Confira se o serviço está iniciado.'
        monitor = monitor_settings()
        result['monitor_enabled'] = bool(monitor.get('enabled'))
        result['automation_detail'] = ('Automação pausada. Clique em Retomar envios para acompanhar novas atribuições.' if not cfg.get('enabled') else
            'Monitor parado: ative Consultar automaticamente na Minha central.' if not monitor.get('enabled') else
            'WhatsApp desconectado: conecte a sessão para enviar.' if result['status'] != 'WORKING' else
            'Automação ativa: apenas novas atribuições após a leitura inicial. A fila existente não recebe envio automático.')
        error = get_meta('workbench_error', '')
        if error: result['automation_detail'] += ' A sincronização com GLPI falhou; confira o diagnóstico da Minha central.'
        scope = get_meta('waha_current_scope', '')
        baseline = get_meta('waha_seen_' + scope, {}) if scope else {}
        result['baseline_ready'] = bool(cfg.get('enabled') and baseline.get('generation') == cfg.get('generation'))
        result['baseline_count'] = baseline.get('count', 0) if result['baseline_ready'] else 0
        result['baseline_at'] = baseline.get('baseline_at') if result['baseline_ready'] else None
        result['last_scan'] = baseline.get('last_scan') if result['baseline_ready'] else None
        if cfg.get('enabled') and not result['baseline_ready']:
            result['automation_detail'] = 'A fila de referência ainda não foi sincronizada. Aguarde a consulta e confira se o monitor está ativo na Minha central.'
        events = get_meta('waha_events_' + scope, {}) if scope else {}
        result['events'] = [{**{k: v for k, v in row.items() if k in ('ticket_id', 'at', 'status', 'phone', 'detail', 'delivery_name', 'error_code')}, 'initial': not event_id.startswith('resume:')} for event_id, row in sorted((events or {}).items(), key=lambda pair: pair[1]['at'], reverse=True)[:50]]
        return result

    @app.post('/api/whatsapp/delivery/{ticket_id}')
    def check_delivery(ticket_id: int, request: Request):
        guard(request)
        if ticket_id <= 0:
            raise HTTPException(400, 'Chamado inválido.')
        try:
            scope, phone, _ = prepare_resume(ticket_id)
            event = (get_meta('waha_events_' + scope, {}) or {}).get(str(ticket_id))
            if not event or event.get('chat_id') != phone + '@c.us':
                raise ValueError('Não há envio inicial correspondente a este contato e usuário.')
            result = refresh_delivery(scope, str(ticket_id), manual=True)
            return {'ok': result.get('delivery_ack') in (2, 3, 4), 'detail': result.get('detail', ''), 'ack_name': result.get('delivery_name')}
        except Exception as exc:
            raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Confirmação indisponível. Nenhuma mensagem foi reenviada.')

    @app.post('/api/whatsapp/connect')
    def connect(request: Request):
        guard(request)
        try:
            sessions = api('GET', '/api/sessions?all=true')
            current = next((s for s in sessions if s.get('name') == 'default'), None)
            if current is None:
                api('POST', '/api/sessions', {'name': 'default', 'start': True})
            elif current.get('status') == 'FAILED':
                api('POST', '/api/sessions/default/restart', {})
            elif current.get('status') == 'STOPPED':
                api('POST', '/api/sessions/default/start', {})
            return {'ok': True}
        except ValueError as exc:
            raise HTTPException(503, str(exc)[:240]) from None
        except Exception:
            raise HTTPException(503, 'Não foi possível iniciar a sessão. Confira a instalação do WAHA.')

    @app.get('/api/whatsapp/qr')
    def qr(request: Request):
        guard(request)
        try:
            return Response(api('GET', '/api/default/auth/qr', image=True), media_type='image/png', headers={'Cache-Control': 'no-store'})
        except ValueError as exc:
            raise HTTPException(409, str(exc)[:240]) from None
        except Exception:
            raise HTTPException(409, 'QR indisponível. Aguarde a sessão iniciar ou confira se já está conectada.')

    @app.put('/api/whatsapp/settings')
    def toggle(payload: Toggle, request: Request):
        guard(request)
        with LOCK:
            previous = config().copy()
            updated = previous.copy()
            if payload.enabled:
                if not monitor_settings().get('enabled'):
                    raise HTTPException(400, 'Ative o monitor na Minha central antes de ativar o envio automático.')
                try:
                    account = str((ready().get('me') or {}).get('id') or '')
                    if not account:
                        raise ValueError('Conta ainda não identificada. Atualize o status.')
                except Exception:
                    raise HTTPException(400, 'Conecte o WhatsApp e confira o número antes de ativar.')
                if not updated.get('enabled') or updated.get('account') != account:
                    updated.update(generation=secrets.token_hex(16), account=account)
            updated['enabled'] = payload.enabled
            set_meta('waha_settings', updated)
        if payload.enabled and sync_now:
            # Establish the baseline before reporting activation complete.
            # Do not hold WAHA's lock while waiting for the monitor's sync lock.
            try:
                sync_now()
            except Exception as exc:
                with LOCK:
                    if config() == updated:  # Never undo a pause made while the scan was running.
                        set_meta('waha_settings', previous)
                raise HTTPException(503, 'Automação não ativada: consulta inicial ao GLPI falhou. Verifique a Minha central e tente novamente.') from exc
        return {'ok': True, 'enabled': payload.enabled}

    @app.post('/api/whatsapp/resume')
    def resume(payload: Resume, request: Request):
        guard(request)
        with LOCK:
            try:
                scope, phone, default_text = prepare_resume(payload.ticket_id)
                info = ready()
                connected = str((info.get('me') or {}).get('id') or '')
                expected = config().get('account')
                if not connected or (expected and connected != expected):
                    raise ValueError('Confira a conta conectada na área Bridge e IA.')
            except Exception as exc:
                raise HTTPException(409, str(exc)[:200] if isinstance(exc, ValueError) else 'Não foi possível validar atribuição, contato ou conexão.')
            text = payload.text if payload.text is not None else default_text
            import re
            if not re.search(r'#' + str(payload.ticket_id) + r'(?!\d)', text):
                raise HTTPException(400, 'Mantenha #' + str(payload.ticket_id) + ' na mensagem.')
            key = 'waha_events_' + scope
            events = get_meta(key, {}) or {}
            event_id = 'resume:' + str(payload.request_id)
            if event_id in events:
                return events[event_id]
            if any(v.get('ticket_id') == payload.ticket_id and time.time() - v.get('at', 0) < 60
                   and v.get('status') in ('resultado incerto', 'aceito pelo WAHA') for v in events.values()):
                raise HTTPException(409, 'Já houve uma tentativa neste chamado no último minuto. Confira a conversa antes de repetir.')
            try:
                chat_id = resolve_chat_id(phone)
            except Exception as exc:
                raise HTTPException(409, str(exc)[:200] if isinstance(exc, ValueError) else 'Não foi possível validar o destino no WAHA; nenhum envio realizado.') from exc
            record = {'ticket_id': payload.ticket_id, 'at': time.time(), 'phone': '••••' + phone[-4:],
                      'kind': 'Retomar atendimento', 'message_text': text, 'chat_id': chat_id, 'account': connected, 'status': 'resultado incerto',
                      'detail': 'Tentativa reservada; confira o WhatsApp antes de repetir.'}
            events[event_id] = record
            set_meta(key, events)
            set_meta('waha_current_scope', scope)
            try:
                result = api('POST', '/api/sendText', {'session': 'default', 'chatId': chat_id, 'text': text, '_assistant_operation': {'scope': scope, 'ticket': payload.ticket_id, 'kind': 'resume', 'operation': str(payload.request_id)}})
                if not isinstance(result, dict) or not result.get('id'):
                    raise ValueError('Sem confirmação')
                record.update(status='aceito pelo WAHA', message_id=message_id(result['id']), detail='Envio aceito; entrega e leitura não verificadas.')
            except Exception as exc:
                record.update(send_failure(exc))
            set_meta(key, events)
            return record


ACK_NAMES = {-1: 'ERROR', 0: 'PENDING', 1: 'SERVER', 2: 'DEVICE', 3: 'READ', 4: 'PLAYED'}


def message_id(value):
    if isinstance(value, dict):
        value = value.get('_serialized')
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_@.:-]{1,250}', value):
        raise ValueError('Identificador de mensagem inválido; confira o resultado no WhatsApp.')
    return value


def refresh_delivery(scope, event_key, manual=False):
    """Read the exact outgoing message, never send/retry messages on this path."""
    with LOCK:
        events = get_meta('waha_events_' + scope, {}) or {}
        event = events.get(str(event_key))
        if not event or not event.get('message_id'):
            return event
        if event.get('delivery_ack') in (2, 3, 4):
            return event  # Preserve the observed historical delivery proof.
        if not manual and time.time() - event['at'] > 600:
            raise ValueError('Janela automática de 10 minutos encerrada. Use Verificar entrega; nenhuma mensagem será reenviada.')
        if not event.get('chat_id') or not event.get('account') or not event.get('message_text'):
            raise ValueError('Registro antigo sem vínculo suficiente para comprovar entrega. Não será reenviado.')
        # Throttle GET polling; never infer success from elapsed time.
        if time.time() - event.get('delivery_checked_at', 0) < 10:
            return event
        info = ready()
        if str((info.get('me') or {}).get('id') or '') != event['account']:
            raise ValueError('A conta do WhatsApp mudou. Comprovação de entrega bloqueada.')
        path = '/api/default/chats/' + quote(event['chat_id'], safe='') + '/messages/' + quote(message_id(event['message_id']), safe='') + '?downloadMedia=false'
        value = api('GET', path)
        if not isinstance(value, dict) or value.get('id') != event['message_id'] or value.get('fromMe') is not True or value.get('body') != event['message_text']:
            raise ValueError('A resposta não corresponde à mensagem enviada. Entrega não confirmada.')
        if value.get('to') and value['to'] != event['chat_id']:
            raise ValueError('O destinatário da confirmação não corresponde ao contato.')
        ack = value.get('ack')
        if type(ack) is not int or ack not in ACK_NAMES or (value.get('ackName') and value['ackName'] != ACK_NAMES[ack]):
            raise ValueError('Confirmação de entrega inválida ou desconhecida.')
        now = time.time()
        event.update(delivery_ack=ack, delivery_name=ACK_NAMES[ack], delivery_checked_at=now)
        if ack >= 2:
            event['delivery_observed_at'] = now
            event['detail'] = 'Entrega confirmada pelo WhatsApp (' + ACK_NAMES[ack] + ').'
        elif ack == -1:
            event['detail'] = 'WhatsApp informou erro. Não haverá reenvio automático.'
        else:
            event['detail'] = 'Mensagem ainda sem confirmação de entrega ao aparelho.'
        set_meta('waha_events_' + scope, events)
        return event


def send_failure(exc):
    # Deliberately never store arbitrary server bodies, URLs, credentials or stack traces.
    if isinstance(exc, WahaAPIError):
        code, reason = 'HTTP_' + str(exc.status_code), str(exc)
    elif isinstance(exc, (TimeoutError, requests.exceptions.Timeout)):
        code, reason = 'TIMEOUT', 'WAHA não respondeu dentro do prazo de envio.'
    elif isinstance(exc, (ConnectionError, requests.exceptions.ConnectionError)):
        code, reason = 'CONNECTION', 'Conexão com o WAHA interrompida ou indisponível.'
    elif isinstance(exc, (ValueError, KeyError, TypeError)):
        code, reason = 'INVALID_RESPONSE', 'WAHA não devolveu uma confirmação com identificador válido.'
    else:
        code, reason = 'UNEXPECTED', 'Falha inesperada ao processar a resposta do WAHA.'
    return {'error_code': code, 'detail': reason + ' Não haverá reenvio automático; confira a conversa.'}


def optional_first_contact_receipt(base, user_id, ticket_id, refresh=True):
    """A missing receipt must never prevent creation of the initial GLPI response."""
    try:
        if not refresh:
            import hashlib
            scope = hashlib.sha256(f'{base}|{user_id}'.encode()).hexdigest()[:24]
            event = (get_meta('waha_events_' + scope, {}) or {}).get(str(ticket_id), {})
            if event.get('delivery_ack') not in (2, 3, 4):
                return None
        return first_contact_receipt(base, user_id, ticket_id, nonblocking=not refresh)
    except Exception:
        return None


def first_contact_receipt(base, user_id, ticket_id, required=False, nonblocking=False):
    import hashlib
    scope = hashlib.sha256(f'{base}|{user_id}'.encode()).hexdigest()[:24]
    if not LOCK.acquire(timeout=0 if nonblocking else 20):
        raise ValueError('Primeiro contato ainda em envio. Aguarde a confirmação de entrega.')
    try:
        event = (get_meta('waha_events_' + scope, {}) or {}).get(str(ticket_id))
        if not event:
            if required or config().get('enabled'):
                raise ValueError('Primeiro contato ainda sem comprovante. T01 aguardando entrega pelo WhatsApp.')
            return None  # Integration disabled: existing manual workflow remains available.
        if event.get('status') != 'aceito pelo WAHA' or not event.get('message_id'):
            raise ValueError('Primeiro contato sem confirmação do WAHA. Confira a conversa antes de registrar a primeira tarefa.')
        event = refresh_delivery(scope, str(ticket_id))
        if event.get('delivery_ack') not in (2, 3, 4):
            raise ValueError('T01 aguardando entrega ao aparelho. Aceite ou envio ao servidor não comprova entrega.')
        return {'ticket_id': ticket_id,
                'at': datetime.fromtimestamp(event['at'], ZoneInfo('America/Sao_Paulo')).isoformat(),
                'delivery_observed_at': datetime.fromtimestamp(event['delivery_observed_at'], ZoneInfo('America/Sao_Paulo')).isoformat(),
                'phone': event.get('phone', ''), 'message_id': event['message_id'], 'text': event.get('message_text', ''),
                'ack': event['delivery_ack'], 'ack_name': event['delivery_name'],
                'status': 'Entrega ao aparelho confirmada pelo WhatsApp (' + event['delivery_name'] + ').'}
    finally:
        LOCK.release()


def receipt_html(receipt):
    import html
    if not receipt:
        return ''
    def readable(value):
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                return str(value)
            return parsed.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y às %H:%M:%S') + ' (Brasília)'
        except (ValueError, TypeError):
            return str(value or 'Não registrado')
    def escape(value):
        return html.escape(str(value)).replace('\n', '<br>')
    ack = receipt.get('ack')
    status = ('Leitura confirmada pelo WhatsApp.' if ack in (3, 4) else
              'Entrega ao aparelho confirmada pelo WhatsApp.' if ack == 2 else
              'Entrega ainda não confirmada.')
    return ('<hr><p><strong>Primeiro contato pelo WhatsApp</strong></p>'
            '<p>' + status + ' Contato: <strong>' + escape(receipt['phone']) + '</strong>.</p>'
            '<ul><li><strong>Tentativa registrada:</strong> ' + escape(readable(receipt['at'])) + '</li>'
            '<li><strong>Confirmação observada:</strong> ' + escape(readable(receipt.get('delivery_observed_at'))) + '</li></ul>'
            '<p><strong>Mensagem enviada</strong></p><blockquote>' + escape(receipt['text']) + '</blockquote>'
            '<p><small>Registro vinculado ao chamado #' + escape(receipt['ticket_id']) +
            '. Identificador completo preservado no registro interno do Assistant.</small></p>')
