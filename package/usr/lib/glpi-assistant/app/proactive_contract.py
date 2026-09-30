"""Versioned proactive drafts. No GLPI mutations or inferred identities."""
from __future__ import annotations
import copy
import json
import re
from datetime import datetime


def parse_proactive_blocks(text: str) -> list[dict]:
    if len(text.encode('utf-8')) > 131072:
        raise ValueError('Texto excede 128 KiB')
    result = []
    for block in re.findall(r'\[GLPI_PROACTIVE\](.*?)\[/GLPI_PROACTIVE\]', text, re.S):
        value = json.loads(block.strip())
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Proativo deve ser um objeto')
            result.append(row)
    if not result or len(result) > 30:
        raise ValueError('Informe de 1 a 30 proativos')
    refs = [str(row.get('draft_ref') or '') for row in result]
    if len(set(refs)) != len(refs):
        raise ValueError('Cada proativo precisa de referência única')
    return result


def normalize_proactive(raw: dict, prompt_timestamp: str | None) -> dict:
    if raw.get('schema_version') != 1 or raw.get('operation') != 'create_proactive':
        raise ValueError('Contrato de proativo não suportado')
    d = copy.deepcopy(raw)
    ref = str(d.get('draft_ref') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ref):
        raise ValueError('Referência inválida')
    pending = []
    for field in ('title', 'description', 'entity', 'category'):
        if not isinstance(d.get(field), str) or not d[field].strip():
            pending.append(field)
        elif len(d[field]) > (200 if field == 'title' else 10000):
            raise ValueError('Campo excede limite: ' + field)
    stamp = None
    if prompt_timestamp:
        try:
            parsed = datetime.fromisoformat(prompt_timestamp.replace('Z', '+00:00'))
            if parsed.utcoffset() is not None:
                stamp = prompt_timestamp
        except (ValueError, TypeError):
            pass
    if not stamp:
        pending.append('prompt_timestamp')
    d['prompt_timestamp'] = stamp
    d['type'] = 2
    priority = d.get('priority', 3)
    if isinstance(priority, bool) or not isinstance(priority,int) or priority not in (2, 3, 4, 5, 6):
        raise ValueError('Prioridade inválida')
    if priority > 3 and not d.get('priority_explicit'):
        pending.append('priority_authorization')
    d['priority'] = priority
    d['target'] = d.get('target', 'active')
    if d['target'] not in ('active', 'solve', 'close'):
        raise ValueError('Destino inválido')
    if d['target'] != 'active' and not str(d.get('solution') or '').strip():
        pending.append('solution')
    if not isinstance(d.get('groups', []), list) or len(d.get('groups', [])) > 20 or any(not isinstance(g,str) or len(g)>200 for g in d.get('groups', [])):
        raise ValueError('Grupos inválidos')
    tasks = d.get('tasks', [])
    if not isinstance(tasks, list) or len(tasks) > 100:
        raise ValueError('Lista de tarefas inválida')
    ids = []
    for task in tasks:
        if not isinstance(task, dict) or not re.fullmatch(r'T\d{2,3}', str(task.get('id') or '')):
            raise ValueError('Identificador de tarefa inválido')
        ids.append(task['id'])
        if not str(task.get('content') or '').strip():
            raise ValueError('Tarefa sem descrição')
        for field,limit in [('content',20000),('title',200),('mode',200)]:
            if not isinstance(task.get(field,''),str) or len(task.get(field,''))>limit: raise ValueError('Campo de tarefa inválido: '+field)
        duration = task.get('actiontime', 0)
        if isinstance(duration, bool) or not isinstance(duration, int) or not 0 <= duration <= 86400:
            raise ValueError('Duração inválida')
        task['actiontime'] = duration
    if len(set(ids)) != len(ids):
        raise ValueError('Tarefas duplicadas')
    evidence = d.get('evidence', [])
    if not isinstance(evidence, list) or len(evidence) > 100:
        raise ValueError('Evidências inválidas')
    eids = set()
    for e in evidence:
        if not isinstance(e, dict) or not re.fullmatch(r'E\d{2,3}', str(e.get('id') or '')) or e['id'] in eids:
            raise ValueError('Referência de evidência inválida')
        eids.add(e['id'])
        if e.get('role', 'evidence') not in ('context', 'evidence'):
            raise ValueError('Tipo de imagem inválido')
        if not isinstance(e.get('source_index'), int) or isinstance(e['source_index'], bool) or e['source_index'] < 1:
            raise ValueError('Ordem da imagem inválida')
    for task in tasks:
        links = task.get('evidence_ids', [])
        if not isinstance(links, list) or any(e not in eids for e in links):
            raise ValueError('Tarefa referencia imagem inexistente')
        if any(e['id'] in links and e.get('role') == 'context' for e in evidence):
            raise ValueError('Imagem de contexto não pode ser evidência')
    d['tasks'] = tasks
    d['evidence'] = evidence
    d['pending_fields'] = pending
    return d
