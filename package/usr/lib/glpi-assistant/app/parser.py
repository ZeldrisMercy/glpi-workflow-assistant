from __future__ import annotations

import re
import unicodedata
from typing import Any

TASK_RE = re.compile(r"\[TAREFA:(?P<id>[^\]]+)\](?P<body>.*?)\[/TAREFA\]", re.I | re.S)
CHANGE_RE = re.compile(r"\[ALTERACOES_CHAMADO\](?P<body>.*?)\[/ALTERACOES_CHAMADO\]", re.I | re.S)
EVIDENCE_RE = re.compile(r"\[EVID[ÊE]NCIA\s*:\s*(?P<id>[A-Za-z0-9_.-]+)\s*\]", re.I)
META_LINE_RE = re.compile(r"^(modalidade|n[ií]vel|nivel|tempo|estado)\s*:\s*(.+?)\s*$", re.I)


BATCH_OPEN_RE = re.compile(r"\[GLPI_BATCH(?:\s*:[^\]]+)?\]", re.I)
BATCH_CLOSE_RE = re.compile(r"\[/GLPI_BATCH\]", re.I)
TICKET_MARKER_RE = re.compile(r"\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]", re.I)


def normalize_contract_text(text: str) -> str:
    """Normalize line endings and repair a contract serialized with literal \n.

    The repair is deliberately gated by an escaped newline immediately after a
    GLPI marker/task opener so ordinary Windows paths/backslashes are untouched.
    """
    source = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    escaped_contract = re.search(r"\[GLPI_ASSISTANT\s*:\s*\d+\s*\]\s*\\(?:r\\n|n|r)", source, re.I)
    escaped_task = re.search(r"\[TAREFA:T\d+\]\s*\\(?:r\\n|n|r)", source, re.I)
    if escaped_contract or escaped_task:
        source = source.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    return source


