"""Review and enrich existing template tasks without creating duplicates."""
import hashlib
import html
import json
import secrets
import tempfile
import time
from pathlib import Path
from fastapi import Form, File, UploadFile, Request, HTTPException
from store import get_meta, set_meta
from workbench import LOCK, plain
from evidence_bridge import image_type


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def register(app, client, guard):
    @app.get('/api/templates/{ticket_id}')
    def tasks(ticket_id: int):
        with client() as glpi:
            ticket = glpi.activate_context_for_ticket(ticket_id)
            rows = glpi.ticket_tasks(ticket_id)
            tasks_out = []
            document_cache = {}
            for t in rows:
                task_id = int(t.get('id') or 0)
                documents = []
                if task_id:
                    try:
                        links = glpi.task_documents(task_id)
                    except Exception:
                        links = []
                    for link in links[:20]:
                        did = int(link.get('documents_id') or 0)
                        if not did:
                            continue
                        if did not in document_cache:
                            try:
                                doc = glpi.document(did)
                                document_cache[did] = {
                                    'id': did,
                                    'name': plain(doc.get('name') or doc.get('filename') or f'Documento {did}'),
                                    'filename': plain(doc.get('filename') or ''),
                                }
                            except Exception:
                                document_cache[did] = {'id': did, 'name': f'Documento {did}', 'filename': ''}
                        documents.append(document_cache[did])
                tasks_out.append({
                    'id': task_id,
                    'text': plain(t.get('content')),
                    'state': t.get('state'),
                    'actiontime': t.get('actiontime'),
                    'documents': documents,
                })
            return {
                'ticket_id': ticket_id,
                'title': plain(ticket.get('name')),
                'suggested': 'backup' in plain(ticket.get('name')).lower() and bool(rows),
                'tasks': tasks_out,
            }

    def read_files(files):
        if len(files) > 30:
            raise HTTPException(413, 'Limite de 30 imagens')
        result, total = [], 0
        for f in files:
            data = f.file.read(8*1024*1024+1)
            total += len(data)
            if len(data) > 8*1024*1024 or total > 20*1024*1024:
                raise HTTPException(413, 'Limite de 8 MiB por imagem e 20 MiB por envio')
            ext = image_type(data)
            if not ext:
                raise HTTPException(400, 'Formato de imagem inválido')
            result.append({'name': Path(f.filename or 'print').stem[:100]+'.'+ext, 'data': data, 'hash': hashlib.sha256(data).hexdigest()})
        return result

    @app.post('/api/templates/plan')
    def plan(request: Request, ticket_id: int = Form(...), edits: str = Form(...), files: list[UploadFile] = File(default=[])):
        guard(request)
        try:
            changes = json.loads(edits)
            if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
                raise ValueError('Selecione entre 1 e 30 tarefas existentes')
            images = read_files(files)
            with LOCK, client() as glpi:
                ticket = glpi.activate_context_for_ticket(ticket_id)
                if int(ticket.get('status') or 0) >= 5:
                    raise ValueError('Chamado solucionado/fechado: reabra pelo GLPI antes de editar')
                rows, seen, indexes = [], set(), []
                for change in changes:
                    tid = int(change['task_id'])
                    if tid in seen:
                        raise ValueError('Tarefa repetida')
                    seen.add(tid)
                    task = glpi.ticket_task(tid)
                    if int(task.get('tickets_id') or 0) != ticket_id:
                        raise ValueError('Tarefa pertence a outro chamado')
                    text = str(change.get('text', ''))
                    actiontime=change.get('actiontime')
                    if actiontime is not None and (type(actiontime) is not int or not 0<=actiontime<=31536000):
                        raise ValueError('Informe duração real válida em segundos')
                    complete = change.get('complete', False)
                    if type(complete) is not bool:
                        raise ValueError('A confirmação de conclusão deve ser verdadeira ou falsa')
                    if not text.strip() or len(text) > 50000:
                        raise ValueError('Texto inválido')
                    ix = change.get('files', [])
                    if any(type(i) is not int or i < 0 or i >= len(images) for i in ix):
                        raise ValueError('Associação de arquivo inválida')
                    indexes.extend(ix)
                    rows.append({'task_id': tid, 'text': text, 'hash': digest(task), 'original': task.get('content', ''),
                                 'edited': text != plain(task.get('content')), 'files': ix,
                                 'complete': complete, 'actiontime':actiontime, 'original_state': int(task.get('state') or 0)})
                if sorted(indexes) != list(range(len(images))):
                    raise ValueError('Associe cada print exatamente uma vez')
                plan_id = secrets.token_urlsafe(24)
                p = {'id': plan_id, 'ticket_id': ticket_id, 'user_id': glpi.current_user_id(), 'base': glpi.base,
                     'ticket_hash': digest(ticket), 'rows': rows, 'files': [{'name': i['name'], 'hash': i['hash']} for i in images],
                     'expires': time.time()+600, 'used': False, 'entity_id': ticket.get('entities_id', 0)}
                set_meta('template_plan_'+plan_id, p)
                return p
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/templates/apply')
    def apply(request: Request, plan_id: str = Form(...), files: list[UploadFile] = File(default=[])):
        guard(request)
        images = read_files(files)
        with LOCK, client() as glpi:
            p = get_meta('template_plan_'+plan_id, {}) or {}
            if not p or p['used'] or p['expires'] < time.time() or p['user_id'] != glpi.current_user_id() or p['base'] != glpi.base:
                raise HTTPException(409, 'Revisão vencida ou já usada')
            if [i['hash'] for i in images] != [i['hash'] for i in p['files']]:
                raise HTTPException(409, 'Os prints mudaram desde a revisão')
            ticket = glpi.activate_context_for_ticket(p['ticket_id'])
            if digest(ticket) != p['ticket_hash']:
                raise HTTPException(409, 'Chamado mudou; revise novamente')
            for row in p['rows']:
                if digest(glpi.ticket_task(row['task_id'])) != row['hash']:
                    raise HTTPException(409, 'Uma tarefa mudou; revise novamente')
            p['used'] = True
            set_meta('template_plan_'+plan_id, p)
            results = []
            with tempfile.TemporaryDirectory(prefix='glpi-template-') as tmp:
                for row in p['rows']:
                    documents = []
                    try:
                        content = '<p>'+html.escape(row['text']).replace('\n', '<br>')+'</p>' if row['edited'] else row['original']
                        for i in row['files']:
                            path = Path(tmp) / f"{i:02d}-{images[i]['name']}"
                            path.write_bytes(images[i]['data'])
                            doc = glpi.upload_document(path, p['entity_id'])
                            documents.append(int(doc['id']))
                            glpi.link_document_to_task(int(doc['id']), row['task_id'])
                            src = f"/front/document.send.php?docid={int(doc['id'])}&itemtype=Ticket&items_id={p['ticket_id']}"
                            content += f'<p><img src="{html.escape(src, quote=True)}" alt="{html.escape(images[i]["name"], quote=True)}"></p>'
                        if row['edited'] or row['files']:
                            glpi.update_task_content(row['task_id'], content)
                        check = glpi.ticket_task(row['task_id'])
                        if plain(check.get('content')) != plain(content):
                            raise ValueError('Texto não confirmado pelo GLPI')
                        linked = {int(x.get('documents_id') or 0) for x in glpi.task_documents(row['task_id'])}
                        if not set(documents).issubset(linked):
                            raise ValueError('Vínculos de documentos não confirmados')
                        if row.get('actiontime') is not None and int(check.get('actiontime') or 0)!=row['actiontime']:
                            glpi.update_task(row['task_id'],{'actiontime':row['actiontime']})
                            check=glpi.ticket_task(row['task_id'])
                            if int(check.get('actiontime') or 0)!=row['actiontime']:
                                raise ValueError('GLPI não confirmou a duração da tarefa')
                        # Completion happens only after evidence links and content are verified.
                        # A failed upload must not tick an unchecked task.
                        if row.get('complete') and int(check.get('state') or 0) != 2:
                            glpi.update_task(row['task_id'], {'state': 2})
                            check = glpi.ticket_task(row['task_id'])
                            if int(check.get('state') or 0) != 2:
                                raise ValueError('GLPI não confirmou a tarefa como concluída')
                        results.append({'task_id': row['task_id'], 'ok': True, 'documents': documents, 'state': check.get('state')})
                    except Exception as exc:
                        results.append({'task_id': row['task_id'], 'ok': False, 'error': str(exc), 'documents': documents})
                        break
            result = {'ok': len(results) == len(p['rows']) and all(r['ok'] for r in results), 'results': results,
                      'not_executed': [r['task_id'] for r in p['rows'][len(results):]]}
            history = get_meta('workbench_history', []) or []
            history.insert(0, {'at': time.time(), 'target': 'existing_tasks', 'ticket_id': p['ticket_id'], **result})
            set_meta('workbench_history', history[:100])
            return result
