"""3.0 workbench. API is authoritative; browser context is only a search hint."""
from __future__ import annotations
import initial_reply
import whatsapp_auto
from contact_policy import self_only_ticket
import hashlib
import html
import json
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from store import get_meta, set_meta, load_config
from contact_template import DEFAULT_CONTACT_MESSAGE, DEFAULT_CONTINUATION_MESSAGE, validate_contact_template

LOCK = threading.RLock()
SYNC_LOCK = threading.Lock()
STOP = threading.Event()
DEFAULTS = {"enabled": True, "auto_initial": True, "initial_reply_template": initial_reply.DEFAULT_TEMPLATE, "stale_hours": 24,
            "interval": 30, "timezone": "America/Sao_Paulo", "country_code": "55", "contact_message": DEFAULT_CONTACT_MESSAGE, "continuation_message": DEFAULT_CONTINUATION_MESSAGE, "contact_name": ""}


def plain(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))).strip()


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', plain(value).casefold()) if not unicodedata.combining(c))


def stamp(value, timezone):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(timezone))).timestamp()
    except (ValueError, TypeError):
        return None


def _whatsapp_digits(phone, country='55'):
    """Normaliza somente números que podem virar um destino WhatsApp seguro.

    Para o Brasil, um número sem ``+`` precisa ter DDD (10/11 dígitos) ou já
    trazer o DDI 55 (12/13 dígitos). Números locais de 8/9 dígitos são
    deliberadamente rejeitados: a base real mostrou perfis com telefone local
    enquanto o formulário do chamado trazia o contato completo com DDD.
    """
    raw = str(phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    if raw.startswith('+'):
        return digits if 8 <= len(digits) <= 15 else ''
    if str(country) == '55':
        # Discagem nacional antiga pode trazer o zero de tronco antes do DDD.
        if digits.startswith('0') and len(digits) in (11, 12):
            digits = digits[1:]
        if len(digits) in (10, 11):
            return '55' + digits
        if digits.startswith('55') and len(digits) in (12, 13):
            return digits
        return ''
    return digits if 8 <= len(digits) <= 15 else ''


def whatsapp(phone, ticket_id, title, country='55'):
    digits = _whatsapp_digits(phone, country)
    if not digits:
        return None
    message = f"Olá! Sou da equipe de suporte. Estou entrando em contato sobre o chamado #{ticket_id}: {title}. Podemos iniciar o atendimento?"
    return 'https://wa.me/' + digits + '?' + urlencode({'text': message})


def description_contact_data(value):
    """Parse labeled fields; malformed explicit contacts must not fall back silently."""
    text = html.unescape(str(value or ''))
    text = re.sub(r'<(?:br\s*/?|/p|/div|/li|/tr)>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]*>', ' ', text).replace('\xa0', ' ')
    label = r'\b(?:telefone|tel|celular|whats(?:app)?|fone|contato)\b'
    candidate = r'\+?\(?\d[\d ().-]{5,}\d'
    phones, invalid = [], False
    ddds = {11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,41,42,43,44,45,46,47,48,49,51,53,54,55,61,62,63,64,65,66,67,68,69,71,73,74,75,77,79,81,82,83,84,85,86,87,88,89,91,92,93,94,95,96,97,98,99}
    for line in text.splitlines():
        # Stop at a semicolon or at the next field label, not at unrelated numbers later in a paragraph.
        for match in re.finditer(r'(?=' + label + r'[^\d+\n;]{0,48}(?P<values>[+\d(][^;\n]{0,140}))', line, re.I):
            values = match.group('values')
            first = re.match(candidate, values)
            if not first:
                invalid = True
                continue
            tokens = [first.group()]
            tail = values[first.end():]
            while True:
                alternative = re.match(r'\s*(?:/|,|ou|e)\s*(' + candidate + r')', tail, re.I)
                if not alternative: break
                tokens.append(alternative.group(1)); tail = tail[alternative.end():]
            for raw in tokens:
                digits = _whatsapp_digits(raw)
                valid = digits.startswith('55') and len(digits) in (12,13) and int(digits[2:4]) in ddds
                if not valid:
                    invalid = True
                elif digits not in phones:
                    phones.append(digits)
    return {'phones': phones, 'invalid': invalid}


def contact_phones_from_text(value):
    return description_contact_data(value)['phones']


def contact_phone_from_text(value):
    phones = contact_phones_from_text(value)
    return phones[0][2:] if len(phones) == 1 else ''


def fingerprint(ticket, tasks, followups, solutions):
    # Include all timeline items to reject stale reviews, even if date_mod has second precision.
    payload = [ticket, tasks, followups, solutions]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def options(glpi):
    raw = glpi.list_search_options('Ticket')
    def field(table, name):
        for k, v in raw.items():
            if isinstance(v, dict) and v.get('table') == table and v.get('field') == name and str(k).isdigit():
                return int(k)
        raise ValueError(f'Campo de busca não disponível: {table}.{name}')
    return raw, field


def searchtype(raw, field_id, preferred, *fallbacks):
    """Escolhe somente operadores declarados pelo listSearchOptions real."""
    option = raw.get(str(field_id), {}) if isinstance(raw, dict) else {}
    allowed = option.get('available_searchtypes') if isinstance(option, dict) else None
    if not isinstance(allowed, list) or not allowed:
        return preferred
    for candidate in (preferred, *fallbacks):
        if candidate in allowed:
            return candidate
    raise ValueError(f'Campo {field_id} não aceita nenhum operador esperado: {preferred}, {", ".join(fallbacks)}')


def equals_any(field_id, values):
    """Grupo OR usando apenas `equals`; evita `lessthan` em dropdown/status."""
    values = [int(v) for v in values]
    if len(values) == 1:
        return (field_id, 'equals', values[0])
    return {
        'link': 'AND',
        'criteria': [
            {'field': field_id, 'searchtype': 'equals', 'value': value, 'link': 'OR'}
            for value in values
        ],
    }


def exact_ticket_criterion(raw, field_id, ticket_id):
    # Nesta instalação real Ticket.id anuncia contains/notcontains, não equals.
    return (field_id, searchtype(raw, field_id, 'equals', 'contains'), int(ticket_id))


def search_ids(glpi, criteria, *, limit=500, sort_field=None):
    _, field = options(glpi)
    fid = field('glpi_tickets', 'id')
    params = {'forcedisplay[0]': fid, 'reset': 'true', 'sort': sort_field or fid, 'order': 'DESC'}
    params.update(query_params(criteria))
    result = []
    total = 0
    start = 0
    while start < limit:
        data = glpi.get('search/Ticket', {**params, 'range': f'{start}-{min(start+99, limit-1)}'})
        rows = data.get('data') or []
        total = int(data.get('totalcount') or 0)
        if isinstance(rows, dict): rows = list(rows.values())
        page = []
        for row in rows:
            value = row.get(str(fid))
            if not str(value).isdigit():
                raise ValueError('GLPI retornou identificador de chamado inesperado; varredura interrompida.')
            page.append(int(value))
        if not rows:
            if start < total: raise ValueError('GLPI retornou página vazia antes do total informado')
            break
        if result and all(i in result for i in page):
            raise ValueError('GLPI repetiu a página de resultados; consulta incompleta')
        result.extend(page)
        start += len(rows)
        if start >= total: break
    return list(dict.fromkeys(result)), total > limit


def query_params(criteria):
    params={}
    def walk(value, prefix):
        if isinstance(value,dict):
            for key,item in value.items(): walk(item,f'{prefix}[{key}]')
        elif isinstance(value,list):
            for key,item in enumerate(value): walk(item,f'{prefix}[{key}]')
        else: params[prefix]=value
    for i,criterion in enumerate(criteria):
        if not isinstance(criterion,dict):
            f,op,value=criterion
            criterion={'field':f,'searchtype':op,'value':value,'link':'AND'}
        walk(criterion,f'criteria[{i}]')
    return params


def search_page(glpi, criteria, offset=0, size=40, sort_field=None):
    _, field = options(glpi)
    fid = field('glpi_tickets', 'id')
    params = {'forcedisplay[0]': fid, 'reset':'true', 'sort':sort_field or fid,
              'order':'DESC', 'range':f'{offset}-{offset+size-1}'}
    params.update(query_params(criteria))
    data = glpi.get('search/Ticket', params)
    rows = data.get('data') or []
    if isinstance(rows,dict): rows=list(rows.values())
    ids=[]
    for row in rows:
        value=row.get(str(fid))
        if not str(value).isdigit(): raise ValueError('Identificador inesperado na busca de chamados')
        ids.append(int(value))
    total=int(data.get('totalcount') or 0)
    if not rows and offset<total: raise ValueError('Página vazia antes do total informado pela API')
    return ids, total, offset+len(rows) if rows and offset+len(rows)<total else None


def status_transition_actor(logs, ticket_id, status_field, target_status):
    """Return the actor of the latest transition to a concrete GLPI status."""
    aliases = {
        5: {'5', 'solved', 'solucionado', 'resolvido', 'resolved'},
        6: {'6', 'closed', 'fechado', 'clos', 'cerrado'},
    }
    changes=[x for x in logs if x.get('itemtype')=='Ticket'
             and int(x.get('items_id') or 0)==ticket_id
             and int(x.get('id_search_option') or 0)==status_field
             and int(x.get('linked_action') or 0)==0]
    matching=[]
    for item in changes:
        raw_status=item.get('new_id') if item.get('new_id') is not None else item.get('new_value')
        if norm(raw_status) in aliases.get(int(target_status), {str(target_status)}):
            matching.append(item)
    if not matching:
        return None
    last=max(matching,key=lambda x:(x.get('date_mod') or '',int(x.get('id') or 0)))
    match=re.search(r' \((\d+)\)$',str(last.get('user_name') or ''))
    return int(match[1]) if match else None


def closing_actor(logs, ticket_id, status_field):
    return status_transition_actor(logs, ticket_id, status_field, 6)


def own_solution_info(glpi, ticket_id, uid, timezone):
    """Identify a solution authored/edited by the authenticated technician.

    Closed tickets may be approved by the requester or by automation, so the
    final 5→6 actor is not a reliable proxy for who performed the technical
    solution.  The personal closure workspace therefore follows solution
    authorship first and uses the status-transition log only as a fallback.
    """
    rows=glpi.list_subitems('Ticket', ticket_id, 'ITILSolution')
    mine=[row for row in rows if int(row.get('users_id') or 0)==uid or int(row.get('users_id_editor') or 0)==uid]
    if not mine:
        return None
    approved=[row for row in mine if row.get('date_approval')]
    pool=approved or mine
    latest=max(pool,key=lambda x:(x.get('date_approval') or x.get('date_creation') or x.get('date_mod') or x.get('date') or '', int(x.get('id') or 0)))
    return {
        'id': int(latest.get('id') or 0),
        'date': stamp(latest.get('date_creation') or latest.get('date_mod') or latest.get('date'), timezone),
        'approved_at': stamp(latest.get('date_approval'), timezone),
        'solution_status': int(latest.get('status') or 0),
        'content': plain(latest.get('content'))[:350],
    }


class Settings(BaseModel):
    enabled: bool = True
    auto_initial: bool = True
    initial_reply_template: str = Field(initial_reply.DEFAULT_TEMPLATE, min_length=1, max_length=4000)
    stale_hours: int = Field(24, ge=1, le=720)
    interval: int = Field(30, ge=30, le=3600)
    timezone: str = 'America/Sao_Paulo'
    country_code: str = '55'
    contact_message: str = Field(DEFAULTS['contact_message'], min_length=1, max_length=2000)
    continuation_message: str = Field(DEFAULTS['continuation_message'], min_length=1, max_length=2000)
    contact_name: str = Field('', max_length=120)


class SolutionItem(BaseModel):
    ticket_id: int = Field(gt=0)
    content: str = Field(min_length=10, max_length=20000)


class SolutionReview(BaseModel):
    items: list[SolutionItem] = Field(min_length=1, max_length=20)
    target: str = 'solve'


class ApplyReview(BaseModel):
    plan_id: str


class BrowserContext(BaseModel):
    ticket_id: int = Field(gt=0)
    url: str = Field(max_length=2048)
    title: str = Field(max_length=500)
    text: str = Field(max_length=16000)


def register(app, client, snapshot, local_guard, bridge_guard):
    def settings():
        cfg = {**DEFAULTS, **(get_meta('workbench_settings', {}) or {})}
        legacy = 'Olá, {nome}! Sou da equipe de suporte. Estou entrando em contato sobre o chamado #{chamado}: {assunto}. Podemos iniciar o atendimento?'
        if cfg['contact_message'] == legacy:
            cfg['contact_message'] = DEFAULT_CONTACT_MESSAGE
        if cfg['initial_reply_template'] == initial_reply.LEGACY_TEMPLATE:
            cfg['initial_reply_template'] = initial_reply.DEFAULT_TEMPLATE
        return cfg

    def prepare_resume(tid):
        with client() as glpi:
            phone, message = prepare_contact(glpi, tid, glpi.current_user_id(), continuation=True)
            return scope(glpi), phone, message

    whatsapp_auto.register(app, local_guard, settings, prepare_resume, lambda: sync())

    def config_identity():
        return hashlib.sha256(json.dumps(load_config() or {}, sort_keys=True).encode()).hexdigest()

    def scope(glpi):
        return hashlib.sha256(f'{glpi.base}|{glpi.current_user_id()}'.encode()).hexdigest()[:24]

    def url(ticket_id):
        base = (load_config() or {}).get('url', '').rstrip('/').removesuffix('/apirest.php')
        return base + f'/front/ticket.form.php?id={ticket_id}'

    def ticket_for_scan(glpi, ticket_id):
        """Lê ticket sem reduzir o escopo `all` a cada item da fila."""
        try:
            return glpi.get_ticket(ticket_id)
        except Exception as exc:
            text = str(exc)
            if '403' not in text and '404' not in text and 'ERROR_RIGHT_MISSING' not in text:
                raise
            return glpi.activate_context_for_ticket(ticket_id)

    def cached_user(glpi, user_id):
        cache = getattr(glpi, '_workbench_users', {})
        key = int(user_id)
        if key not in cache:
            try:
                value = glpi.get(f'User/{key}')
                cache[key] = value if isinstance(value, dict) else None
            except Exception:
                cache[key] = None
            glpi._workbench_users = cache
        return cache[key]

    def requester_contacts(glpi, ticket, relations, ticket_id, title, cfg):
        extracted = description_contact_data(ticket.get('content'))
        description_phones = extracted['phones']
        issue = 'Telefone da descrição incompleto ou inválido; confira o DDD.' if extracted['invalid'] else 'Mais de um telefone na descrição; confira o destinatário.' if len(description_phones) > 1 else ''
        contacts = [{'name': 'Contato do atendimento', 'phone': phone,
                     'phone_source': 'descricao', 'priority': 'principal',
                     'ambiguous': bool(issue), 'contact_issue': issue,
                     'whatsapp': whatsapp(phone, ticket_id, title, cfg['country_code'])}
                    for phone in description_phones]
        if extracted['invalid'] and not contacts:
            contacts.append({'name':'Contato a conferir', 'phone':'', 'phone_source':'descricao', 'priority':'principal', 'ambiguous':True, 'contact_issue':issue, 'whatsapp':None})
        for rel in [x for x in relations if int(x.get('type') or 0) == 1]:
            person = cached_user(glpi, int(rel.get('users_id') or 0)) if rel.get('users_id') else None
            name = plain(rel.get('label', ''))
            candidates = []
            if person:
                candidates = [person.get('mobile'), person.get('phone'), person.get('phone2')]
                name = plain(' '.join(str(person.get(k) or '') for k in ('firstname', 'realname'))) or person.get('name') or name
            phone = next((str(v).strip() for v in candidates if v and _whatsapp_digits(v, cfg['country_code'])), '')
            contacts.append({'name': name or 'Solicitante', 'phone': phone,
                             'phone_source': 'perfil' if phone else 'indisponivel',
                             'priority': 'secundario' if description_phones or extracted['invalid'] else 'principal',
                             'whatsapp': whatsapp(phone, ticket_id, title, cfg['country_code'])})
        return contacts

    def assigned(glpi, ticket_id, uid):
        try:
            return any(int(x.get('users_id') or 0) == uid and int(x.get('type') or 0) == 2 for x in glpi.ticket_users(ticket_id))
        except Exception as exc:
            if '403' not in str(exc) and 'ERROR_RIGHT_MISSING' not in str(exc): raise
            raw,field=options(glpi)
            if raw.get('5',{}).get('table')!='glpi_users': raise
            fid=field('glpi_tickets','id')
            ids,_,_=search_page(glpi,[(5,'equals',uid),exact_ticket_criterion(raw,fid,ticket_id)],size=10)
            return ticket_id in ids

    def timeline(glpi, tid):
        return (glpi.ticket_tasks(tid), glpi.list_subitems('Ticket', tid, 'ITILFollowup'),
                glpi.list_subitems('Ticket', tid, 'ITILSolution'))

    def read_timeline(glpi, tid, warnings):
        values=[]
        for kind in ('TicketTask', 'ITILFollowup', 'ITILSolution'):
            try:
                values.append(glpi.ticket_tasks(tid) if kind=='TicketTask' else glpi.list_subitems('Ticket',tid,kind))
            except Exception as exc:
                warnings.append({'ticket_id':tid,'resource':kind,'error':str(exc)[:300]})
                values.append([])
        return tuple(values)

    def overview(glpi, tid, warnings, ticket=None):
        t=ticket if ticket is not None else glpi.activate_context_for_ticket(tid)
        def label(kind, id, fallback):
            if not id: return fallback
            cache=getattr(glpi,'_workbench_labels',{})
            key=(kind,id)
            if key not in cache:
                try:
                    value=glpi.get(f'{kind}/{id}')
                    cache[key]=plain(value.get('completename') or value.get('name')) or f'{kind} #{id}'
                except Exception:
                    cache[key]=f'{kind} #{id}'
                glpi._workbench_labels=cache
            return cache[key]
        eid=int(t.get('entities_id') or 0);cid=int(t.get('itilcategories_id') or 0)
        return {'id':tid,'title':plain(t.get('name')),'raw':t,'entity_id':eid,
                'entity':{'label':label('Entity',eid,'Entidade raiz')},
                'category':{'label':label('ITILCategory',cid,'Sem categoria')},
                'status':int(t.get('status') or 0),'priority':int(t.get('priority') or 0)}

    def all_entities(glpi, warnings):
        try: glpi.change_active_entities_all()
        except Exception as exc:
            warnings.append({'resource':'entidades','error':'Consulta restrita à entidade ativa: '+str(exc)[:200]})

    def initial(glpi, tid, uid, record, save):
        ticket = glpi.get_ticket(tid)
        if int(ticket.get('status') or 0) >= 5 or not assigned(glpi, tid, uid):
            record['initial'] = 'ignorada: chamado solucionado ou atribuição alterada'
            return
        prefs = settings()
        context = {}
        template = prefs['initial_reply_template']
        if '{saudacao}' in template:
            hour = datetime.now(ZoneInfo(prefs['timezone'])).hour
            context['saudacao'] = 'Bom dia' if 5 <= hour < 12 else 'Boa tarde' if 12 <= hour < 18 else 'Boa noite'
        if '{tecnico}' in template:
            technician = prefs['contact_name'].strip()
            if not technician:
                try:
                    user = glpi.get('User/' + str(uid))
                    technician = ' '.join(str(user.get(k) or '').strip() for k in ('firstname', 'realname')).strip() or str(user.get('name') or '')
                except Exception:
                    technician = ''
            if not technician:
                technician = 'a equipe de suporte'
            context['tecnico'] = technician
        initial_reply.ensure(glpi, tid, uid, ticket, record, save, plain(ticket.get('content')), template, context)

    def prepare_contact(glpi, tid, uid, continuation=False):
        fresh = ticket_for_scan(glpi, tid)
        relations_now = glpi.ticket_users(tid)
        if int(fresh.get('status') or 0) not in (1, 2, 3, 4) or not any(
            int(r.get('users_id') or 0) == uid and int(r.get('type') or 0) == 2 for r in relations_now):
            raise ValueError('Chamado encerrado ou atribuição alterada; contato cancelado.')
        # Never choose silently among multiple requesters or destination numbers.
        if not contact_phones_from_text(fresh.get('content')) and len([r for r in relations_now if int(r.get('type') or 0) == 1]) > 1:
            raise ValueError('Mais de um requerente. Selecione o contato manualmente.')
        glpi._workbench_users = {}
        prefs = settings()
        people = requester_contacts(glpi, fresh, relations_now, tid, fresh.get('name', ''), prefs)
        people = [p for p in people if p.get('priority') == 'principal']
        if len(people) != 1 or any(p.get('ambiguous') for p in people):
            raise ValueError('Contato ausente ou ambíguo. Confira manualmente.')
        person = people[0]
        if person.get('phone_source') == 'descricao':
            person = {**person, 'name': ''}  # Do not address the recipient by the requester's name.
        phone = _whatsapp_digits(person.get('phone'), prefs['country_code'])
        if not phone:
            raise ValueError('Telefone incompleto. Corrija o cadastro e contate manualmente.')
        technician = prefs['contact_name'].strip()
        if not technician:
            user = glpi.get('User/' + str(uid))
            technician = ' '.join(str(user.get(k) or '').strip() for k in ('firstname', 'realname')).strip() or str(user.get('name') or '')
        if not technician:
            raise ValueError('Configure seu nome nas preferências de contato.')
        message = whatsapp_auto.render(prefs['continuation_message'] if continuation else prefs['contact_message'], {
            'nome': person['name'], 'tecnico': technician, 'chamado': tid,
            'assunto': plain(fresh.get('name')), 'empresa': overview(glpi, tid, [], fresh)['entity']['label']
        }, prefs['timezone'])
        return phone, message

    def sync():
        with SYNC_LOCK:
            cfg = settings()
            with client() as glpi:
                warnings = []
                all_entities(glpi, warnings)
                uid = glpi.current_user_id()
                key = 'workbench_' + scope(glpi)
                state = get_meta(key, {}) or {}
                records = state.setdefault('records', {})
                raw, field = options(glpi)
                # GLPI's native assigned-technician search option; fail closed on incompatible schema.
                opt = raw.get('5', {})
                if opt.get('table') != 'glpi_users' or opt.get('field') != 'name':
                    raise ValueError('Este GLPI não expõe o campo padrão 5 (técnico atribuído). Ajuste o adaptador antes de ativar o monitor.')
                status_field = field('glpi_tickets', 'status')
                ids, truncated = search_ids(glpi, [(5, 'equals', uid), equals_any(status_field, (1, 2, 3, 4))])
                if truncated:
                    raise ValueError('Mais de 500 chamados atribuídos. Nenhuma automação aplicada; refine o escopo do perfil GLPI.')
                wa_scope = scope(glpi)
                wa_new = whatsapp_auto.begin_scan(wa_scope, ids) if cfg['enabled'] else {}
                baseline = not state.get('initialized')
                now = time.time()
                previous = set(state.get('active_ids', []))
                save = lambda: set_meta(key, state)
                rows = []
                errors = []
                for tid in ids:
                    try:
                        ticket = ticket_for_scan(glpi, tid)
                        snap = overview(glpi, tid, warnings, ticket)
                        # A busca nativa já filtra o técnico. Ticket_User fica para
                        # contatos e é relido em TTL, não em todo ciclo da Central.
                        if snap['status'] >= 5:
                            continue
                        rec = records.get(str(tid))
                        if rec is None or (not baseline and tid not in previous):
                            rec = {'seen_at': now, 'baseline': baseline, 'initial': 'base existente' if baseline else 'aguardando'}
                            records[str(tid)] = rec
                        if not __import__('proactive').is_proactive(ticket) and not baseline and not rec['baseline'] and cfg['auto_initial'] and rec.get('initial') in ('aguardando', 'aguardando entrega', 'enviando', 'resultado incerto', 'resposta criada'):
                            try:
                                with LOCK:
                                    if settings()['auto_initial']: initial(glpi, tid, uid, rec, save)
                            except Exception as exc:
                                warnings.append({'ticket_id':tid,'resource':'T01','error':str(exc)[:300]})
                        if tid in wa_new and not __import__('proactive').is_proactive(ticket) and not self_only_ticket(glpi, ticket, uid):
                            whatsapp_auto.process(wa_scope, tid, lambda: prepare_contact(glpi, tid, uid), wa_new[tid])
                        # Reconcile an existing public reply independently of auto-creation.
                        if rec.get('initial_followup_id') and not rec.get('initial_receipt_id'):
                            try:
                                initial_reply.reconcile_receipt(glpi, tid, uid, rec, save)
                            except Exception as exc:
                                warnings.append({'ticket_id':tid,'resource':'T01 comprovante','error':str(exc)[:300]})
                        # Deep timeline is expensive in the real GLPI (~3 reads per ticket).
                        # Keep it authoritative, but reuse a recent result between monitor cycles.
                        activity_ttl = max(300, min(900, cfg['interval'] * 3))
                        activity_due = not rec.get('activity_checked_at') or now - rec['activity_checked_at'] >= activity_ttl
                        if activity_due:
                            tasks, follows, solutions = read_timeline(glpi, tid, warnings)
                            own = [stamp(x.get('date_creation') or x.get('date'), cfg['timezone'])
                                   for x in tasks + follows + solutions if int(x.get('users_id') or 0) == uid]
                            own.extend(stamp(x.get('date_mod'), cfg['timezone']) for x in tasks + follows + solutions if int(x.get('users_id_editor') or 0) == uid)
                            if int(snap['raw'].get('users_id_lastupdater') or 0) == uid:
                                own.append(stamp(snap['raw'].get('date_mod'), cfg['timezone']))
                            own = [x for x in own if x is not None]
                            last = max(own) if own else None
                            rec['last_own_update'] = last
                            rec['activity_checked_at'] = now
                        else:
                            last = rec.get('last_own_update')
                            if int(snap['raw'].get('users_id_lastupdater') or 0) == uid:
                                current = stamp(snap['raw'].get('date_mod'), cfg['timezone'])
                                if current is not None and (last is None or current > last):
                                    last = current
                                    rec['last_own_update'] = current
                        since = last if last is not None else rec['seen_at']
                        contacts_ttl = 1800
                        contact_revision = hashlib.sha256(str(snap['raw'].get('content') or '').encode()).hexdigest()
                        contacts_due = rec.get('contact_revision') != contact_revision or rec.get('contact_schema') != 3 or not rec.get('contacts_checked_at') or now - rec['contacts_checked_at'] >= contacts_ttl
                        if contacts_due:
                            try:
                                relations = glpi.ticket_users(tid)
                            except Exception as exc:
                                warnings.append({'ticket_id':tid,'resource':'Ticket_User','error':str(exc)[:300]})
                                relations = []
                            contacts = requester_contacts(glpi, snap['raw'], relations, tid, snap['title'], cfg)
                            rec['contacts'] = contacts
                            rec['contacts_checked_at'] = now
                            rec['contact_revision'] = contact_revision
                            rec['contact_schema'] = 3
                        else:
                            contacts = rec.get('contacts') or []
                        description = plain(snap['raw'].get('content'))
                        # The Central should let the technician understand the request before
                        # opening WhatsApp/GLPI. Keep the preview intentionally bounded so the
                        # monitor response stays light even when ticket descriptions are large.
                        if len(description) > 1800:
                            description = description[:1797].rstrip() + '…'
                        rows.append({'id': tid, 'title': snap['title'], 'description': description,
                                     'entity': snap['entity']['label'], 'entity_id': snap['entity_id'],
                                     'category': snap['category']['label'], 'status': snap['status'], 'priority': snap['priority'],
                                     'url': url(tid), 'contacts': contacts, **rec, 'last_own_update': last,
                                     'last_any_update': snap['raw'].get('date_mod'), 'stale_hours': max(0, (now-since)/3600),
                                     'stale': now-since >= cfg['stale_hours']*3600})
                    except Exception as exc:
                        errors.append({'ticket_id': tid, 'error': str(exc)[:500]})
                # Preserve failed ticket observations; absence from a successful full search alone ends an assignment.
                state.update(initialized=True, active_ids=ids, items=rows, last_sync=now, errors=errors, warnings=warnings, total_candidates=len(ids))
                save()
                set_meta('workbench_current', key)
                set_meta('workbench_config', config_identity())
                return {**state, 'records': None, 'settings': cfg}

    @app.get('/api/workbench')
    def get_workbench():
        key = get_meta('workbench_current', '')
        state = get_meta(key, {}) if key else {}
        if get_meta('workbench_config', '') != config_identity():
            state = {}
        return {**(state or {}), 'records': None, 'settings': settings(),
                'monitor_error': get_meta('workbench_error', ''),
                'last_attempt': get_meta('workbench_last_attempt', None)}

    @app.put('/api/workbench/settings')
    def save_settings(payload: Settings, request: Request):
        local_guard(request)
        # PUTs parciais vindos de testes/integrações não devem zerar preferências
        # já salvas para os defaults do modelo. A UI envia o objeto completo,
        # mas preservar campos omitidos torna o contrato mais seguro.
        merged = {**settings(), **payload.model_dump(exclude_unset=True)}
        try:
            validated = Settings(**merged)
            ZoneInfo(validated.timezone)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(400, 'Fuso horário ou preferências inválidas') from exc
        if not re.fullmatch(r'\d{1,3}', validated.country_code):
            raise HTTPException(400, 'DDI inválido')
        try:
            validated.initial_reply_template = initial_reply.validate_template(validated.initial_reply_template)
            validated.contact_message = validate_contact_template(validated.contact_message)
            validated.continuation_message = validate_contact_template(validated.continuation_message)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not validated.initial_reply_template.strip():
            raise HTTPException(400, 'O texto da resposta inicial não pode ficar vazio.')
        with SYNC_LOCK:
            with LOCK:
                if validated.enabled and not settings().get('enabled'):
                    whatsapp_auto.reset_monitor_baseline()
                set_meta('workbench_settings', validated.model_dump())
        return {'ok': True, 'settings': validated.model_dump()}

    @app.get('/api/workbench/contact-profile')
    def contact_profile():
        with client() as glpi:
            uid = glpi.current_user_id()
            try:
                user = glpi.get('User/' + str(uid))
                name = ' '.join(str(user.get(k) or '').strip() for k in ('firstname', 'realname')).strip()
                name = name or str(user.get('name') or '').strip()
            except Exception:
                name = ''
            return {'user_id': uid, 'name': name, 'source': 'GLPI' if name else 'unavailable'}

    @app.post('/api/workbench/sync')
    def sync_route(request: Request):
        local_guard(request)
        set_meta('workbench_last_attempt', time.time())
        try:
            result = sync()
            set_meta('workbench_error', '')
            return result
        except Exception as exc:
            set_meta('workbench_error', str(exc)[:500])
            raise HTTPException(502, str(exc)) from exc

    @app.get('/api/workbench/entities')
    def entities():
        with client() as glpi:
            return {'items': [{'id': int(e['id']), 'name': plain(e.get('completename') or e.get('name'))} for e in glpi.entity_rows()]}

    @app.get('/api/workbench/diagnostics/{ticket_id}')
    def read_diagnostics(ticket_id: int):
        if ticket_id<=0: raise HTTPException(400,'Chamado inválido')
        with client() as glpi:
            results=[]
            uid=glpi.current_user_id()
            try:
                ticket=glpi.activate_context_for_ticket(ticket_id)
                results.append({'resource':'Ticket','ok':True,'status':ticket.get('status'),'entity_id':ticket.get('entities_id')})
            except Exception as exc:
                return {'ticket_id':ticket_id,'user_id':uid,'checks':[{'resource':'Ticket','ok':False,'error':str(exc)[:400]}]}
            for kind in ('Ticket_User','Group_Ticket','TicketTask','ITILFollowup','ITILSolution','Log'):
                try:
                    values=glpi.list_subitems('Ticket',ticket_id,kind)
                    result={'resource':kind,'ok':True,'count':len(values)}
                    if kind=='TicketTask':result['recorded_seconds']=sum(int(x.get('actiontime') or 0) for x in values)
                    if kind=='Log':
                        _,field=options(glpi)
                        result['closing_actor_matches_user']=closing_actor(values,ticket_id,field('glpi_tickets','status'))==uid
                        result['status_values']=[{'new_value':x.get('new_value'),'new_id':x.get('new_id'),'author_has_id':bool(re.search(r' \((\d+)\)$',str(x.get('user_name') or '')))} for x in values if int(x.get('id_search_option') or 0)==field('glpi_tickets','status')][-5:]
                    results.append(result)
                except Exception as exc: results.append({'resource':kind,'ok':False,'error':str(exc)[:400]})
            return {'ticket_id':ticket_id,'user_id':uid,'checks':results,'note':'Sem tokens, texto do chamado, nomes ou anexos.'}

    @app.get('/api/workbench/categories')
    def category_options(entity_id: int = -1, ticket_id: int = 0):
        if entity_id<0 and ticket_id<=0: raise HTTPException(400,'Selecione uma empresa ou informe um chamado')
        with client() as glpi:
            if ticket_id>0:
                ticket=glpi.activate_context_for_ticket(ticket_id)
                entity_id=int(ticket['entities_id'])
            glpi.change_active_entity(entity_id,recursive=False)
            rows=glpi.list_all('ITILCategory')
            return {'items':[{'id':int(x['id']),'name':plain(x.get('completename') or x.get('name'))} for x in rows]}

    @app.get('/api/workbench/my-tickets')
    def my_tickets(view: str = 'assigned', q: str = '', entity_id: int = -1,
                   status: int = 0, days: int = 365, offset: int = 0, stale_only: bool = False):
        if view not in ('assigned','solved','closed') or len(q)>200 or status not in range(5) or not 0<=days<=3650 or not 0<=offset<=100000:
            raise HTTPException(400,'Filtro inválido')
        cfg=settings()
        with client() as glpi:
            entity_scope=''
            if entity_id>=0:
                glpi.change_active_entity(entity_id, recursive=False)
            else:
                try: glpi.change_active_entities_all()
                except Exception:
                    entity_scope=' A API não permitiu ampliar as entidades; resultados limitados à entidade ativa da sessão.'
            uid=glpi.current_user_id()
            raw,field=options(glpi)
            status_field=field('glpi_tickets','status')
            closure_view=view in ('solved','closed')
            target_status=5 if view=='solved' else 6 if view=='closed' else None
            if view=='assigned':
                # "Minha fila" means active tickets that are still assigned to the
                # authenticated technician.  Status 5 belongs in Fechamentos.
                criteria=[equals_any(status_field,(1,2,3,4))]
                if raw.get('5',{}).get('table')!='glpi_users':
                    raise HTTPException(400,'Filtro de técnico atribuído indisponível nesta instalação')
                criteria.append((5,'equals',uid))
                if status:
                    criteria.append((status_field,'equals',status))
                sort_field=field('glpi_tickets','date_mod')
            else:
                criteria=[(status_field,'equals',target_status)]
                date_name='solvedate' if view=='solved' else 'closedate'
                date_field=field('glpi_tickets',date_name)
                tz=ZoneInfo(cfg['timezone'])
                if days==0:
                    start_today=datetime.now(tz).replace(hour=0,minute=0,second=0,microsecond=0)
                    cutoff=start_today.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    cutoff=datetime.fromtimestamp(time.time()-days*86400,tz).strftime('%Y-%m-%d %H:%M:%S')
                criteria.append((date_field,'morethan',cutoff))
                sort_field=date_field
            if entity_id>=0:
                criteria.append((field('glpi_entities','completename'),'equals',entity_id))
            exact_requested = int(q.strip().lstrip('#')) if q.strip().lstrip('#').isdigit() else None
            if exact_requested is not None:
                criteria.append(exact_ticket_criterion(raw,field('glpi_tickets','id'),exact_requested))
            ids,total,next_offset=search_page(glpi,criteria,offset,sort_field=sort_field)
            if exact_requested is not None:
                ids=[tid for tid in ids if tid==exact_requested]
            terms=re.findall(r'\w+',norm(q))
            deep_read=bool(terms) or (view=='assigned' and stale_only)
            records=(get_meta('workbench_'+scope(glpi),{}) or {}).get('records',{})
            rows,errors,unverified=[],[],0
            warnings=[]
            for tid in ids:
                try:
                    ticket=ticket_for_scan(glpi,tid)
                    current_status=int(ticket.get('status') or 0)
                    logs=[]
                    if entity_id>=0 and int(ticket.get('entities_id') or 0)!=entity_id:
                        continue
                    if view=='assigned':
                        if current_status not in (1,2,3,4):
                            continue
                        if status and current_status!=status:
                            continue
                    else:
                        if current_status!=target_status:
                            continue
                        own_solution=None
                        try:
                            own_solution=own_solution_info(glpi,tid,uid,cfg['timezone'])
                        except Exception as exc:
                            warnings.append({'ticket_id':tid,'resource':'ITILSolution','error':str(exc)[:300]})
                        solved_by_user=bool(own_solution)
                        transition_actor=None
                        if not solved_by_user:
                            try:
                                logs=glpi.list_subitems('Ticket',tid,'Log')
                                transition_actor=status_transition_actor(logs,tid,status_field,5)
                            except Exception as exc:
                                warnings.append({'ticket_id':tid,'resource':'Log','error':str(exc)[:300]})
                            solved_by_user=transition_actor==uid
                        if not solved_by_user:
                            unverified+=1
                            continue
                    tasks,follows,solutions=(read_timeline(glpi,tid,warnings) if deep_read else ([],[],[]))
                    snap=overview(glpi,tid,warnings,ticket)
                    sections=[('Assunto',plain(ticket.get('name'))),('Descrição',plain(ticket.get('content')))]
                    if deep_read:
                        sections += [('Tarefa #'+str(t['id']),plain(t.get('content'))) for t in tasks]
                        sections += [('Acompanhamento',plain(t.get('content'))) for t in follows]
                        sections += [('Solução',plain(t.get('content'))) for t in solutions]
                    elif closure_view and own_solution and own_solution.get('content'):
                        sections.append(('Solução',own_solution['content']))
                    searchable=norm(' '.join([str(tid),snap['entity']['label'],snap['category']['label']]+[v for _,v in sections]))
                    if terms and not all(term in searchable for term in terms):
                        continue
                    last=None
                    if view=='assigned':
                        own=[stamp(t.get('date_creation') or t.get('date'),cfg['timezone']) for t in tasks+follows+solutions if int(t.get('users_id') or 0)==uid]
                        own.extend(stamp(t.get('date_mod'),cfg['timezone']) for t in tasks+follows+solutions if int(t.get('users_id_editor') or 0)==uid)
                        if deep_read:
                            try: logs=glpi.list_subitems('Ticket',tid,'Log')
                            except Exception: logs=[]
                        for entry in logs:
                            author=re.search(r' \((\d+)\)$',str(entry.get('user_name') or ''))
                            if author and int(author[1])==uid:
                                own.append(stamp(entry.get('date_mod'),cfg['timezone']))
                        if int(ticket.get('users_id_lastupdater') or 0)==uid:
                            own.append(stamp(ticket.get('date_mod'),cfg['timezone']))
                        if not deep_read:
                            cached=records.get(str(tid),{}).get('last_own_update')
                            if cached is not None:
                                own.append(cached)
                        own=[t for t in own if t is not None]
                        last=max(own) if own else None
                        stale_since=last if last is not None else records.get(str(tid),{}).get('seen_at')
                        if stale_only and (stale_since is None or time.time()-stale_since<cfg['stale_hours']*3600):
                            continue
                    match=next(((kind,text) for kind,text in sections if terms and any(term in norm(text) for term in terms)),('Descrição',plain(ticket.get('content'))))
                    event_at=None
                    authorship=''
                    closure_state=''
                    solution_at=None
                    if view=='solved':
                        event_at=stamp(ticket.get('solvedate'),cfg['timezone'])
                        solution_at=(own_solution or {}).get('date')
                        authorship='Solução registrada por você' if own_solution else 'Solução por você confirmada no histórico'
                        closure_state='Aguardando aprovação ou fechamento'
                    elif view=='closed':
                        event_at=stamp(ticket.get('closedate'),cfg['timezone'])
                        solution_at=(own_solution or {}).get('date')
                        authorship='Solução técnica registrada por você' if own_solution else 'Solução por você confirmada no histórico'
                        closure_state='Fechado · solução aprovada/encerrada no GLPI'
                    rows.append({'id':tid,'title':plain(ticket.get('name')),'entity':snap['entity']['label'],'entity_id':snap['entity_id'],
                                 'category':snap['category']['label'],'status':ticket.get('status'),'url':url(tid),
                                 'last_any_update':stamp(ticket.get('date_mod'),cfg['timezone']),'last_own_update':last,
                                 'assigned_seen_at':records.get(str(tid),{}).get('seen_at'),
                                 'solved_at':stamp(ticket.get('solvedate'),cfg['timezone']),
                                 'closed_at':stamp(ticket.get('closedate'),cfg['timezone']),
                                 'event_at':event_at,'solution_at':solution_at,'approval_at':(own_solution or {}).get('approved_at') if closure_view else None,'authorship':authorship,'closure_state':closure_state,
                                 'match_source':match[0],'excerpt':match[1][:420],
                                 'activity_complete':deep_read,
                                 'task_count':len(tasks) if deep_read else None})
                except Exception as exc:
                    errors.append({'ticket_id':tid,'error':str(exc)})
            exact_verified = len(rows) if next_offset is None else None
            if view=='assigned':
                scope_text='Somente chamados em status Novo, Atribuído, Planejado ou Pendente que a busca nativa do GLPI relaciona ao seu usuário.'
            else:
                state_label='solucionados' if view=='solved' else 'fechados'
                scope_text=f'Chamados {state_label} no período, filtrados pela sua autoria técnica da solução. Fechados representam soluções já aprovadas/encerradas.'
            return {'items':rows,'view':view,'total_candidates':total,'verified_total':exact_verified,'scanned':len(ids),'next_offset':next_offset,
                    'unverified_closures':unverified,'errors':errors,'warnings':warnings,'stale_hours':cfg['stale_hours'],
                    'scope':scope_text+(' Pesquisa profunda em tarefas, acompanhamentos e soluções.' if deep_read else '')+entity_scope}

    @app.get('/api/workbench/company-search')
    def company_search(entity_id: int = -1, ticket_id: int = 0, q: str = '', status: int = 0, category: int = 0, days: int = 365, offset: int = 0):
        if offset < 0 or offset > 100000 or len(q) > 200 or not 1 <= days <= 3650 or status not in range(7) or category < 0:
            raise HTTPException(400, 'Filtro inválido')
        with client() as glpi:
            if ticket_id:
                base_ticket = glpi.activate_context_for_ticket(ticket_id)
                entity_id = int(base_ticket.get('entities_id') or 0)
            elif entity_id >= 0:
                glpi.change_active_entity(entity_id, recursive=False)
            else:
                raise HTTPException(400, 'Selecione uma empresa ou informe um chamado')
            _, field = options(glpi)
            cutoff = datetime.fromtimestamp(time.time()-days*86400, ZoneInfo(settings()['timezone'])).strftime('%Y-%m-%d %H:%M:%S')
            criteria = [(field('glpi_entities', 'completename'), 'equals', entity_id),
                        (field('glpi_tickets', 'date_mod'), 'morethan', cutoff)]
            if status: criteria.append((field('glpi_tickets','status'),'equals',status))
            if category: criteria.append((field('glpi_itilcategories','completename'),'equals',category))
            terms=[t for t in norm(q).split() if t not in {'de','da','do','das','dos','a','o','e','em','para'}]
            raw=glpi.list_search_options('Ticket')
            text_fields=[int(k) for k,v in raw.items() if str(k).isdigit() and isinstance(v,dict) and
                         ((v.get('table')=='glpi_tickets' and v.get('field') in ('name','content')) or
                          (v.get('table') in ('glpi_tickettasks','glpi_itilfollowups','glpi_itilsolutions') and v.get('field')=='content'))]
            # If the API does not expose task search, keep full paginated inspection rather than exclude matches.
            indexed=all(any(isinstance(v,dict) and v.get('table')==table and v.get('field')=='content' for v in raw.values())
                        for table in ('glpi_tickets','glpi_tickettasks','glpi_itilfollowups','glpi_itilsolutions'))
            exact_id=q.strip().lstrip('#')
            exact_requested = int(exact_id) if exact_id.isdigit() else None
            if exact_requested is not None:
                criteria.append(exact_ticket_criterion(raw,field('glpi_tickets','id'),exact_requested))
                terms=[]
            if indexed:
                for term in terms:
                    criteria.append({'link':'AND','criteria':[{'link':'OR' if i else 'AND','field':f,'searchtype':'contains','value':term} for i,f in enumerate(text_fields)]})
            ids,total,next_offset=search_page(glpi,criteria,offset,sort_field=field('glpi_tickets','date_mod'))
            if exact_requested is not None:
                ids = [tid for tid in ids if tid == exact_requested]
            truncated=next_offset is not None
            rows, counts, errors = [], {}, []
            for tid in ids:
                try:
                    t = glpi.get_ticket(tid)
                    if int(t.get('entities_id') or 0) != entity_id:
                        continue
                    cid = int(t.get('itilcategories_id') or 0)
                    counts[cid] = counts.get(cid, 0) + 1
                    if (status and int(t.get('status') or 0) != status) or (category and cid != category):
                        continue
                    content = plain(t.get('content'))
                    task_text = ''
                    title = plain(t.get('name'))
                    if terms and not all(term in norm(title+' '+content) for term in terms):
                        detail_warnings=[]
                        tasks,follows,solutions=read_timeline(glpi,tid,detail_warnings)
                        errors.extend(detail_warnings)
                        task_text = ' '.join(plain(x.get('content')) for x in tasks+follows+solutions)
                        haystack = norm(title + ' ' + content + ' ' + task_text)
                        if not all(term in haystack for term in terms):
                            continue
                    excerpt = content
                    if terms and not all(term in norm(title + ' ' + content) for term in terms):
                        excerpt = task_text
                    rows.append({'id': tid, 'title': title, 'status': t.get('status'), 'category_id': cid,
                                 'date_mod': t.get('date_mod'), 'url': url(tid), 'excerpt': excerpt[:500]})
                except Exception as exc:
                    errors.append({'ticket_id': tid, 'error': str(exc)})
            categories = []
            for cid, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                label = 'Sem categoria'
                if cid:
                    try:
                        c = glpi.get('ITILCategory/' + str(cid))
                        label = plain(c.get('completename') or c.get('name'))
                    except Exception:
                        label = f'Categoria #{cid}'
                categories.append({'id': cid, 'name': label, 'count': count})
            return {'items': sorted(rows, key=lambda x: x.get('date_mod') or '', reverse=True), 'categories': categories,
                    'entity_id': entity_id, 'scanned': len(ids), 'total_candidates':total, 'next_offset':next_offset, 'truncated': truncated, 'errors': errors,
                    'scope': 'Mesma entidade e período. Busca paginada sem corte nos primeiros 200 chamados. Categorias representam os candidatos examinados nesta página. '+('Filtro de conteúdo aplicado pelo GLPI.' if indexed else 'Pesquisa de conteúdo examinada por página; continue até concluir.')}

    @app.get('/api/workbench/recent-edits')
    def recent_edits():
        with client() as glpi:
            warnings=[]
            all_entities(glpi,warnings)
            _, field = options(glpi)
            try:
                raw = glpi.list_search_options('Ticket')
                last_editor = next(int(k) for k,v in raw.items() if isinstance(v, dict) and
                                   v.get('linkfield') == 'users_id_lastupdater' and str(k).isdigit())
                criteria = [(last_editor, 'equals', glpi.current_user_id())]
                label = 'Chamados cujo último editor é você, ordenados pela atualização. Tarefas exibidas pertencem a esses chamados.'
            except (ValueError, StopIteration):
                criteria = [(5, 'equals', glpi.current_user_id())]
                label = 'Seu GLPI não expôs o filtro de último editor. Exibindo atividade recente dos chamados atribuídos a você; pode incluir edições de outras pessoas.'
            ids, truncated = search_ids(glpi, criteria, limit=20, sort_field=field('glpi_tickets', 'date_mod'))
            rows, errors = [], []
            for tid in ids:
                try:
                    t = ticket_for_scan(glpi,tid)
                    rows.append({'id': tid, 'title': plain(t.get('name')), 'date_mod': t.get('date_mod'), 'url': url(tid)})
                except Exception as exc:
                    errors.append({'ticket_id': tid, 'error': str(exc)})
            rows.sort(key=lambda x: x.get('date_mod') or '', reverse=True)
            rows = rows[:20]
            for row in rows:
                try:
                    ticket_for_scan(glpi,row['id'])
                    tasks = sorted(glpi.ticket_tasks(row['id']), key=lambda t: t.get('date_mod') or t.get('date') or '', reverse=True)
                    row['tasks'] = [{'id': t['id'], 'ticket_id': row['id'], 'text': plain(t.get('content'))[:180],
                                     'state': t.get('state'), 'date': t.get('date_mod') or t.get('date')} for t in tasks[:5]]
                    row['task_count'] = len(tasks)
                except Exception as exc:
                    row['tasks'] = []
                    errors.append({'ticket_id': row['id'], 'error': str(exc)})
            return {'items': rows, 'scope': label, 'truncated': truncated, 'errors': errors,
                    'scanned': len(ids)}

    @app.get('/api/workbench/similar/{ticket_id}')
    def similar(ticket_id: int, q: str = '', status: int = 0, category: int = 0, days: int = 365):
        if len(q) > 200 or days < 1 or days > 3650 or status not in range(7):
            raise HTTPException(400, 'Filtro inválido')
        with client() as glpi:
            ticket = glpi.activate_context_for_ticket(ticket_id)
            _, field = options(glpi)
            # Strict entity boundary is mandatory; references never imply resolution or company identity across entities.
            criteria = [(field('glpi_entities', 'completename'), 'equals', ticket.get('entities_id', 0))]
            if status:
                criteria.append((field('glpi_tickets', 'status'), 'equals', status))
            if category:
                criteria.append((field('glpi_itilcategories', 'completename'), 'equals', category))
            if q.strip():
                criteria.append((field('glpi_tickets', 'name'), 'contains', q.strip()))
            cutoff = datetime.fromtimestamp(time.time()-days*86400, ZoneInfo(settings()['timezone'])).strftime('%Y-%m-%d %H:%M:%S')
            criteria.append((field('glpi_tickets', 'date_mod'), 'morethan', cutoff))
            ids, truncated = search_ids(glpi, criteria, limit=200)
            words = set(re.findall(r'\w{3,}', norm(q or ticket.get('name')))) - {'para', 'com', 'uma', 'dos', 'das'}
            rows = []
            for tid in ids:
                if tid == ticket_id:
                    continue
                other = glpi.get_ticket(tid)
                if int(other.get('entities_id') or 0) != int(ticket.get('entities_id') or 0):
                    continue
                tokens = set(re.findall(r'\w{3,}', norm(other.get('name'))))
                score = len(words & tokens)/max(1, len(words | tokens))
                hint = get_meta('browser_context_' + str(tid), {}) or {}
                hint_words = set(re.findall(r'\w{3,}', norm(hint.get('text', '')))) if hint.get('entity_id') == ticket.get('entities_id') else set()
                context_match = bool(words & hint_words)
                if context_match:
                    score = max(score, .35 * len(words & hint_words)/max(1, len(words)))
                if score == 0 and not q:
                    continue
                rows.append({'id': tid, 'title': plain(other.get('name')), 'status': other.get('status'), 'score': round(score*100), 'context_match': context_match,
                             'date_mod': other.get('date_mod'), 'url': url(tid), 'excerpt': plain(other.get('content'))[:500]})
            return {'items': sorted(rows, key=lambda x: x['score'], reverse=True)[:30], 'truncated': truncated,
                    'scope': 'Mesma entidade GLPI; sem equivalência automática entre entidades e empresas.', 'scanned': len(ids)}

    @app.post('/api/workbench/solution/plan')
    def solution_plan(payload: SolutionReview, request: Request):
        local_guard(request)
        if payload.target not in ('solve', 'close') or len({i.ticket_id for i in payload.items}) != len(payload.items):
            raise HTTPException(400, 'Destino inválido ou chamado repetido')
        with LOCK, client() as glpi:
            items = []
            for item in payload.items:
                ticket = glpi.activate_context_for_ticket(item.ticket_id)
                tasks, follows, solutions = timeline(glpi, item.ticket_id)
                if 'backup' in norm(ticket.get('name')):
                    pending = [str(t['id']) for t in tasks if int(t.get('state') or 0) != 2]
                    if pending:
                        raise HTTPException(409, f"#{item.ticket_id}: conferência de backup com tarefas pendentes: {', '.join(pending)}. Conclua as verificações antes de fechar.")
                if int(ticket.get('status') or 0) == 6:
                    raise HTTPException(409, f'#{item.ticket_id} já está fechado')
                if not assigned(glpi, item.ticket_id, glpi.current_user_id()):
                    raise HTTPException(403, f'#{item.ticket_id} não está atribuído ao usuário da API')
                if not plain(item.content).strip():
                    raise HTTPException(400, 'Solução vazia')
                if int(ticket.get('status') or 0) < 5 and any(plain(s.get('content')) == plain(item.content) for s in solutions):
                    raise HTTPException(409, f'#{item.ticket_id} já contém esta solução, mas ainda não está solucionado. Verifique o GLPI antes de repetir.')
                recorded_seconds = sum(int(t.get('actiontime') or 0) for t in tasks)
                if int(ticket.get('status') or 0) < 5 and recorded_seconds <= 0:
                    raise HTTPException(
                        409,
                        f'#{item.ticket_id}: este fluxo exige duração antes de solucionar ou fechar. '
                        'Registre as tarefas com o tempo real e gere nova revisão.',
                    )
                items.append({**item.model_dump(), 'title': plain(ticket.get('name')), 'status': ticket.get('status'),
                              'recorded_seconds': recorded_seconds,
                              'hash': fingerprint(ticket, tasks, follows, solutions)})
            plan_id = secrets.token_urlsafe(24)
            plan = {'plan_id': plan_id, 'scope': scope(glpi), 'target': payload.target, 'items': items, 'expires': time.time()+600, 'used': False}
            set_meta('solution_plan_' + plan_id, plan)
            return plan

    @app.post('/api/workbench/solution/apply')
    def solution_apply(payload: ApplyReview, request: Request):
        local_guard(request)
        with LOCK, client() as glpi:
            key = 'solution_plan_' + payload.plan_id
            plan = get_meta(key, {}) or {}
            if not plan or plan['used'] or plan['expires'] < time.time() or plan['scope'] != scope(glpi):
                raise HTTPException(409, 'Revisão vencida ou já utilizada. Atualize os chamados e revise novamente.')
            # Validate the entire batch before its first mutation.
            for item in plan['items']:
                ticket = glpi.activate_context_for_ticket(item['ticket_id'])
                if fingerprint(ticket, *timeline(glpi, item['ticket_id'])) != item['hash']:
                    raise HTTPException(409, f"#{item['ticket_id']} mudou desde a revisão. Gere nova revisão.")
            plan['used'] = True
            set_meta(key, plan)
            results = []
            for item in plan['items']:
                tid = item['ticket_id']
                try:
                    glpi.activate_context_for_ticket(tid)
                    if not assigned(glpi, tid, glpi.current_user_id()):
                        raise ValueError('Atribuição mudou antes da aplicação')
                    current = glpi.get_ticket(tid)
                    if fingerprint(current, *timeline(glpi, tid)) != item['hash']:
                        raise ValueError('Chamado mudou durante a execução do lote')
                    if int(current.get('status') or 0) < 5:
                        glpi.post('ITILSolution', {'input': {'itemtype': 'Ticket', 'items_id': tid,
                                  'content': '<p>'+html.escape(item['content']).replace('\n', '<br>')+'</p>'}})
                    if plan['target'] == 'close':
                        current = glpi.get_ticket(tid)
                        if int(current.get('status') or 0) != 5:
                            raise ValueError('GLPI não confirmou o estado Solucionado; fechamento interrompido')
                        glpi.put(f'Ticket/{tid}', {'input': {'id': tid, 'status': 6}})
                    status = int(glpi.get_ticket(tid).get('status') or 0)
                    expected = 6 if plan['target'] == 'close' else 5
                    if status != expected:
                        raise ValueError(f'GLPI retornou estado {status}, esperado {expected}. Verifique permissões e campos obrigatórios.')
                    results.append({'ticket_id': tid, 'ok': True, 'status': status})
                except Exception as exc:
                    results.append({'ticket_id': tid, 'ok': False, 'error': str(exc), 'check_before_retry': True})
                    # Stop on uncertain outcome, preserving remaining items without writing.
                    for remaining in plan['items'][len(results):]:
                        results.append({'ticket_id': remaining['ticket_id'], 'ok': False, 'error': 'Não executado: lote interrompido'})
                    break
            history = get_meta('workbench_history', []) or []
            history.insert(0, {'at': time.time(), 'target': plan['target'], 'results': results})
            set_meta('workbench_history', history[:100])
            return {'ok': all(i['ok'] for i in results), 'results': results}

    @app.get('/api/workbench/history')
    def history():
        return {'items': get_meta('workbench_history', []) or []}

    @app.get('/api/bridge/glpi-origin')
    def glpi_origin(request: Request):
        bridge_guard(request)
        return {'url': (load_config() or {}).get('url', '')}

    @app.post('/api/bridge/context')
    def context(payload: BrowserContext, request: Request):
        bridge_guard(request)
        configured = urlsplit((load_config() or {}).get('url', ''))
        incoming = urlsplit(payload.url)
        if (incoming.scheme, incoming.netloc) != (configured.scheme, configured.netloc):
            raise HTTPException(400, 'A página não corresponde ao servidor GLPI configurado')
        # Check access via API before accepting a hint from a web page.
        with client() as glpi:
            ticket = glpi.activate_context_for_ticket(payload.ticket_id)
            set_meta('browser_context_' + str(payload.ticket_id), {**payload.model_dump(), 'at': time.time(), 'entity_id': ticket.get('entities_id')})
        return {'ok': True, 'ticket_id': payload.ticket_id}

    @app.get('/api/workbench/context/{ticket_id}')
    def read_context(ticket_id: int):
        with client() as glpi:
            glpi.activate_context_for_ticket(ticket_id)
        return get_meta('browser_context_' + str(ticket_id), {}) or {}

    def worker():
        # Primeira leitura rápida após o serviço subir. Antes da 3.1 a Central
        # aguardava o intervalo inteiro (120 s por padrão), parecendo inativa.
        first = True
        while not STOP.wait(2 if first else settings()['interval']):
            first = False
            if settings()['enabled'] and load_config():
                set_meta('workbench_last_attempt', time.time())
                try:
                    sync()
                    set_meta('workbench_error', '')
                except Exception as exc:
                    set_meta('workbench_error', str(exc)[:500])

    def start():
        STOP.clear()
        if not get_meta('workbench_3_3_2_refresh', False):
            saved = get_meta('workbench_settings', {}) or {}
            if saved.get('interval', 120) == 120:
                saved['interval'] = 30
                set_meta('workbench_settings', saved)
            set_meta('workbench_3_3_2_refresh', True)
        # A rc1 desligou auto_initial uma única vez como trava de homologação.
        # Na rc2 a T01 automática volta a ser o comportamento esperado. A
        # primeira sincronização continua sendo apenas baseline, portanto não
        # cria T01 retroativa para chamados que já estavam atribuídos.
        migration_key = 'workbench_3_1_rc2_auto_initial_applied'
        if not get_meta(migration_key, False):
            saved = get_meta('workbench_settings', {}) or {}
            if get_meta('workbench_3_1_rc1_safety_applied', False) and saved.get('auto_initial') is False:
                saved['auto_initial'] = True
                set_meta('workbench_settings', saved)
            set_meta(migration_key, True)
        threading.Thread(target=worker, daemon=True, name='glpi-monitor').start()

    def stop():
        STOP.set()

    from contextlib import asynccontextmanager
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def monitor_lifespan(application):
        async with previous_lifespan(application) as state:
            start()
            try:
                yield state
            finally:
                stop()

    app.router.lifespan_context = monitor_lifespan