def split_closure_batch(text: str) -> list[dict[str, Any]]:
    """Split one AI answer containing one or many ticket contracts.

    A batch wrapper is optional. Each ticket is delimited by its own
    ``[GLPI_ASSISTANT:<id>]`` marker and the next marker. The returned closure
    intentionally keeps the marker so the ordinary parser/bridge cross-checks
    still apply to every item independently.
    """
    source = normalize_batch_text(text)
    matches = list(TICKET_MARKER_RE.finditer(source))
    if not matches:
        return []
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, match in enumerate(matches):
        ticket_id = int(match.group(1))
        if ticket_id in seen:
            raise ValueError(f"Chamado #{ticket_id} repetido no mesmo lote.")
        seen.add(ticket_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        block = source[match.start():end].strip()
        block = BATCH_CLOSE_RE.sub('', block).strip()
        if not TASK_RE.search(block):
            raise ValueError(f"Chamado #{ticket_id}: nenhum bloco [TAREFA:...] encontrado.")
        result.append({"ticket_id": ticket_id, "closure": block})
    return result


def normalize_batch_text(text: str) -> str:
    source = normalize_contract_text(text).strip()
    source = BATCH_OPEN_RE.sub('', source)
    source = BATCH_CLOSE_RE.sub('', source)
    return source.strip()


def resolve_bridge_ticket_id(payload_ticket_id: int | None, closure: str) -> int:
    """Resolve and cross-check the ticket carried by an AI handoff."""
    markers = re.findall(r"\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]", closure or "", re.I)
    if len(set(markers)) > 1:
        raise ValueError('O texto contém marcadores de chamados diferentes.')
    marker = re.search(r"\[GLPI_ASSISTANT\s*:\s*(\d+)\s*\]", closure or "", re.I)
    marker_ticket_id = int(marker.group(1)) if marker else None
    ticket_id = int(payload_ticket_id) if payload_ticket_id else marker_ticket_id
    if ticket_id is None:
        raise ValueError("Número do chamado ausente. Use [GLPI_ASSISTANT:<ID>] no início do fechamento.")
    if ticket_id <= 0:
        raise ValueError("ticket_id inválido")
    if marker_ticket_id is not None and marker_ticket_id != ticket_id:
        raise ValueError(f"Conflito de chamado: payload #{ticket_id} e marcador #{marker_ticket_id}.")
    return ticket_id


def parse_duration(value: str) -> int:
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return int(value) * 60

    parts = value.split(":")
    if len(parts) == 2 and all(re.fullmatch(r"\d+", p or "x") for p in parts):
        hours, minutes = map(int, parts)
        if minutes >= 60:
            raise ValueError(f"Tempo inválido: {value}")
        return hours * 3600 + minutes * 60

    if len(parts) == 3 and all(re.fullmatch(r"\d+", p or "x") for p in parts):
        hours, minutes, seconds = map(int, parts)
        if minutes >= 60 or seconds >= 60:
            raise ValueError(f"Tempo inválido: {value}")
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Tempo inválido: {value}. Use HH:MM, HH:MM:SS ou minutos inteiros.")


def task_state(value: str) -> int:
    # Accept harmless Markdown/punctuation variations emitted by AI models.
    raw = unicodedata.normalize("NFKD", value.strip().casefold())
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    n = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    if n in {"2", "feito", "concluido", "done", "finalizado", "completo", "completed"}:
        return 2
    if n in {"1", "aberto", "a fazer", "todo", "pendente", "open", "to do"}:
        return 1
    raise ValueError(f"Estado de tarefa não reconhecido: {value}")


def normalize_modality(value: str) -> str:
    n = re.sub(r"\s+", " ", value.strip()).casefold()
    aliases = {
        "remoto": "REMOTO",
        "remote": "REMOTO",
        "presencial": "PRESENCIAL",
        "on-site": "PRESENCIAL",
        "onsite": "PRESENCIAL",
        "local": "PRESENCIAL",
    }
    if n in aliases:
        return aliases[n]
    raise ValueError(f"Modalidade não reconhecida: {value}. Use REMOTO ou PRESENCIAL.")


def normalize_level(value: str) -> str:
    n = re.sub(r"[^a-z0-9]", "", value.strip().casefold())
    aliases = {
        "n1": "N1",
        "nivel1": "N1",
        "suporten1": "N1",
        "l1": "N1",
        "n2": "N2",
        "nivel2": "N2",
        "suporten2": "N2",
        "l2": "N2",
    }
    if n in aliases:
        return aliases[n]
    raise ValueError(f"Nível não reconhecido: {value}. Use N1 ou N2.")


def _strip_task_metadata(body: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    lines = body.strip().splitlines()
    content_lines: list[str] = []
    in_meta = True
    for line in lines:
        m = META_LINE_RE.match(line)
        if in_meta and m:
            key = m.group(1).casefold()
            if key in {"nível", "nivel"}:
                key = "nivel"
            meta[key] = m.group(2).strip()
            continue
        if in_meta and not line.strip():
            continue
        in_meta = False
        content_lines.append(line)
    return meta, "\n".join(content_lines).strip()


def _parse_change_block(body: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "titulo": None,
        "categoria": None,
        "requerente": None,
        "adicionar_grupo": [],
        "remover_grupo": [],
        "adicionar_tecnico": [],
        "remover_tecnico": [],
    }
    current_list: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("-") and current_list:
            result[current_list].append(line[1:].strip())
            continue
        m = re.match(r"^([A-Za-z_çÇãÃáÁéÉíÍóÓúÚ ]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1).strip().casefold().replace(" ", "_")
        value = m.group(2).strip()
        aliases = {
            "titulo": "titulo",
            "título": "titulo",
            "categoria": "categoria",
            "requerente": "requerente",
            "adicionar_grupo": "adicionar_grupo",
            "remover_grupo": "remover_grupo",
            "adicionar_atribuido": "adicionar_grupo",
            "remover_atribuido": "remover_grupo",
            "adicionar_técnico": "adicionar_tecnico",
            "adicionar_tecnico": "adicionar_tecnico",
            "remover_técnico": "remover_tecnico",
            "remover_tecnico": "remover_tecnico",
        }
        mapped = aliases.get(key)
        if not mapped:
            current_list = None
            continue
        if mapped in {"titulo", "categoria", "requerente"}:
            result[mapped] = value or None
            current_list = None
        else:
            current_list = mapped
            if value:
                result[mapped].append(value)
    return result


def _split_change_values(values: list[Any]) -> list[str]:
    """Normalize repeated, list and legacy semicolon-separated changes.

    Older Bridge prompts emitted ``REMOTO; SUPORTE N1`` on a single line.
    The parser must treat that as two groups, while preserving the safer
    repeated-line/list syntax as the canonical representation.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for item in re.split(r"[;\n]+", str(raw or "")):
            item = re.sub(r"\s+", " ", item).strip(" \t,-")
            if not item:
                continue
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(item)
    return cleaned


def _empty_changes() -> dict[str, Any]:
    return {
        "titulo": None,
        "categoria": None,
        "requerente": None,
        "adicionar_grupo": [],
        "remover_grupo": [],
        "adicionar_tecnico": [],
        "remover_tecnico": [],
    }


def _ensure_operational_groups(
    tasks: list[dict[str, Any]],
    changes: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Guarantee deterministic operational groups for a complete 2.3 closure.

    The Browser Bridge can observe a streaming response immediately after T05
    and, on a slow generation, receive the trailing ALTERACOES_CHAMADO a little
    later.  REMOTO/PRESENCIAL and SUPORTE N1/N2 are already explicit metadata
    on every task, so the local Assistant can safely repair those two groups
    without depending on the trailing AI block. Other ticket changes are never
    inferred here.
    """
    if not tasks:
        return changes, []

    modalities = {str(t.get("modalidade") or "").strip() for t in tasks if t.get("modalidade")}
    levels = {str(t.get("nivel") or "").strip() for t in tasks if t.get("nivel")}

    # Um fechamento parcial (por exemplo T04/T05) também precisa continuar
    # operacionalmente coerente. Para nível, qualquer atividade N2 eleva o
    # atendimento a SUPORTE N2. Para modalidade, só inferimos quando todas as
    # tarefas recebidas concordam entre si.
    required: list[str] = []
    if len(modalities) == 1:
        required.append(next(iter(modalities)))
    if levels:
        required.append("SUPORTE N2" if "N2" in levels else "SUPORTE N1")
    if not required:
        return changes, []
    result = changes if changes is not None else _empty_changes()

    # Reconcile only the deterministic operational families. This matters when
    # a technician edits the generated draft by hand (for example N1 -> N2):
    # the stale SUPORTE N1 must not survive beside the new SUPORTE N2.
    required_norm = {re.sub(r"\s+", " ", x).casefold(): x for x in required}
    required_support = next((x for x in required if x in {"SUPORTE N1", "SUPORTE N2"}), None)
    required_modality = next((x for x in required if x in {"REMOTO", "PRESENCIAL"}), None)

    cleaned_add: list[str] = []
    for raw in _split_change_values(result.get("adicionar_grupo", [])):
        item = str(raw).strip()
        norm = re.sub(r"\s+", " ", item).casefold()
        if norm in {"suporte n1", "suporte n2"} and required_support and norm != required_support.casefold():
            continue
        if norm in {"remoto", "presencial"} and required_modality and norm != required_modality.casefold():
            continue
        cleaned_add.append(item)
    result["adicionar_grupo"] = cleaned_add

    cleaned_remove: list[str] = []
    for raw in _split_change_values(result.get("remover_grupo", [])):
        item = str(raw).strip()
        norm = re.sub(r"\s+", " ", item).casefold()
        if norm in required_norm:
            continue
        cleaned_remove.append(item)
    result["remover_grupo"] = cleaned_remove

    declared = _split_change_values(result.get("adicionar_grupo", []))
    normalized = {re.sub(r"\s+", " ", x).casefold() for x in declared}
    auto_added: list[str] = []
    for group in required:
        key = re.sub(r"\s+", " ", group).casefold()
        if key not in normalized:
            result.setdefault("adicionar_grupo", []).append(group)
            normalized.add(key)
            auto_added.append(group)
    return result, auto_added


def _quality_summary(tasks: list[dict[str, Any]], changes: dict[str, Any] | None = None, auto_added_groups: list[str] | None = None) -> dict[str, Any]:
    total = sum(int(t.get("actiontime") or 0) for t in tasks)
    durations = [int(t.get("actiontime") or 0) for t in tasks]
    levels = sorted({str(t.get("nivel") or "") for t in tasks if t.get("nivel")})
    modalities = sorted({str(t.get("modalidade") or "") for t in tasks if t.get("modalidade")})
    warnings: list[str] = []

    if len(tasks) == 5 and durations and len(set(durations)) == 1 and durations[0] <= 5 * 60:
        warnings.append("Os cinco tempos são idênticos e baixos; confirme se refletem o esforço real do atendimento.")
    if total and total < 15 * 60:
        warnings.append("Tempo total abaixo de 15 minutos; confirme se representa o esforço real do atendimento.")

    required_groups: list[str] = []
    if len(modalities) == 1:
        required_groups.append(modalities[0])
    if levels:
        required_groups.append("SUPORTE N2" if "N2" in levels else "SUPORTE N1")

    declared_groups = [str(x).strip() for x in (changes or {}).get("adicionar_grupo", []) if str(x).strip()]
    normalized_declared = {re.sub(r"\s+", " ", x).casefold() for x in declared_groups}
    missing_groups = [
        group for group in required_groups
        if re.sub(r"\s+", " ", group).casefold() not in normalized_declared
    ]
    if missing_groups:
        warnings.append(
            "Grupos operacionais ausentes no bloco ALTERACOES_CHAMADO: "
            + ", ".join(missing_groups)
            + "."
        )

    return {
        "total_actiontime": total,
        "levels": levels,
        "modalities": modalities,
        "required_groups": required_groups,
        "declared_groups": declared_groups,
        "missing_groups": missing_groups,
        "auto_added_groups": list(auto_added_groups or []),
        "warnings": warnings,
    }


def parse_closure(text: str) -> dict[str, Any]:
    text = normalize_contract_text(text).strip()
    if len(re.findall(r'\[ALTERACOES_CHAMADO\]', text, re.I)) != len(CHANGE_RE.findall(text)) or len(re.findall(r'\[/ALTERACOES_CHAMADO\]', text, re.I)) != len(CHANGE_RE.findall(text)):
        raise ValueError('Bloco ALTERACOES_CHAMADO incompleto.')
    if len(CHANGE_RE.findall(text)) > 1:
        raise ValueError('Use apenas um bloco ALTERACOES_CHAMADO por chamado.')
    if len(re.findall(r'\[TAREFA:', text, re.I)) != len(TASK_RE.findall(text)):
        raise ValueError('Bloco de tarefa incompleto.')
    if len(re.findall(r'\[/TAREFA\]', text, re.I)) != len(TASK_RE.findall(text)):
        raise ValueError('Fechamento de tarefa sem abertura.')
    tasks = []
    seen_evidence: set[str] = set()
    seen_task_ids: set[str] = set()
    for m in TASK_RE.finditer(text):
        task_id = m.group("id").strip().upper()
        if not re.fullmatch(r"T(?:0[1-9]|[1-9][0-9]{1,2})", task_id):
            raise ValueError(f"Identificador de tarefa inválido: {task_id}. Use T01, T02… T999.")
        if task_id in seen_task_ids:
            raise ValueError(f"Tarefa repetida no fechamento: {task_id}.")
        seen_task_ids.add(task_id)
        meta, content = _strip_task_metadata(m.group("body"))
        missing = [k for k in ("modalidade", "nivel", "tempo", "estado") if not meta.get(k)]
        if missing:
            friendly = ["nível" if k == "nivel" else k for k in missing]
            raise ValueError(f"Tarefa {task_id}: metadados ausentes: {', '.join(friendly)}")
        evidences = [x.group("id").upper() for x in EVIDENCE_RE.finditer(content)]
        if len(evidences) != len(set(evidences)):
            raise ValueError(f'Evidência repetida na tarefa {task_id}.')
        duplicates = seen_evidence.intersection(evidences)
        if duplicates:
            raise ValueError(f"Evidência repetida entre tarefas: {', '.join(sorted(duplicates))}")
        seen_evidence.update(evidences)
        modalidade = normalize_modality(meta["modalidade"])
        nivel = normalize_level(meta["nivel"])
        tasks.append({
            "id": task_id,
            "modalidade": modalidade,
            "nivel": nivel,
            "tempo": meta["tempo"],
            "actiontime": parse_duration(meta["tempo"]),
            "estado": meta["estado"],
            "state": task_state(meta["estado"]),
            "content": content,
            "evidences": evidences,
        })

    if not tasks:
        raise ValueError("Nenhum bloco [TAREFA:...] encontrado.")

    received_ids = [task["id"] for task in tasks]
    if not received_ids:
        raise ValueError("Informe ao menos uma tarefa.")

    task_order = [int(task["id"][1:]) for task in tasks]
    if task_order != sorted(task_order):
        raise ValueError("As tarefas devem aparecer em ordem numérica crescente.")

    cm = CHANGE_RE.search(text)
    changes = _parse_change_block(cm.group("body")) if cm else None
    changes, auto_added_groups = _ensure_operational_groups(tasks, changes)

    quality = _quality_summary(tasks, changes, auto_added_groups)
    quality["partial_closure"] = len(tasks) < 5
    quality["task_ids"] = [t["id"] for t in tasks]
    quality["missing_task_ids"] = [f"T0{i}" for i in range(1, 6) if f"T0{i}" not in seen_task_ids]

    return {
        "tasks": tasks,
        "changes": changes,
        "evidence_ids": sorted(seen_evidence),
        "quality": quality,
    }
