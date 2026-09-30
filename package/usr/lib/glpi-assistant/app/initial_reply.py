"""Public initial follow-up, independently of WhatsApp; durable no-duplicate POST."""
import hashlib
import html
import re
import whatsapp_auto

MARKER = 'glpi-assistant:initial-reply:T01'


LEGACY_TEMPLATE = 'Olá! O chamado #{chamado} foi atribuído ao suporte para atendimento.\n\nVocê pode responder por este chamado para complementar as informações.'
DEFAULT_TEMPLATE = '{saudacao}, tudo bem? Aqui é {tecnico}, da Equipe de Suporte. Vou acompanhar seu chamado #{chamado} — {assunto}.\n\nSe quiser acrescentar alguma informação ou indicar o melhor horário para conversarmos, é só responder por aqui.'
FIELDS = {'saudacao', 'tecnico', 'chamado', 'assunto'}


def validate_template(value):
    if not value.strip() or len(value) > 4000:
        raise ValueError('Informe uma mensagem entre 1 e 4000 caracteres.')
    tokens = re.findall(r'\{([^{}]*)\}', value)
    if any(t not in FIELDS for t in tokens) or re.search(r'[{}]', re.sub(r'\{[^{}]*\}', '', value)):
        raise ValueError('Use somente {saudacao}, {tecnico}, {chamado} e {assunto}.')
    return value


def render_intro(template, tid, subject, context=None):
    values = {**(context or {}), 'chamado': str(tid), 'assunto': str(subject or '')}
    text = re.sub(r'\{(saudacao|tecnico|chamado|assunto)\}', lambda m: str(values.get(m[1], 'Olá' if m[1] == 'saudacao' else 'da equipe de suporte')), template)
    return '<p>' + html.escape(text).replace('\n', '<br>') + '</p>'


def belongs(row, tid, uid):
    return (row.get('itemtype') == 'Ticket' and int(row.get('items_id') or 0) == tid
            and int(row.get('users_id') or 0) == uid and int(row.get('is_private') or 0) == 0
            and MARKER in html.unescape(str(row.get('content') or '')))


def reconcile_receipt(glpi, tid, uid, record, save):
    if record.get('initial_receipt_id'):
        return
    receipt = whatsapp_auto.optional_first_contact_receipt(glpi.base, uid, tid)
    if not receipt:
        return
    fid = int(record['initial_followup_id'])
    current = glpi.get(f'ITILFollowup/{fid}')
    if not belongs(current, tid, uid):
        raise ValueError('Resposta inicial mudou de autor, visibilidade ou chamado. Atualização bloqueada.')
    proof = 'glpi-assistant:delivery:' + hashlib.sha256(receipt['message_id'].encode()).hexdigest()
    content = str(current.get('content') or '')
    # Decode GLPI's outer HTML encoding only; preserve escaped user text within HTML.
    if '<' not in content:
        content = html.unescape(content)
    if proof not in content:
        content += '<!-- ' + proof + ' -->' + whatsapp_auto.receipt_html(receipt)
        glpi.put(f'ITILFollowup/{fid}', {'input': {'id': fid, 'content': content}})
        observed = glpi.get(f'ITILFollowup/{fid}')
        if not belongs(observed, tid, uid) or proof not in html.unescape(str(observed.get('content') or '')):
            raise ValueError('Edição da resposta ainda sem confirmação na releitura do GLPI.')
    record['initial_receipt_id'] = receipt['message_id']
    record['initial'] = 'resposta criada · entrega confirmada'
    save()


def request_summary(description):
    # Decode nested GLPI entities, then escape every value before producing HTML.
    text = str(description or '')[:12000]
    for _ in range(2):
        text = html.unescape(text)
    matches = list(re.finditer(r'(?:^|\s)([1-9][0-9]?)\)\s+', text))
    if len(matches) >= 3 and [int(m[1]) for m in matches] == list(range(1, len(matches) + 1)):
        rows = []
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            value = text[match.end():end].strip()
            label, sep, content = value.partition(':')
            if sep and len(label) <= 160:
                rows.append('<li><strong>' + html.escape(label.strip()) + ':</strong> ' + html.escape(content.strip()) + '</li>')
            else:
                rows.append('<li>' + html.escape(value) + '</li>')
        prefix = text[:matches[0].start()].strip()
        # Preserve any nonstandard introductory content instead of discarding it.
        intro = '' if prefix.casefold() in ('', 'dados do formulário') else '<p>' + html.escape(prefix) + '</p>'
        return intro + '<ul>' + ''.join(rows) + '</ul>'
    return '<p>' + html.escape(text).replace('\n', '<br>') + '</p>'


def ensure(glpi, tid, uid, ticket, record, save, description, template=None, context=None):
    if record.get('initial_followup_id'):
        reconcile_receipt(glpi, tid, uid, record, save)
        return
    # Read before POST, also after a restart/ambiguous prior response.
    replies = glpi.list_subitems('Ticket', tid, 'ITILFollowup')
    own = [r for r in replies if belongs(r, tid, uid)]
    if len(own) > 1:
        raise ValueError('Mais de uma resposta inicial encontrada; revisão manual necessária.')
    if own:
        record.update(initial='resposta criada', initial_followup_id=int(own[0]['id']))
        save()
        reconcile_receipt(glpi, tid, uid, record, save)
        return
    # Historical tasks remain intact; do not notify old tickets on upgrade.
    tasks = glpi.ticket_tasks(tid)
    if tasks and 'backup' in str(ticket.get('name') or '').lower():
        record['initial'] = 'modelo de backup existente; anexar nas tarefas prontas'
        return
    existing = next((t for t in tasks if re.search(r'glpi-assistant:[^>\s]*:t0?1|\bt0?1\b|problema\s+(?:relatado|informado)', html.unescape(str(t.get('content') or '')), re.I)), None)
    if existing:
        record.update(initial='existente', initial_task_id=existing['id'])
        return
    if record.get('initial') in ('enviando', 'resultado incerto'):
        record['initial'] = 'resultado incerto'
        return
    if not description:
        record['initial'] = 'sem solicitação inicial; revisão necessária'
        return
    body = ('<!-- ' + MARKER + ' --><p><strong>T01 — Recebimento da solicitação</strong></p>'
            + render_intro(template if template is not None else DEFAULT_TEMPLATE, tid, ticket.get('name'), context)
            + '<p><strong>Solicitação registrada</strong></p>' + request_summary(description))
    record['initial'] = 'enviando'
    save()  # Persist reservation before POST; no automatic duplicate after timeout.
    try:
        result = glpi.post('ITILFollowup', {'input': {'itemtype': 'Ticket', 'items_id': tid,
                          'content': body, 'is_private': 0}})
        fid = int(result['id'])
        if fid <= 0 or not belongs(glpi.get(f'ITILFollowup/{fid}'), tid, uid):
            raise ValueError('Resposta inicial não confirmada no GLPI.')
        record.update(initial='resposta criada', initial_followup_id=fid)
        save()
    except Exception:
        record['initial'] = 'resultado incerto'
        save()
        raise
