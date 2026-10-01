from __future__ import annotations
from contact_policy import self_only_ticket
from closure_intent import parse_intent

import html
import json
import hashlib
import os
import queue
import re
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
import whatsapp_auto
from local_security import LocalBoundary
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from evidence_bridge import validate_images, save_images, delete_images

from glpi import GlpiClient, GlpiConfig, GlpiError, decode_glpi_text
from parser import EVIDENCE_RE, normalize_contract_text, parse_closure, parse_duration, resolve_bridge_ticket_id, task_state, split_closure_batch
from store import (
    DATA_DIR,
    catalog_stats,
    clear_catalog,
    create_bridge_handoff,
    connect,
    delete_bridge_handoff,
    get_bridge_handoff,
    get_catalog_item,
    get_meta,
    list_catalog,
    list_bridge_handoffs,
    load_config,
    replace_catalog,
    resolve_catalog,
    save_config,
    set_bridge_handoff_status,
    set_meta,
    upsert_catalog_item,
)

VERSION = "3.4.0-beta.1"
STATIC = Path(__file__).parent / "static"
PROMPT_PATH = Path(__file__).parent / "PROMPT_FORMALIZACAO.md"

app = FastAPI(title="GLPI Assistant", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(LocalBoundary)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    )
    if request.url.path.startswith('/api/'):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

app.mount("/static", StaticFiles(directory=STATIC), name="static")

import workbench
import evidence_bridge
import template_tasks
workbench.register(app, lambda: _client(), lambda g, i: _ticket_snapshot(g, i), lambda r: _require_local_ui(r), lambda r: _require_bridge_auth(r))
evidence_bridge.register(app)
template_tasks.register(app, lambda: _client(), lambda r: _require_local_ui(r))


class SetupPayload(BaseModel):
    url: str
    user_token: str
    app_token: str = ""
    verify_tls: bool = True


class ParsePayload(BaseModel):
    text: str


class PlanPayload(BaseModel):
    ticket_id: int
    text: str
    evidence_map: dict[str, str] = {}


class ReviewSuggestPayload(BaseModel):
    ticket_id: int
    text: str


class BatchParsePayload(BaseModel):
    text: str


class TicketEditPayload(BaseModel):
    title: str | None = None
    category: str | None = None
    status: int | None = None
    priority: int | None = None


class ActorEditPayload(BaseModel):
    kind: str
    role: str
    query: str


class TaskEditPayload(BaseModel):
    content: str | None = None
    time: str | None = None
    state: str | None = None
    technician: str | None = None
    modality: str | None = None


class ManualTaskPayload(BaseModel):
    content: str
    time: str = "00:05"
    state: str = "FEITO"
    technician: str | None = None
    modality: str = "REMOTO"


class TaskBulkDeletePayload(BaseModel):
    task_ids: list[int]


class ReplaceRequesterPayload(BaseModel):
    query: str


class BridgePairPayload(BaseModel):
    code: str
    extension_version: str | None = None


class BridgeHandoffPayload(BaseModel):
    version: int = 2
    source: str = "chatgpt"
    ticket_id: int | None = None
    closure: str
    images: list[dict[str, str]] = []
    manual: bool = False


class BridgeHandoffStatePayload(BaseModel):
    status: str


class BridgePingPayload(BaseModel):
    extension_version: str | None = None


_BRIDGE_PAIR_LOCK = threading.Lock()
_BRIDGE_PAIR: dict[str, Any] = {"code": None, "expires_at": 0.0, "attempts": 0}
_BRIDGE_SUBSCRIBERS_LOCK = threading.Lock()
_BRIDGE_SUBSCRIBERS: set[queue.Queue] = set()
_BRIDGE_MAX_CLOSURE_BYTES = 128 * 1024


def _config() -> GlpiConfig:
    cfg = load_config()
    if not cfg:
        raise HTTPException(409, "Aplicação ainda não configurada")
    return GlpiConfig(**cfg)


def _client():
    return GlpiClient(_config())


def _error(exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    raise HTTPException(400, str(exc)) from exc


@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/ai/prompt")
def ai_prompt():
    try:
        return {"ok": True, "version": VERSION, "prompt": PROMPT_PATH.read_text(encoding="utf-8")}
    except Exception as exc:
        _error(exc)


@app.get("/api/status")
def status():
    cfg = load_config()
    safe = None
    if cfg:
        safe = {
            "url": cfg.get("url", ""),
            "has_user_token": bool(cfg.get("user_token")),
            "has_app_token": bool(cfg.get("app_token")),
            "verify_tls": cfg.get("verify_tls", True),
        }
    return {
        "configured": bool(cfg),
        "config": safe,
        "catalog": catalog_stats(),
        "sync": get_meta("last_sync"),
        "current_user_id": get_meta("current_user_id"),
        "connection_diagnostics": get_meta("connection_diagnostics"),
        "version": VERSION,
    }


def _require_local_ui(request: Request) -> None:
    # Same-origin JSON requests from the local UI are allowed. Browser pages
    # hosted elsewhere cannot read the pairing code because we intentionally
    # do not enable CORS for the application. CLI requests have no Origin.
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
        raise HTTPException(403, "Operação disponível somente pela interface local do GLPI Assistant")


def _bridge_token() -> str:
    return str(get_meta("bridge_token", "") or "")


def _require_bridge_auth(request: Request) -> str:
    expected = _bridge_token()
    if not expected:
        raise HTTPException(401, "Browser Bridge ainda não foi pareado")
    auth = (request.headers.get("authorization") or "").strip()
    supplied = ""
    if auth.casefold().startswith("bearer "):
        supplied = auth[7:].strip()
    if not supplied:
        supplied = (request.headers.get("x-glpi-bridge-token") or "").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Bridge Token inválido")
    return supplied


def _bridge_row(row: dict[str, Any], *, include_closure: bool = True) -> dict[str, Any]:
    metadata = get_meta(f"bridge_images_{row['id']}", []) or []
    normalized_closure = normalize_contract_text(row.get("closure") or "")
    intent = parse_intent(normalized_closure)
    expected_ids = [m.group("id").upper() for m in EVIDENCE_RE.finditer(normalized_closure)]
    stored_ids = [str(item.get("id") or "").upper() for item in metadata]
    missing_ids = sorted(set(expected_ids) - set(stored_ids), key=lambda value: int(value[1:]))
    data = {
        "id": int(row["id"]),
        "source": row.get("source") or "chatgpt",
        "ticket_id": row.get("ticket_id"),
        "intent": intent,
        "content_hash": row.get("content_hash"),
        "status": row.get("status") or "pending",
        "task_count": int(row.get("task_count") or 0),
        "evidence_count": int(row.get("evidence_count") or 0),
        "stored_evidence_count": len(stored_ids),
        "missing_evidence_ids": missing_ids,
        "evidence_ready": not missing_ids and len(stored_ids) == len(set(expected_ids)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if include_closure:
        data["closure"] = normalized_closure
        data["images"] = metadata
    return data


def _broadcast_bridge_handoff(row: dict[str, Any]) -> None:
    event = _bridge_row(row, include_closure=True)
    dead: list[queue.Queue] = []
    with _BRIDGE_SUBSCRIBERS_LOCK:
        subscribers = list(_BRIDGE_SUBSCRIBERS)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            # A stale browser tab must never block delivery to active tabs.
            dead.append(subscriber)
    if dead:
        with _BRIDGE_SUBSCRIBERS_LOCK:
            for subscriber in dead:
                _BRIDGE_SUBSCRIBERS.discard(subscriber)


@app.get("/api/bridge/info")
def bridge_info():
    last_seen = float(get_meta("bridge_last_seen", 0) or 0)
    age = max(0.0, time.time() - last_seen) if last_seen else None
    return {
        "ok": True,
        "assistant_version": VERSION,
        "protocol": 2,
        "bridge_generation": "2.4.0",
        "capabilities": ["ack", "persistent-outbox", "multi-ticket", "generic-ai", "evidence-preview", "mirrored-editors", "evidence-ttl"],
        "paired": bool(_bridge_token()),
        "connected": bool(last_seen and age is not None and age <= 90),
        "last_seen": last_seen or None,
        "last_seen_age": round(age, 1) if age is not None else None,
        "extension_version": get_meta("bridge_extension_version"),
        "last_handoff": get_meta("bridge_last_handoff"),
    }


@app.post("/api/bridge/pair-code")
def bridge_pair_code(request: Request):
    _require_local_ui(request)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = time.time() + 300
    with _BRIDGE_PAIR_LOCK:
        _BRIDGE_PAIR["code"] = code
        _BRIDGE_PAIR["expires_at"] = expires_at
        _BRIDGE_PAIR["attempts"] = 0
    return {
        "ok": True,
        "code": f"{code[:3]}-{code[3:]}",
        "expires_in": 300,
        "expires_at": expires_at,
    }


@app.post("/api/bridge/pair")
def bridge_pair(payload: BridgePairPayload):
    code = re.sub(r"\D", "", payload.code or "")
    now = time.time()
    with _BRIDGE_PAIR_LOCK:
        expected = str(_BRIDGE_PAIR.get("code") or "")
        expires_at = float(_BRIDGE_PAIR.get("expires_at") or 0)
        if not expected or now > expires_at:
            _BRIDGE_PAIR["code"] = None
            _BRIDGE_PAIR["expires_at"] = 0.0
            _BRIDGE_PAIR["attempts"] = 0
            raise HTTPException(410, "Código de pareamento expirado. Gere outro no GLPI Assistant.")
        attempts = int(_BRIDGE_PAIR.get("attempts") or 0)
        if attempts >= 8:
            _BRIDGE_PAIR["code"] = None
            _BRIDGE_PAIR["expires_at"] = 0.0
            _BRIDGE_PAIR["attempts"] = 0
            raise HTTPException(429, "Muitas tentativas de pareamento. Gere um novo código no GLPI Assistant.")
        if not secrets.compare_digest(code, expected):
            _BRIDGE_PAIR["attempts"] = attempts + 1
            raise HTTPException(401, "Código de pareamento inválido")
        _BRIDGE_PAIR["code"] = None
        _BRIDGE_PAIR["expires_at"] = 0.0
        _BRIDGE_PAIR["attempts"] = 0

    token = secrets.token_urlsafe(32)
    set_meta("bridge_token", token)
    set_meta("bridge_last_seen", now)
    set_meta("bridge_extension_version", payload.extension_version)
    return {
        "ok": True,
        "protocol": 2,
        "assistant_version": VERSION,
        "bridge_token": token,
    }


@app.post("/api/bridge/revoke")
def bridge_revoke(request: Request):
    _require_local_ui(request)
    set_meta("bridge_token", "")
    set_meta("bridge_last_seen", 0)
    set_meta("bridge_extension_version", None)
    return {"ok": True}


@app.post("/api/bridge/unpair")
def bridge_unpair(request: Request):
    _require_bridge_auth(request)
    set_meta("bridge_token", "")
    set_meta("bridge_last_seen", 0)
    set_meta("bridge_extension_version", None)
    return {"ok": True}


@app.post("/api/bridge/ping")
def bridge_ping(payload: BridgePingPayload, request: Request):
    _require_bridge_auth(request)
    now = time.time()
    set_meta("bridge_last_seen", now)
    if payload.extension_version:
        set_meta("bridge_extension_version", payload.extension_version)
    return {"ok": True, "assistant_version": VERSION, "protocol": 2, "bridge_generation": "2.4.0", "ack": True, "now": now}



def _completion_key(ticket_id):
    identity = hashlib.sha256(json.dumps(load_config() or {}, sort_keys=True).encode()).hexdigest()
    return f"completed_bridge_{identity}_{ticket_id}"


def _task_fingerprints(parsed):
    return {_hash_json(t) for t in parsed.get('tasks', [])}


def _change_fingerprints(parsed):
    return {_hash_json([key, item]) for key, value in parsed.get('changes', {}).items()
            for item in (value if isinstance(value, list) else [value]) if item is not None}


def _intent_status_complete(closure, status):
    intent = parse_intent(closure)
    return not intent or int(status or 0) in ((6,) if intent['target'] == 'close' else (5, 6))


def _intent_is_complete(ticket_id, closure):
    if not parse_intent(closure):
        return True
    try:
        with _client() as glpi:
            return _intent_status_complete(closure, glpi.get_ticket(ticket_id).get('status'))
    except Exception:
        return False  # Loss of access must preserve unfinished work.


def _remember_applied(ticket_id, text):
    parsed = parse_closure(normalize_contract_text(text).strip())
    key = _completion_key(ticket_id)
    old = get_meta(key, {}) or {}
    hashes = set(old.get('tasks', [])) | _task_fingerprints(parsed)
    changes = set(old.get('changes', [])) | _change_fingerprints(parsed)
    closures = set(old.get('closures', []))
    if _intent_is_complete(ticket_id, text):
        closures.add(hashlib.sha256(normalize_contract_text(text).strip().encode()).hexdigest())
    set_meta(key, {'tasks': sorted(hashes), 'closures': sorted(closures), 'changes': sorted(changes)})
    with connect() as con:
        rows = con.execute("SELECT * FROM bridge_handoff WHERE ticket_id=?", (ticket_id,)).fetchall()
        for row in rows:
            candidate = parse_closure(row['closure'])
            exact = hashlib.sha256(row['closure'].encode()).hexdigest() in closures
            subset = _change_fingerprints(candidate) <= changes and _task_fingerprints(candidate) <= hashes
            if (exact or subset) and _intent_is_complete(ticket_id, row['closure']):
                con.execute("UPDATE bridge_handoff SET status='completed' WHERE id=?", (row['id'],))


def _already_applied(ticket_id, closure, parsed):
    if parse_intent(closure):
        return _intent_is_complete(ticket_id, closure)
    old = get_meta(_completion_key(ticket_id), {}) or {}
    if hashlib.sha256(closure.encode()).hexdigest() in old.get('closures', []):
        return True
    return bool(parsed.get('tasks')) and _change_fingerprints(parsed) <= set(old.get('changes', [])) and _task_fingerprints(parsed) <= set(old.get('tasks', []))


@app.post("/api/bridge/handoff")
def bridge_handoff(payload: BridgeHandoffPayload, request: Request):
    _require_bridge_auth(request)
    if int(payload.version or 0) != 2:
        raise HTTPException(400, "Versão de protocolo do Browser Bridge não suportada")

    closure = normalize_contract_text(payload.closure or "").strip()
    if not closure:
        raise HTTPException(400, "O handoff não contém fechamento")
    if len(closure.encode("utf-8")) > _BRIDGE_MAX_CLOSURE_BYTES:
        raise HTTPException(413, "Fechamento excede o limite de 128 KiB do Browser Bridge")

    try:
        parse_intent(closure)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        parsed = parse_closure(closure)
    except Exception as exc:
        raise HTTPException(400, f"Fechamento recusado pelo parser: {exc}") from exc

    ids = [str(t.get("id") or "").strip().upper() for t in parsed.get("tasks", [])]
    if not ids:
        raise HTTPException(400, "Informe ao menos uma tarefa")
    if any(not re.fullmatch(r"T(?:0[1-9]|[1-9][0-9]{1,2})", task_id) for task_id in ids):
        raise HTTPException(400, "Use identificadores T01 a T999")
    order = [int(task_id[1:]) for task_id in ids]
    if order != sorted(order):
        raise HTTPException(400, "As tarefas do Browser Bridge devem estar em ordem numérica crescente")

    try:
        ticket_id = resolve_bridge_ticket_id(payload.ticket_id, closure)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    source = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (payload.source or "chatgpt").strip())[:64] or "chatgpt"
    if _already_applied(ticket_id, closure, parsed):
        return {"ok": True, "created": False, "updated": False, "duplicate": True,
                "completed": True, "evidence_ready": True, "missing_evidence_ids": []}
    # Legacy versions did not persist completion receipts. Recover them from GLPI.
    if load_config():
        try:
            with _client() as glpi:
                ticket = glpi.get_ticket(ticket_id)
                if int(ticket.get('status') or 0) in (5, 6) and _intent_status_complete(closure, ticket.get('status')):
                    _remember_applied(ticket_id, closure)
                    return {"ok": True, "duplicate": True, "completed": True, "evidence_ready": True, "missing_evidence_ids": []}
                if parsed.get('tasks'):
                    missing_tasks, _ = _partition_incoming_tasks(parsed['tasks'], _existing_task_candidates(glpi, ticket_id))
                    if not parse_intent(closure) and not missing_tasks and not _build_plan(ticket_id, closure).get('has_actionable_operations'):
                        _remember_applied(ticket_id, closure)
                        return {"ok": True, "duplicate": True, "completed": True, "evidence_ready": True, "missing_evidence_ids": []}
        except Exception:
            pass  # Offline or insufficient access: preserve pending work.
    images = validate_images(payload.images)
    expected_evidence = set(parsed.get('evidence_ids', []))
    supplied_evidence = {item['id'] for item in images}
    unexpected = sorted(supplied_evidence - expected_evidence)
    missing = sorted(expected_evidence - supplied_evidence)
    if unexpected:
        raise HTTPException(400, 'Imagens sem marcador no fechamento: ' + ', '.join(unexpected))
    # O texto do fechamento não espera os prints. O handoff parcial entra na
    # Inbox/editores imediatamente e _bridge_row expõe missing_evidence_ids.
    # Quando os prints chegam, o mesmo content_hash é atualizado e reaberto.
    # A mesma formalização reutiliza a mesma entrada da Inbox. Porém, prints
    # diferentes são uma revisão real (clips manual/correção) e devem atualizar
    # a entrada existente em vez de serem descartados como duplicata.
    digest_source = f"{ticket_id or 0}\n{closure}".encode("utf-8")
    digest = hashlib.sha256(digest_source).hexdigest()
    row, created = create_bridge_handoff(
        source=source,
        ticket_id=ticket_id,
        closure=closure,
        content_hash=digest,
        task_count=len(parsed.get("tasks", [])),
        evidence_count=len(parsed.get("evidence_ids", [])),
    )
    if row.get('status') == 'completed':
        return {"ok": True, "duplicate": True, "completed": True, "evidence_ready": True, "missing_evidence_ids": []}
    old_images = get_meta(f"bridge_images_{row['id']}", []) or []
    old_signature = sorted((str(item.get('id') or ''), str(item.get('hash') or '')) for item in old_images)
    # Evidence may arrive after the text ACK. Merge new E-IDs with what was
    # already stored; a later partial upload must not erase E01/E02 that are
    # already attached to this handoff.
    merged_images = save_images(row['id'], images) if images else old_images
    merged_signature = sorted((str(item.get('id') or ''), str(item.get('hash') or '')) for item in merged_images)
    updated = (not created and old_signature != merged_signature)
    duplicate = (not created and not updated)
    if updated:
        # Reabre a entrada para revisão caso ela já tivesse sido importada.
        row = set_bridge_handoff_status(int(row['id']), 'pending') or row

    now = time.time()
    set_meta("bridge_last_seen", now)
    set_meta("bridge_last_handoff", {
        "id": int(row["id"]),
        "ticket_id": row.get("ticket_id"),
        "created_at": row.get("created_at"),
        "duplicate": duplicate,
        "updated": updated,
        "manual": bool(payload.manual),
    })
    if created or updated:
        _broadcast_bridge_handoff(row)
    handoff_view = _bridge_row(row, include_closure=False)
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "duplicate": duplicate,
        "evidence_ready": handoff_view["evidence_ready"],
        "missing_evidence_ids": handoff_view["missing_evidence_ids"],
        "handoff": handoff_view,
    }


_BRIDGE_RECONCILE_AT = {}


def _reconcile_legacy(rows):
    if not load_config():
        return
    for row in rows:
        tid = row.get('ticket_id')
        key = (_completion_key(tid), row['id'])
        if row.get('status') != 'imported' or time.monotonic() - _BRIDGE_RECONCILE_AT.get(key, -1000) < 60:
            continue
        _BRIDGE_RECONCILE_AT[key] = time.monotonic()
        try:
            with _client() as glpi:
                status = int(glpi.get_ticket(tid).get('status') or 0)
                parsed = parse_closure(row['closure'])
                if status in (5, 6) and _intent_status_complete(row['closure'], status):
                    _remember_applied(tid, row['closure'])
                elif parsed.get('tasks') and not parse_intent(row['closure']):
                    missing, _ = _partition_incoming_tasks(parsed['tasks'], _existing_task_candidates(glpi, tid))
                    if not missing and not _build_plan(tid, row['closure']).get('has_actionable_operations'):
                        _remember_applied(tid, row['closure'])
        except Exception:
            pass


@app.get("/api/bridge/inbox")
def bridge_inbox(limit: int = 30):
    rows = list_bridge_handoffs(limit=limit)
    _reconcile_legacy(rows)
    rows = list_bridge_handoffs(limit=limit)
    return {"ok": True, "items": [_bridge_row(r, include_closure=True) for r in rows],
            "completed_ids": [r["id"] for r in list_bridge_handoffs(limit=100, status="completed")]}


@app.get("/api/bridge/handoff/{handoff_id}")
def bridge_get_handoff(handoff_id: int):
    row = get_bridge_handoff(handoff_id)
    if not row:
        raise HTTPException(404, "Handoff não encontrado")
    return _bridge_row(row, include_closure=True)


@app.put("/api/bridge/handoff/{handoff_id}/state")
def bridge_set_handoff_state(handoff_id: int, payload: BridgeHandoffStatePayload, request: Request):
    _require_local_ui(request)
    try:
        row = set_bridge_handoff_status(handoff_id, payload.status.strip().casefold())
    except Exception as exc:
        _error(exc)
    if not row:
        raise HTTPException(404, "Handoff não encontrado")
    return {"ok": True, "handoff": _bridge_row(row, include_closure=False)}


@app.delete("/api/bridge/handoff/{handoff_id}")
def bridge_delete_handoff(handoff_id: int, request: Request):
    _require_local_ui(request)
    if not delete_bridge_handoff(handoff_id):
        raise HTTPException(404, "Handoff não encontrado")
    delete_images(handoff_id)
    return {"ok": True}


@app.get("/api/bridge/events")
def bridge_events():
    subscriber: queue.Queue = queue.Queue(maxsize=32)
    with _BRIDGE_SUBSCRIBERS_LOCK:
        _BRIDGE_SUBSCRIBERS.add(subscriber)

    def stream():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    item = subscriber.get(timeout=15)
                    payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    yield f"event: handoff\ndata: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _BRIDGE_SUBSCRIBERS_LOCK:
                _BRIDGE_SUBSCRIBERS.discard(subscriber)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

def _safe_user_catalog_entry(glpi: GlpiClient, user_id: int | None) -> None:
    if not user_id:
        return
    try:
        user = glpi.get(f"User/{int(user_id)}")
        if isinstance(user, dict) and user.get("id"):
            upsert_catalog_item("User", user)
    except Exception:
        pass


def _profile_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "interface": row.get("interface"),
    }


@app.post("/api/setup/test")
def setup_test(payload: SetupPayload, request: Request):
    _require_local_ui(request)
    try:
        cfg = GlpiConfig(**payload.model_dump())
        with GlpiClient(cfg) as glpi:
            # initSession is the authentication test. Everything after it is
            # best-effort diagnostics and MUST NOT turn a valid restricted
            # technician token into a false login failure.
            diag = glpi.connection_diagnostics()
        return {"ok": True, **diag}
    except Exception as exc:
        _error(exc)


@app.post("/api/setup/save")
def setup_save(payload: SetupPayload, request: Request):
    _require_local_ui(request)
    try:
        cfg = GlpiConfig(**payload.model_dump())
        with GlpiClient(cfg) as glpi:
            diag = glpi.connection_diagnostics()
            user_id = diag.get("user_id")

        # A new credential must never inherit catalog rows gathered by another
        # user/token. The following sync will rebuild only what this token sees.
        clear_catalog()
        save_config(payload.model_dump())
        set_meta("current_user_id", user_id)
        set_meta("connection_diagnostics", diag)
        return {"ok": True, "user_id": user_id, "diagnostics": diag}
    except Exception as exc:
        _error(exc)


def _sync_visible_catalogs(glpi: GlpiClient) -> tuple[dict[str, int], list[str], list[dict[str, Any]]]:
    kinds = ("ITILCategory", "Group", "User", "Entity")
    aggregate: dict[str, dict[int, dict[str, Any]]] = {k: {} for k in kinds}
    succeeded: dict[str, bool] = {k: False for k in kinds}
    warnings: list[str] = []
    contexts: list[dict[str, Any]] = []

    try:
        profiles = glpi.profile_rows()
    except Exception as exc:
        profiles = []
        warnings.append(f"getMyProfiles: {exc}")

    try:
        active = glpi.get_active_profile()
    except Exception:
        active = {}

    try:
        active_id = int(active.get("id") or 0)
    except (TypeError, ValueError):
        active_id = 0

    ordered = []
    if active_id:
        ordered.extend([p for p in profiles if int(p.get("id") or 0) == active_id])
    ordered.extend([p for p in profiles if int(p.get("id") or 0) != active_id])
    if not ordered:
        ordered = [{}]

    for profile in ordered:
        pid = int(profile.get("id") or 0) if profile else 0
        pname = str(profile.get("name") or pid or "perfil atual")
        if pid and pid != active_id:
            try:
                glpi.change_active_profile(pid)
            except Exception as exc:
                warnings.append(f"Perfil {pname}: não foi possível ativar ({exc})")
                continue

        try:
            entities = glpi.entity_rows()
        except Exception as exc:
            entities = []
            warnings.append(f"Perfil {pname}: getMyEntities falhou ({exc})")

        context_info = {
            "profile": _profile_summary(profile) if profile else {"id": active_id or None, "name": active.get("name")},
            "entities": [{"id": e.get("id"), "name": e.get("name")} for e in entities],
            "all_entities": False,
        }

        try:
            glpi.change_active_entities_all()
            context_info["all_entities"] = True
            contexts.append(context_info)
            scan_contexts = [None]
        except Exception as exc:
            warnings.append(
                f"Perfil {pname}: 'todas as entidades' indisponível; "
                f"usando entidades permitidas individualmente ({exc})"
            )
            contexts.append(context_info)
            scan_contexts = entities or [None]

        for entity in scan_contexts:
            if entity is not None:
                try:
                    eid = int(entity.get("id") or 0)
                    if not eid:
                        continue
                    glpi.change_active_entity(eid, recursive=True)
                except Exception as exc:
                    warnings.append(f"Perfil {pname}: entidade {entity.get('id')} indisponível ({exc})")
                    continue

            for kind in kinds:
                try:
                    items = glpi.list_all(kind)
                    succeeded[kind] = True
                    for item in items:
                        try:
                            iid = int(item.get("id"))
                        except (TypeError, ValueError, AttributeError):
                            continue
                        aggregate[kind][iid] = item
                except Exception as exc:
                    # A listagem global de User, por exemplo, pode ser proibida
                    # para um técnico que ainda consegue operar seus tickets.
                    warnings.append(f"Perfil {pname}: catálogo {kind} indisponível ({exc})")

    counts: dict[str, int] = {}
    for kind in kinds:
        # Clear stale rows even when this credential cannot list a kind.
        rows = list(aggregate[kind].values()) if succeeded[kind] else []
        counts[kind] = replace_catalog(kind, rows)

    return counts, warnings, contexts


@app.post("/api/sync")
def sync_catalog(request: Request):
    _require_local_ui(request)
    try:
        with _client() as glpi:
            diag = glpi.connection_diagnostics()
            user_id = diag.get("user_id")
            set_meta("current_user_id", user_id)
            set_meta("connection_diagnostics", diag)

            counts, warnings, contexts = _sync_visible_catalogs(glpi)
            _safe_user_catalog_entry(glpi, user_id)
            # account for the self user added after a restricted User sync
            counts = catalog_stats()

        stamp = {
            "counts": counts,
            "warnings": warnings,
            "contexts": contexts,
        }
        set_meta("last_sync", stamp)
        return {
            "ok": True,
            **stamp,
            "current_user_id": get_meta("current_user_id"),
            "diagnostics": get_meta("connection_diagnostics"),
        }
    except Exception as exc:
        _error(exc)


@app.get("/api/catalog/{kind}")
def catalog(kind: str, q: str = "", limit: int = 100):
    allowed = {"ITILCategory", "Group", "User", "Entity"}
    if kind not in allowed:
        raise HTTPException(404, "Catálogo inválido")
    capped = min(max(limit, 1), 500)
    items = list_catalog(kind, q, capped)

    # Restricted technician profiles sometimes cannot enumerate /User even
    # though GLPI's normal assignee picker can search users. When a typed user
    # query has no local hit, use the Search API as a targeted fallback and
    # hydrate only those candidates into the local catalog.
    if kind == "User" and len(str(q or "").strip()) >= 2 and not items:
        try:
            with _client() as glpi:
                for uid in glpi.search_user_ids(q, limit=min(capped, 30)):
                    try:
                        user = glpi.get(f"User/{uid}")
                        if isinstance(user, dict) and user.get("id"):
                            upsert_catalog_item("User", user)
                    except Exception:
                        continue
            items = list_catalog(kind, q, capped)
        except Exception:
            # Autocomplete is best effort. Submit-time resolution still returns
            # a useful error if the user cannot be resolved.
            pass
    return {"items": items}


TICKET_STATUS_LABELS = {
    1: "Novo",
    2: "Processando (atribuído)",
    3: "Processando (planejado)",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}

TICKET_PRIORITY_LABELS = {
    1: "Muito baixa",
    2: "Baixa",
    3: "Média",
    4: "Alta",
    5: "Muito alta",
    6: "Crítica",
}


def _ticket_snapshot(glpi: GlpiClient, ticket_id: int) -> dict[str, Any]:
    # Locate the ticket across every profile/entity available to this token.
    # The default GLPI profile is not necessarily the technician profile.
    ticket = glpi.activate_context_for_ticket(ticket_id)
    entity_id = int(ticket.get("entities_id") or 0)
    entity_label = str(entity_id) if entity_id else "—"
    if entity_id:
        cached = get_catalog_item("Entity", entity_id)
        if cached:
            entity_label = cached.get("full_name") or cached.get("name") or str(entity_id)
        else:
            try:
                ent = glpi.get(f"Entity/{entity_id}")
                upsert_catalog_item("Entity", ent)
                entity_label = ent.get("completename") or ent.get("name") or str(entity_id)
            except Exception:
                pass
    category_id = int(ticket.get("itilcategories_id") or 0)
    if category_id:
        cached = get_catalog_item("ITILCategory", category_id)
        if cached:
            category_label = cached.get("full_name") or cached.get("name") or str(category_id)
        else:
            try:
                cat = glpi.get(f"ITILCategory/{category_id}")
                upsert_catalog_item("ITILCategory", cat)
                category_label = cat.get("completename") or cat.get("name") or str(category_id)
            except Exception:
                category_label = str(category_id)
    else:
        category_label = "Sem categoria"

    users = glpi.ticket_users(ticket_id)
    groups = glpi.ticket_groups(ticket_id)

    def user_obj(rel):
        uid = int(rel.get("users_id") or 0)
        label = str(uid)
        if uid:
            cached = get_catalog_item("User", uid)
            if cached:
                label = cached.get("full_name") or cached.get("name") or str(uid)
            else:
                try:
                    u = glpi.get(f"User/{uid}")
                    upsert_catalog_item("User", u)
                    first = str(u.get("firstname") or "").strip()
                    last = str(u.get("realname") or "").strip()
                    label = " ".join(x for x in [first, last] if x).strip() or str(u.get("name") or uid)
                except Exception:
                    pass
        return {**rel, "label": label}

    def group_obj(rel):
        gid = int(rel.get("groups_id") or 0)
        label = str(gid)
        if gid:
            cached = get_catalog_item("Group", gid)
            if cached:
                label = cached.get("full_name") or cached.get("name") or str(gid)
            else:
                try:
                    g = glpi.get(f"Group/{gid}")
                    upsert_catalog_item("Group", g)
                    label = g.get("completename") or g.get("name") or str(gid)
                except Exception:
                    pass
        return {**rel, "label": label}

    try:
        status_num = int(ticket.get("status") or 0)
    except (TypeError, ValueError):
        status_num = 0
    try:
        priority_num = int(ticket.get("priority") or 0)
    except (TypeError, ValueError):
        priority_num = 0

    return {
        "id": int(ticket["id"]),
        "title": decode_glpi_text(ticket.get("name")),
        "url": glpi.base.rstrip("/") + f"/front/ticket.form.php?id={int(ticket['id'])}",
        "entity_id": entity_id,
        "entity": {"id": entity_id, "label": decode_glpi_text(entity_label)},
        "category": {"id": category_id, "label": decode_glpi_text(category_label)},
        "status": status_num,
        "status_label": TICKET_STATUS_LABELS.get(status_num, f"Status {status_num}" if status_num else "—"),
        "priority": priority_num,
        "priority_label": TICKET_PRIORITY_LABELS.get(priority_num, f"Prioridade {priority_num}" if priority_num else "—"),
        "requesters": [user_obj(r) for r in users if r.get("type") == 1],
        "observers": [user_obj(r) for r in users if r.get("type") == 3],
        "assigned_users": [user_obj(r) for r in users if r.get("type") == 2],
        "assigned_groups": [group_obj(r) for r in groups if r.get("type") == 2],
        "raw": ticket,
    }


@app.get("/api/ticket/{ticket_id}")
def ticket(ticket_id: int):
    try:
        with _client() as glpi:
            return _ticket_snapshot(glpi, ticket_id)
    except Exception as exc:
        _error(exc)


@app.put("/api/ticket/{ticket_id}")
def update_ticket_manual(ticket_id: int, payload: TicketEditPayload, request: Request):
    _require_local_ui(request)
    """Manual editor for the most useful Ticket fields.

    It intentionally writes only fields explicitly present in the request.
    Actor relations are handled by their own endpoints so requester/group/user
    changes stay visible and auditable in the UI.
    """
    try:
        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            fields: dict[str, Any] = {}
            changed: list[dict[str, Any]] = []

            if payload.title is not None:
                title = payload.title.strip()
                if not title:
                    raise ValueError("O título do chamado não pode ficar vazio.")
                if title != snap["title"]:
                    fields["name"] = title
                    changed.append({"field": "title", "from": snap["title"], "to": title})

            if payload.category is not None:
                category_query = payload.category.strip()
                if category_query:
                    category = _resolve_catalog_live(
                        glpi, "ITILCategory", category_query, snap["entity_id"]
                    )
                    if int(category["id"]) != int(snap["category"]["id"]):
                        fields["itilcategories_id"] = int(category["id"])
                        changed.append({
                            "field": "category",
                            "from": snap["category"],
                            "to": category,
                        })

            if payload.status is not None:
                status = int(payload.status)
                if status not in TICKET_STATUS_LABELS:
                    raise ValueError(f"Status de chamado inválido: {status}")
                if status != int(snap.get("status") or 0):
                    fields["status"] = status
                    changed.append({
                        "field": "status",
                        "from": snap.get("status"),
                        "to": status,
                    })

            if payload.priority is not None:
                priority = int(payload.priority)
                if priority not in TICKET_PRIORITY_LABELS:
                    raise ValueError(f"Prioridade inválida: {priority}")
                if priority != int(snap.get("priority") or 0):
                    fields["priority"] = priority
                    changed.append({
                        "field": "priority",
                        "from": snap.get("priority"),
                        "to": priority,
                    })

            glpi.update_ticket_fields(ticket_id, fields)
            refreshed = _ticket_snapshot(glpi, ticket_id)

        return {"ok": True, "changed": changed, "ticket": refreshed}
    except Exception as exc:
        _error(exc)


def _actor_type(role: str) -> int:
    normalized = (role or "").strip().casefold()
    mapping = {
        "requester": 1,
        "requerente": 1,
        "assigned": 2,
        "atribuido": 2,
        "atribuído": 2,
        "observer": 3,
        "observador": 3,
    }
    if normalized not in mapping:
        raise ValueError(f"Papel de ator inválido: {role}")
    return mapping[normalized]


@app.post("/api/ticket/{ticket_id}/actors")
def add_ticket_actor_manual(ticket_id: int, payload: ActorEditPayload, request: Request):
    _require_local_ui(request)
    try:
        kind = (payload.kind or "").strip().casefold()
        if kind not in {"user", "group"}:
            raise ValueError("kind deve ser 'user' ou 'group'.")
        actor_type = _actor_type(payload.role)
        query = payload.query.strip()
        if not query:
            raise ValueError("Informe o usuário ou grupo a adicionar.")

        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            catalog_kind = "User" if kind == "user" else "Group"
            item = _resolve_catalog_live(glpi, catalog_kind, query, snap["entity_id"])
            if kind == "user":
                current = glpi.ticket_users(ticket_id)
                if any(
                    int(r.get("type") or 0) == actor_type
                    and int(r.get("users_id") or 0) == int(item["id"])
                    for r in current
                ):
                    relation_id = next(
                        int(r["id"]) for r in current
                        if int(r.get("type") or 0) == actor_type
                        and int(r.get("users_id") or 0) == int(item["id"])
                    )
                    created = False
                else:
                    relation_id = glpi.add_ticket_user(ticket_id, int(item["id"]), actor_type)
                    created = True
            else:
                current = glpi.ticket_groups(ticket_id)
                if any(
                    int(r.get("type") or 0) == actor_type
                    and int(r.get("groups_id") or 0) == int(item["id"])
                    for r in current
                ):
                    relation_id = next(
                        int(r["id"]) for r in current
                        if int(r.get("type") or 0) == actor_type
                        and int(r.get("groups_id") or 0) == int(item["id"])
                    )
                    created = False
                else:
                    relation_id = glpi.add_ticket_group(ticket_id, int(item["id"]), actor_type)
                    created = True

            refreshed = _ticket_snapshot(glpi, ticket_id)

        return {
            "ok": True,
            "created": created,
            "relation_id": relation_id,
            "item": item,
            "ticket": refreshed,
        }
    except Exception as exc:
        _error(exc)


@app.put("/api/ticket/{ticket_id}/requester")
def replace_ticket_requester_manual(ticket_id: int, payload: ReplaceRequesterPayload, request: Request):
    _require_local_ui(request)
    try:
        query = payload.query.strip()
        if not query:
            raise ValueError("Informe o requerente substituto.")
        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            item = _resolve_catalog_live(glpi, "User", query, snap["entity_id"])
            target = int(item["id"])
            current = glpi.ticket_users(ticket_id)
            requester_rows = [r for r in current if int(r.get("type") or 0) == 1]
            if len(requester_rows) == 1 and int(requester_rows[0].get("users_id") or 0) == target:
                refreshed = snap
                changed = False
            else:
                for rel in requester_rows:
                    if int(rel.get("users_id") or 0) != target:
                        glpi.delete_ticket_user_relation(int(rel["id"]))
                if not any(int(rel.get("users_id") or 0) == target for rel in requester_rows):
                    glpi.add_ticket_user(ticket_id, target, 1)
                refreshed = _ticket_snapshot(glpi, ticket_id)
                changed = True
        return {"ok": True, "changed": changed, "requester": item, "ticket": refreshed}
    except Exception as exc:
        _error(exc)


@app.put("/api/ticket/{ticket_id}/technician")
def replace_ticket_technician_manual(ticket_id: int, payload: ReplaceRequesterPayload, request: Request):
    _require_local_ui(request)
    try:
        query = payload.query.strip()
        if not query:
            raise ValueError("Informe o técnico substituto.")
        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            item = _resolve_catalog_live(glpi, "User", query, snap["entity_id"])
            target = int(item["id"])
            current = glpi.ticket_users(ticket_id)
            assigned_rows = [r for r in current if int(r.get("type") or 0) == 2]
            changed = not (
                len(assigned_rows) == 1
                and int(assigned_rows[0].get("users_id") or 0) == target
            )
            if changed:
                for rel in assigned_rows:
                    if int(rel.get("users_id") or 0) != target:
                        glpi.delete_ticket_user_relation(int(rel["id"]))
                if not any(int(rel.get("users_id") or 0) == target for rel in assigned_rows):
                    glpi.add_ticket_user(ticket_id, target, 2)

            # Never report success without confirming the actual Ticket_User row.
            verified = [
                r for r in glpi.ticket_users(ticket_id)
                if int(r.get("type") or 0) == 2 and int(r.get("users_id") or 0) == target
            ]
            if not verified:
                raise GlpiError(
                    f"O GLPI respondeu à alteração, mas o técnico {item.get('full_name') or target} "
                    "não apareceu como atribuído na releitura do chamado."
                )
            refreshed = _ticket_snapshot(glpi, ticket_id)
        return {"ok": True, "changed": changed, "item": item, "ticket": refreshed}
    except Exception as exc:
        _error(exc)


@app.delete("/api/ticket/{ticket_id}/actors/{kind}/{relation_id}")
def delete_ticket_actor_manual(ticket_id: int, kind: str, relation_id: int, request: Request):
    _require_local_ui(request)
    try:
        normalized = (kind or "").strip().casefold()
        if normalized not in {"user", "group"}:
            raise ValueError("kind deve ser 'user' ou 'group'.")
        with _client() as glpi:
            _ticket_snapshot(glpi, ticket_id)
            if normalized == "user":
                rows = glpi.ticket_users(ticket_id)
                rel = next((r for r in rows if int(r.get("id") or 0) == relation_id), None)
                if not rel:
                    raise ValueError(f"Relação de usuário #{relation_id} não pertence ao chamado.")
                glpi.delete_ticket_user_relation(relation_id)
            else:
                rows = glpi.ticket_groups(ticket_id)
                rel = next((r for r in rows if int(r.get("id") or 0) == relation_id), None)
                if not rel:
                    raise ValueError(f"Relação de grupo #{relation_id} não pertence ao chamado.")
                glpi.delete_ticket_group_relation(relation_id)
            refreshed = _ticket_snapshot(glpi, ticket_id)
        return {"ok": True, "deleted_relation_id": relation_id, "ticket": refreshed}
    except Exception as exc:
        _error(exc)


def _html_to_text(value: Any) -> str:
    import re

    text = decode_glpi_text(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)<p(?:\s+[^>]*)?>", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _task_logical_id(value: Any) -> str | None:
    import re

    text = decode_glpi_text(value)
    m = re.search(r"<!--\s*glpi-assistant:[^:>]+:(?P<id>[^>]+?)\s*-->", text, re.I)
    return m.group("id").strip() if m else None


def _replace_evidence_marker(rendered_html: str, evidence_id: str, inline_html: str) -> str:
    """Replace exactly one evidence marker using the parser's accepted syntax."""
    evidence_id = str(evidence_id or '').upper()
    marker_re = re.compile(
        r"\[EVID[ÊE]NCIA\s*:\s*" + re.escape(evidence_id) + r"\s*\]",
        re.I,
    )
    result, replaced = marker_re.subn(lambda _m: inline_html, rendered_html)
    if replaced != 1:
        raise ValueError(
            f"Marcador {evidence_id} não foi encontrado exatamente uma vez no HTML da tarefa"
        )
    return result


def _task_compare_text(value: Any) -> str:
    """Canonical text used only for conservative duplicate detection.

    Evidence markers and the five standard section headings are intentionally
    ignored because an already-created task may have had its evidence marker
    replaced by inline HTML. The body remains the source of truth.
    """
    import re
    import unicodedata

    text = _html_to_text(value)
    text = EVIDENCE_RE.sub(" ", text)
    text = text.replace("\\.", ".").replace("**", " ").replace("__", " ")
    text = re.sub(
        r"(?im)^\s*[1-5]\s*[.)-]?\s*(problema informado|problema identificado|diagn[oó]stico|solu[cç][aã]o aplicada|valida[cç][aã]o do cliente)\s*$",
        " ",
        text,
    )
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _task_similarity(a: Any, b: Any) -> tuple[float, str]:
    """Return a conservative semantic-ish similarity without an AI API."""
    from difflib import SequenceMatcher

    left = _task_compare_text(a)
    right = _task_compare_text(b)
    if not left or not right:
        return 0.0, "empty"
    if left == right:
        return 1.0, "exact"

    # Very short support notes are too easy to collide accidentally.
    if min(len(left), len(right)) < 36:
        return 0.0, "short"

    ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
    lt = set(left.split())
    rt = set(right.split())
    jaccard = len(lt & rt) / max(1, len(lt | rt))
    containment = min(len(lt & rt) / max(1, len(lt)), len(lt & rt) / max(1, len(rt)))

    # Require agreement from character order AND vocabulary. This threshold is
    # intentionally high: false negatives are preferable to dropping a real
    # technical action merely because two notes discuss the same incident.
    if ratio >= 0.94 and jaccard >= 0.82 and containment >= 0.90:
        return min(0.999, (ratio + jaccard + containment) / 3), "near_exact"
    return max(ratio, jaccard), "different"


def _existing_task_candidates(glpi: GlpiClient, ticket_id: int) -> list[dict[str, Any]]:
    """Cheap task history for planning: no document lookups or label GETs."""
    out: list[dict[str, Any]] = []
    for raw in glpi.ticket_tasks(ticket_id):
        tid = int(raw.get("id") or 0)
        if not tid:
            continue
        out.append({
            "id": tid,
            "logical_id": (_task_logical_id(raw.get("content")) or "").upper() or None,
            "content": raw.get("content") or "",
            "content_text": _html_to_text(raw.get("content")),
        })
    import initial_reply
    uid = glpi.current_user_id()
    for row in glpi.list_subitems('Ticket', ticket_id, 'ITILFollowup'):
        if initial_reply.belongs(row, ticket_id, uid):
            out.append({'id': int(row['id']), 'resource': 'ITILFollowup', 'logical_id': 'T01',
                        'content': row.get('content') or '', 'content_text': _html_to_text(row.get('content'))})
    return out


def _partition_incoming_tasks(
    tasks: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Interpret a closure against what is already registered in GLPI.

    A closure can contain all T01-T05 or only a remaining subset. Existing
    tasks are matched one-to-one by Assistant logical ID first and by a
    conservative normalized-content comparison second. Only missing tasks are
    returned for creation.
    """
    missing: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    used_existing: set[tuple] = set()
    accepted_incoming: list[dict[str, Any]] = []

    for task in tasks:
        logical = str(task.get("id") or "").strip().upper()
        match: dict[str, Any] | None = None
        reason = ""
        score = 0.0

        for item in existing:
            eid = int(item.get("id") or 0)
            if (item.get('resource', 'TicketTask'), eid) in used_existing:
                continue
            if logical and str(item.get("logical_id") or "").upper() == logical:
                match, reason, score = item, "logical_id", 1.0
                break

        if match is None:
            best: tuple[float, dict[str, Any] | None, str] = (0.0, None, "")
            for item in existing:
                eid = int(item.get("id") or 0)
                if (item.get('resource', 'TicketTask'), eid) in used_existing:
                    continue
                candidate_score, candidate_reason = _task_similarity(task.get("content"), item.get("content"))
                if candidate_reason in {"exact", "near_exact"} and candidate_score > best[0]:
                    best = (candidate_score, item, candidate_reason)
            score, match, reason = best

        # Also block accidental duplicate text within the same incoming closure.
        if match is None:
            for previous in accepted_incoming:
                candidate_score, candidate_reason = _task_similarity(task.get("content"), previous.get("content"))
                if candidate_reason in {"exact", "near_exact"} and candidate_score >= 0.94:
                    skipped.append({
                        "task": task,
                        "existing_task_id": None,
                        "existing_logical_id": previous.get("id"),
                        "reason": "duplicate_in_closure",
                        "score": candidate_score,
                    })
                    match = {"id": 0}
                    break

        if match is not None:
            eid = int(match.get("id") or 0)
            if eid:
                used_existing.add((match.get('resource', 'TicketTask'), eid))
                skipped.append({
                    "task": task,
                    "existing_task_id": eid,
                    "existing_resource": match.get("resource", "TicketTask"),
                    "existing_logical_id": match.get("logical_id"),
                    "reason": reason,
                    "score": score,
                })
            continue

        missing.append(task)
        accepted_incoming.append(task)

    return missing, skipped


def _task_state_label(state: Any) -> str:
    try:
        n = int(state)
    except (TypeError, ValueError):
        return str(state or "—")
    return {1: "A fazer", 2: "Feito"}.get(n, f"Estado {n}")


def _ticket_task_list(glpi: GlpiClient, ticket_id: int, include_documents: bool = True) -> list[dict[str, Any]]:
    tasks = glpi.ticket_tasks(ticket_id)
    user_cache: dict[int, str] = {}
    group_cache: dict[int, str] = {}
    doc_cache: dict[int, dict[str, Any]] = {}

    def user_label(uid: int) -> str:
        if not uid:
            return "—"
        if uid not in user_cache:
            label = str(uid)
            cached = get_catalog_item("User", uid)
            if cached:
                label = str(cached.get("full_name") or cached.get("name") or uid)
            else:
                try:
                    u = glpi.get(f"User/{uid}")
                    upsert_catalog_item("User", u)
                    first = str(u.get("firstname") or "").strip()
                    last = str(u.get("realname") or "").strip()
                    label = " ".join(x for x in (first, last) if x).strip() or str(u.get("name") or uid)
                except Exception:
                    pass
            user_cache[uid] = label
        return user_cache[uid]

    def group_label(gid: int) -> str:
        if not gid:
            return "—"
        if gid not in group_cache:
            label = str(gid)
            cached = get_catalog_item("Group", gid)
            if cached:
                label = str(cached.get("full_name") or cached.get("name") or gid)
            else:
                try:
                    g = glpi.get(f"Group/{gid}")
                    upsert_catalog_item("Group", g)
                    label = str(g.get("completename") or g.get("name") or gid)
                except Exception:
                    pass
            group_cache[gid] = label
        return group_cache[gid]

    out: list[dict[str, Any]] = []
    for task in tasks:
        task_id = int(task.get("id") or 0)
        docs: list[dict[str, Any]] = []
        if task_id and include_documents:
            try:
                links = glpi.task_documents(task_id)
            except Exception:
                links = []
            for rel in links:
                did = int(rel.get("documents_id") or 0)
                if not did:
                    continue
                if did not in doc_cache:
                    try:
                        doc_cache[did] = glpi.document(did)
                    except Exception:
                        doc_cache[did] = {"id": did}
                doc = doc_cache[did]
                docs.append({
                    "id": did,
                    "name": str(doc.get("name") or doc.get("filename") or f"Documento {did}"),
                    "filename": str(doc.get("filename") or ""),
                    "mime": str(doc.get("mime") or ""),
                    "relation_id": int(rel.get("id") or 0),
                })

        tech_id = int(task.get("users_id_tech") or 0)
        group_id = int(task.get("groups_id_tech") or 0)
        actiontime = int(task.get("actiontime") or 0)
        out.append({
            "id": task_id,
            "logical_id": _task_logical_id(task.get("content")),
            "date": task.get("date_creation") or task.get("date"),
            "date_mod": task.get("date_mod"),
            "state": int(task.get("state") or 0),
            "state_label": _task_state_label(task.get("state")),
            "actiontime": actiontime,
            "tech_user_id": tech_id,
            "tech_label": user_label(tech_id),
            "group_id": group_id,
            "group_label": group_label(group_id),
            "content_text": _html_to_text(task.get("content")),
            "documents": docs,
            "documents_loaded": include_documents,
            "created_by_user_id": int(task.get("users_id") or 0),
        })

    out.sort(key=lambda x: (str(x.get("date") or ""), int(x.get("id") or 0)), reverse=True)
    return out


@app.get("/api/ticket/{ticket_id}/tasks")
def ticket_tasks(ticket_id: int, include_documents: bool = False):
    try:
        with _client() as glpi:
            ticket_obj = glpi.activate_context_for_ticket(ticket_id)
            if int(ticket_obj.get("id") or 0) != ticket_id:
                raise ValueError("Chamado não encontrado.")
            tasks = _ticket_task_list(glpi, ticket_id, include_documents=include_documents)
        return {"ticket_id": ticket_id, "count": len(tasks), "tasks": tasks}
    except Exception as exc:
        _error(exc)


@app.get("/api/ticket/{ticket_id}/tasks/{task_id}/documents")
def task_document_list(ticket_id: int, task_id: int):
    try:
        with _client() as glpi:
            glpi.activate_context_for_ticket(ticket_id)
            task=glpi.ticket_task(task_id)
            if int(task.get('tickets_id') or 0)!=ticket_id:
                raise ValueError('Tarefa não pertence ao chamado')
            docs=[]
            for link in glpi.task_documents(task_id):
                did=int(link.get('documents_id') or 0)
                if not did: continue
                doc=glpi.document(did)
                docs.append({'id':did,'name':str(doc.get('name') or doc.get('filename') or f'Documento {did}')})
            return {'ticket_id':ticket_id,'task_id':task_id,'documents':docs}
    except Exception as exc:
        _error(exc)


@app.delete("/api/ticket/{ticket_id}/tasks/{task_id}")
def delete_ticket_task(ticket_id: int, task_id: int, request: Request):
    _require_local_ui(request)
    try:
        with _client() as glpi:
            ticket_obj = glpi.activate_context_for_ticket(ticket_id)
            if int(ticket_obj.get("id") or 0) != ticket_id:
                raise ValueError("Chamado não encontrado.")
            task = glpi.ticket_task(task_id)
            if int(task.get("tickets_id") or 0) != ticket_id:
                raise ValueError(
                    f"A tarefa #{task_id} não pertence ao chamado #{ticket_id}."
                )
            documents = glpi.task_documents(task_id)
            glpi.delete_task(task_id)
            remaining = _ticket_task_list(glpi, ticket_id)
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "deleted_task_id": task_id,
            "linked_documents_before_delete": [int(x.get("documents_id") or 0) for x in documents],
            "tasks": remaining,
        }
    except Exception as exc:
        _error(exc)


@app.post("/api/ticket/{ticket_id}/tasks/bulk-delete")
def bulk_delete_ticket_tasks(ticket_id: int, payload: TaskBulkDeletePayload, request: Request):
    _require_local_ui(request)
    try:
        task_ids = sorted({int(x) for x in payload.task_ids if int(x) > 0})
        if not task_ids:
            raise ValueError("Selecione ao menos uma tarefa para excluir.")
        if len(task_ids) > 100:
            raise ValueError("Exclusão em massa limitada a 100 tarefas por operação.")

        with _client() as glpi:
            ticket_obj = glpi.activate_context_for_ticket(ticket_id)
            if int(ticket_obj.get("id") or 0) != ticket_id:
                raise ValueError("Chamado não encontrado.")

            # Preflight completo: nenhuma exclusão começa antes de confirmar que
            # todas as IDs selecionadas pertencem ao chamado carregado.
            existing = {int(x.get("id") or 0): x for x in glpi.ticket_tasks(ticket_id)}
            invalid = [tid for tid in task_ids if tid not in existing]
            if invalid:
                raise ValueError(
                    "Exclusão bloqueada: estas tarefas não pertencem ao chamado "
                    f"#{ticket_id}: {', '.join(map(str, invalid))}."
                )

            deleted: list[int] = []
            failed: list[dict[str, Any]] = []
            for tid in task_ids:
                try:
                    glpi.delete_task(tid)
                    deleted.append(tid)
                except Exception as exc:
                    failed.append({"task_id": tid, "message": str(exc)})

            remaining = _ticket_task_list(glpi, ticket_id)

        return {
            "ok": not failed,
            "partial": bool(failed),
            "ticket_id": ticket_id,
            "requested_count": len(task_ids),
            "deleted_count": len(deleted),
            "deleted_task_ids": deleted,
            "failed": failed,
            "tasks": remaining,
        }
    except Exception as exc:
        _error(exc)


def _task_marker_html(raw_content: Any, logical_id: str | None = None) -> str:
    import re

    raw = decode_glpi_text(raw_content)
    m = re.search(r"<!--\s*glpi-assistant:[^>]+?-->", raw, re.I)
    if m:
        return m.group(0)
    if logical_id:
        return f"<!-- glpi-assistant:{VERSION}:{html.escape(str(logical_id), quote=True)} -->"
    return ""


@app.put("/api/ticket/{ticket_id}/tasks/{task_id}")
def update_ticket_task_manual(ticket_id: int, task_id: int, payload: TaskEditPayload, request: Request):
    _require_local_ui(request)
    try:
        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            task = glpi.ticket_task(task_id)
            if int(task.get("tickets_id") or 0) != ticket_id:
                raise ValueError(f"A tarefa #{task_id} não pertence ao chamado #{ticket_id}.")

            fields: dict[str, Any] = {}
            if payload.content is not None:
                content = payload.content.strip()
                if not content:
                    raise ValueError("O conteúdo da tarefa não pode ficar vazio.")
                marker = _task_marker_html(task.get("content"), _task_logical_id(task.get("content")))
                fields["content"] = marker + _markdownish_to_html(content)

            if payload.time is not None:
                fields["actiontime"] = parse_duration(payload.time)

            if payload.state is not None:
                fields["state"] = task_state(payload.state)

            if payload.technician is not None:
                technician = payload.technician.strip()
                if technician:
                    item = _resolve_catalog_live(glpi, "User", technician, snap["entity_id"])
                    fields["users_id_tech"] = int(item["id"])

            if payload.modality is not None:
                modality = payload.modality.strip()
                if modality:
                    item = _resolve_catalog_live(glpi, "Group", modality, snap["entity_id"])
                    fields["groups_id_tech"] = int(item["id"])

            if "content" in fields:
                candidates = [x for x in _existing_task_candidates(glpi, ticket_id) if int(x.get("id") or 0) != task_id]
                incoming = [{"id": _task_logical_id(task.get("content")) or f"EDIT-{task_id}", "content": fields["content"]}]
                _, dup = _partition_incoming_tasks(incoming, candidates)
                if dup:
                    other = dup[0].get("existing_task_id")
                    raise ValueError(
                        f"Conteúdo repetido: a tarefa #{other} já representa este lançamento. "
                        "A edição foi bloqueada para evitar duplicidade."
                    )

            glpi.update_task(task_id, fields)
            tasks = _ticket_task_list(glpi, ticket_id)

        return {"ok": True, "task_id": task_id, "tasks": tasks}
    except Exception as exc:
        _error(exc)


@app.post("/api/ticket/{ticket_id}/tasks/manual")
def create_ticket_task_manual(ticket_id: int, payload: ManualTaskPayload, request: Request):
    _require_local_ui(request)
    try:
        content = payload.content.strip()
        if not content:
            raise ValueError("O conteúdo da tarefa não pode ficar vazio.")

        with _client() as glpi:
            snap = _ticket_snapshot(glpi, ticket_id)
            current_user_id = glpi.current_user_id()
            tech_id = current_user_id
            if payload.technician and payload.technician.strip():
                tech = _resolve_catalog_live(glpi, "User", payload.technician.strip(), snap["entity_id"])
                tech_id = int(tech["id"])
            modality = _resolve_catalog_live(glpi, "Group", payload.modality, snap["entity_id"])

            existing = _existing_task_candidates(glpi, ticket_id)
            _, dup = _partition_incoming_tasks([{"id": "MANUAL-CHECK", "content": content}], existing)
            if dup:
                other = dup[0].get("existing_task_id")
                raise ValueError(
                    f"Conteúdo repetido: a tarefa #{other} já representa este lançamento. "
                    "Nada foi criado."
                )

            logical_id = f"MANUAL-{secrets.token_hex(4).upper()}"
            marker = f"<!-- glpi-assistant:{VERSION}:{logical_id} -->"
            task_id = glpi.create_task(
                ticket_id=ticket_id,
                content=marker + _markdownish_to_html(content),
                actiontime=parse_duration(payload.time),
                state=task_state(payload.state),
                tech_user_id=tech_id,
                group_id=int(modality["id"]),
            )
            tasks = _ticket_task_list(glpi, ticket_id)

        return {
            "ok": True,
            "task_id": task_id,
            "logical_id": logical_id,
            "tasks": tasks,
        }
    except Exception as exc:
        _error(exc)


@app.post("/api/parse")
def parse_endpoint(payload: ParsePayload, request: Request):
    _require_local_ui(request)
    try:
        return parse_closure(payload.text)
    except Exception as exc:
        _error(exc)


@app.post("/api/parse-batch")
def parse_batch_endpoint(payload: BatchParsePayload, request: Request):
    """Validate a multi-ticket AI response without writing anything to GLPI."""
    _require_local_ui(request)
    try:
        rows = split_closure_batch(payload.text)
        if not rows:
            raise ValueError("Nenhum marcador [GLPI_ASSISTANT:<ID>] encontrado no lote.")
        return {
            "ok": True,
            "count": len(rows),
            "items": [
                {
                    "ticket_id": item["ticket_id"],
                    "closure": item["closure"],
                    "parsed": parse_closure(item["closure"]),
                }
                for item in rows
            ],
        }
    except Exception as exc:
        _error(exc)


_REVIEW_STOPWORDS = {
    "a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "um", "uma", "foi", "foram", "realizado", "realizada", "realizados", "realizadas",
    "usuario", "usuaria", "cliente", "chamado", "atendimento", "problema", "solucao", "aplicada", "aplicado",
}


def _review_norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", decode_glpi_text(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _review_tokens(value: Any) -> set[str]:
    return {
        token for token in _review_norm(value).split()
        if len(token) > 2 and token not in _REVIEW_STOPWORDS
    }


def _clean_title_sentence(value: str) -> str:
    text = EVIDENCE_RE.sub(" ", value or "")
    text = re.sub(r"(?im)^\s*\*{0,2}\d+[\\.)-]?\s*[^\n*]+\*{0,2}\s*$", " ", text)
    text = re.sub(r"[*_`#>|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    prefixes = (
        r"^(?:foi|foram)\s+(?:identificado|identificada|identificados|identificadas)\s+(?:que\s+)?",
        r"^(?:identificado|identificada)\s+(?:que\s+)?",
        r"^(?:verificou-se|constatou-se)\s+(?:que\s+)?",
        r"^(?:o|a)\s+(?:usuario|usuaria|cliente)\s+(?:relatou|informou)\s+(?:que\s+)?",
    )
    for pattern in prefixes:
        text = re.sub(pattern, "", text, flags=re.I)
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" .:-")
    if len(sentence) > 112:
        sentence = sentence[:109].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    if sentence:
        sentence = sentence[0].upper() + sentence[1:]
    return sentence


def _suggest_title(parsed: dict[str, Any], snap: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(task.get("id")): str(task.get("content") or "") for task in parsed.get("tasks", [])}
    candidate = ""
    source = ""
    for task_id, label in (("T02", "Problema Identificado"), ("T04", "Solução Aplicada"), ("T01", "Problema Informado")):
        candidate = _clean_title_sentence(by_id.get(task_id, ""))
        if len(_review_tokens(candidate)) >= 2:
            source = label
            break
    current = str(snap.get("title") or "").strip()
    if not candidate or _review_norm(candidate) == _review_norm(current):
        return {"value": None, "confidence": 0.0, "source": source, "reason": "Título atual já representa o fechamento ou não houve frase técnica suficiente."}
    generic = _review_norm(current) in {
        "abrir uma solicitacao", "solicitacao", "suporte", "chamado", "abrir chamado", "nova solicitacao"
    } or len(_review_tokens(current)) < 2
    confidence = 0.88 if generic else 0.70
    return {
        "value": candidate,
        "confidence": confidence,
        "source": source,
        "reason": "Título derivado do fechamento; confirme antes de aplicar.",
    }


def _category_review_candidates(parsed: dict[str, Any], snap: dict[str, Any]) -> list[dict[str, Any]]:
    entity_id = int(snap.get("entity_id") or 0)
    ticket_raw = snap.get("raw") or {}
    task_text = " ".join(str(task.get("content") or "") for task in parsed.get("tasks", []))
    corpus = " ".join([str(snap.get("title") or ""), decode_glpi_text(ticket_raw.get("content")), task_text])
    corpus_norm = _review_norm(corpus)
    corpus_tokens = _review_tokens(corpus)
    categories = list_catalog("ITILCategory", "", 5000)
    ranked: list[dict[str, Any]] = []
    for item in categories:
        item_entity = item.get("entity_id")
        if item_entity not in (None, 0, entity_id):
            continue
        label = str(item.get("full_name") or item.get("name") or "").strip()
        tokens = _review_tokens(label)
        if not tokens:
            continue
        common = tokens & corpus_tokens
        coverage = len(common) / len(tokens)
        precision = len(common) / max(1, min(len(corpus_tokens), max(4, len(tokens) * 3)))
        leaf = str(item.get("name") or label.split(" > ")[-1]).strip()
        leaf_norm = _review_norm(leaf)
        phrase = 1.0 if leaf_norm and len(leaf_norm) >= 4 and leaf_norm in corpus_norm else 0.0
        entity_bonus = 0.04 if item_entity == entity_id else 0.015
        score = min(1.0, 0.62 * coverage + 0.18 * precision + 0.16 * phrase + entity_bonus)
        if score < 0.12:
            continue
        ranked.append({
            "id": int(item["id"]),
            "name": item.get("name") or label,
            "full_name": label,
            "entity_id": item_entity,
            "score": round(score, 4),
            "matched_terms": sorted(common),
        })
    ranked.sort(key=lambda row: (-row["score"], row["full_name"].casefold(), row["id"]))
    return ranked[:8]


@app.post("/api/review/suggest")
def review_suggest(payload: ReviewSuggestPayload, request: Request):
    """Conservative local review of title/category against the current closure.

    This endpoint never writes to GLPI. It surfaces a proposal and alternatives
    so the technician remains the decision maker.
    """
    _require_local_ui(request)
    try:
        resolve_bridge_ticket_id(payload.ticket_id, payload.text)
        parsed = parse_closure(payload.text)
        with _client() as glpi:
            snap = _ticket_snapshot(glpi, payload.ticket_id)
        candidates = _category_review_candidates(parsed, snap)
        current_category_id = int((snap.get("category") or {}).get("id") or 0)
        current_score = next((row["score"] for row in candidates if row["id"] == current_category_id), 0.0)
        top = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        recommended = None
        # Deliberately conservative: recommendation only when the closure has a
        # strong lexical fit and there is meaningful separation from runner-up.
        if top and top["id"] != current_category_id:
            margin = top["score"] - (second["score"] if second else 0.0)
            if top["score"] >= 0.48 and margin >= 0.07 and top["score"] >= current_score + 0.10:
                recommended = top
        return {
            "ok": True,
            "ticket_id": payload.ticket_id,
            "current": {
                "title": snap.get("title") or "",
                "category": snap.get("category") or {},
                "category_fit": round(float(current_score), 4),
                "groups": [str(item.get("label") or item.get("groups_id") or "").strip() for item in snap.get("assigned_groups", []) if str(item.get("label") or item.get("groups_id") or "").strip()],
                "technicians": [str(item.get("label") or item.get("users_id") or "").strip() for item in snap.get("assigned_users", []) if str(item.get("label") or item.get("users_id") or "").strip()],
            },
            "title": _suggest_title(parsed, snap),
            "category": {
                "recommended": recommended,
                "candidates": candidates[:5],
                "reason": (
                    "Sugestão disponível; confirme ou edite antes do Dry Run."
                    if recommended else
                    "Nenhuma troca automática sugerida com confiança suficiente. Revise as alternativas se necessário."
                ),
            },
        }
    except Exception as exc:
        _error(exc)


def _resolve_catalog_live(
    glpi: GlpiClient,
    kind: str,
    query: str,
    entity_id: int | None = None,
) -> dict[str, Any]:
    """Resolve an operational catalog value without silently guessing.

    Fast path is the local SQLite catalog. For User, a targeted Search API
    lookup is attempted before a global list because restricted technicians
    often can use GLPI's assignee picker while GET /User is forbidden. The
    final resolver remains conservative and rejects ambiguous people/groups.
    """
    query = str(query or "").strip()
    first_error: Exception | None = None

    # Explicit numeric forms are useful when two people have the same name.
    if kind == "User":
        m = re.fullmatch(r"(?:id\s*[:#]?\s*|#)?(\d+)", query, re.I)
        if m:
            uid = int(m.group(1))
            try:
                user = glpi.get(f"User/{uid}")
                if isinstance(user, dict) and int(user.get("id") or 0) == uid:
                    upsert_catalog_item("User", user)
                    cached = get_catalog_item("User", uid)
                    if cached:
                        return {
                            "id": int(cached["id"]),
                            "name": cached.get("name") or str(uid),
                            "full_name": cached.get("full_name") or cached.get("name") or str(uid),
                            "entity_id": cached.get("entity_id"),
                            "raw": cached.get("raw") or user,
                            "match": {"query": query, "method": "id", "score": 1.0},
                        }
            except Exception as exc:
                first_error = exc

    try:
        return resolve_catalog(kind, query, entity_id)
    except LookupError as exc:
        if "ambígu" in str(exc).casefold():
            raise
        first_error = exc

    try:
        if entity_id:
            try:
                glpi.change_active_entity(int(entity_id), recursive=True)
            except Exception:
                pass

        # Targeted user search mirrors the picker behavior and is much cheaper
        # than enumerating every user. It also works in some restricted profiles
        # where list_all("User") does not.
        if kind == "User":
            try:
                ids = glpi.search_user_ids(query, limit=30)
            except Exception:
                ids = []
            for uid in ids:
                try:
                    user = glpi.get(f"User/{uid}")
                    if isinstance(user, dict) and user.get("id"):
                        upsert_catalog_item("User", user)
                except Exception:
                    continue
            if ids:
                try:
                    return resolve_catalog(kind, query, entity_id)
                except LookupError as exc:
                    if "ambígu" in str(exc).casefold():
                        raise
                    first_error = exc

        items = glpi.list_all(kind)
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                upsert_catalog_item(kind, item)
    except Exception as refresh_exc:
        raise LookupError(
            f"{kind} não encontrado para '{query}'. "
            f"O catálogo local não resolveu e a busca ao vivo no GLPI falhou: {refresh_exc}"
        ) from first_error

    return resolve_catalog(kind, query, entity_id)


def _resolve_changes(
    glpi: GlpiClient,
    changes: dict[str, Any] | None,
    entity_id: int | None = None,
) -> dict[str, Any] | None:
    if not changes:
        return None
    resolved: dict[str, Any] = {}
    if changes.get("titulo"):
        title = re.sub(r"\s+", " ", str(changes["titulo"])).strip()
        if not title:
            raise ValueError("Título sugerido vazio.")
        if len(title) > 180:
            raise ValueError("Título sugerido excede 180 caracteres.")
        resolved["titulo"] = title
    if changes.get("categoria"):
        resolved["categoria"] = _resolve_catalog_live(glpi, "ITILCategory", changes["categoria"], entity_id)
    if changes.get("requerente"):
        resolved["requerente"] = _resolve_catalog_live(glpi, "User", changes["requerente"], entity_id)
    for key, kind in (
        ("adicionar_grupo", "Group"),
        ("remover_grupo", "Group"),
        ("adicionar_tecnico", "User"),
        ("remover_tecnico", "User"),
    ):
        resolved[key] = [_resolve_catalog_live(glpi, kind, x, entity_id) for x in changes.get(key, [])]
    return resolved


def _hash_json(value: Any) -> str:
    blob = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _normalize_text(text: str) -> str:
    # O mesmo texto percorre JSON no Dry Run e multipart/form-data na execução.
    # Browsers podem serializar quebras de linha de campos multipart como CRLF,
    # enquanto o JSON preserva LF. Canonicalizar evita falso "fechamento mudou".
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _text_hash(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def _canonical_evidence_map(mapping: dict[str, str] | None) -> dict[str, str]:
    if not mapping:
        return {}
    return {str(k).upper(): str(v) for k, v in mapping.items() if str(v)}


def _ticket_state_material(ticket: dict[str, Any]) -> dict[str, Any]:
    # Compara somente o estado do chamado que influencia o plano.
    # Relações são ordenadas por identidade semântica para não depender
    # da ordem em que a API do GLPI devolve os registros.
    return {
        "id": int(ticket["id"]),
        "title": str(ticket.get("title") or ""),
        "entity_id": int(ticket.get("entity_id") or 0),
        "category_id": int((ticket.get("category") or {}).get("id") or 0),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "requesters": sorted(
            (int(x.get("users_id") or 0), int(x.get("type") or 0))
            for x in ticket.get("requesters", [])
        ),
        "assigned_users": sorted(
            (int(x.get("users_id") or 0), int(x.get("type") or 0))
            for x in ticket.get("assigned_users", [])
        ),
        "assigned_groups": sorted(
            (int(x.get("groups_id") or 0), int(x.get("type") or 0))
            for x in ticket.get("assigned_groups", [])
        ),
    }


def _ticket_state_hash(ticket: dict[str, Any]) -> str:
    return _hash_json(_ticket_state_material(ticket))


PLAN_TTL_SECONDS = 30 * 60
_PLAN_CACHE: dict[str, dict[str, Any]] = {}
_PLAN_LOCK = threading.Lock()


def _purge_plans() -> None:
    cutoff = time.time() - PLAN_TTL_SECONDS
    with _PLAN_LOCK:
        stale = [pid for pid, rec in _PLAN_CACHE.items() if rec["created_at"] < cutoff]
        for pid in stale:
            _PLAN_CACHE.pop(pid, None)


def _store_plan(plan: dict[str, Any], text: str, evidence_map: dict[str, str]) -> str:
    _purge_plans()
    plan_id = secrets.token_urlsafe(24)
    record = {
        "created_at": time.time(),
        "ticket_id": int(plan["ticket"]["id"]),
        "text_hash": _text_hash(text),
        "evidence_hash": _hash_json(_canonical_evidence_map(evidence_map)),
        "ticket_state_hash": _ticket_state_hash(plan["ticket"]),
        "current_user_id": int(plan["current_user_id"]),
        # O plano resolvido no Dry Run é a fonte exata da execução.
        # Não re-resolvemos catálogos na hora de aplicar.
        "plan": plan,
    }
    with _PLAN_LOCK:
        _PLAN_CACHE[plan_id] = record
    return plan_id


def _load_plan(plan_id: str) -> dict[str, Any]:
    _purge_plans()
    with _PLAN_LOCK:
        record = _PLAN_CACHE.get(plan_id)
    if not record:
        raise ValueError(
            "Dry Run não encontrado ou expirado. Gere um novo Dry Run antes de aplicar."
        )
    return record


def _consume_plan(plan_id: str) -> None:
    with _PLAN_LOCK:
        if _PLAN_CACHE.pop(plan_id, None) is None:
            raise ValueError('Este plano já foi consumido por outro envio. Atualize o chamado.')

def _build_plan(ticket_id: int, text: str, evidence_map: dict[str, str] | None = None) -> dict[str, Any]:
    text = _normalize_text(text)
    resolve_bridge_ticket_id(ticket_id, text)
    parsed = parse_closure(text)

    with _client() as glpi:
        snap = _ticket_snapshot(glpi, ticket_id)
        current_user_id = glpi.current_user_id()
        entity_id = snap["entity_id"]

        # First interpret the AI closure against the real task history. This is
        # what allows a ticket that already has T01-T03 to continue with only
        # T04/T05, while also protecting against a repeated full submission.
        existing_tasks = _existing_task_candidates(glpi, ticket_id)
        missing_tasks, skipped_tasks = _partition_incoming_tasks(parsed["tasks"], existing_tasks)

        contact_receipt = (whatsapp_auto.optional_first_contact_receipt(glpi.base, current_user_id, ticket_id, refresh=False)
            if missing_tasks and (not existing_tasks or any(t.get('id') == 'T01' for t in missing_tasks))
            and not self_only_ticket(glpi, snap['raw'], current_user_id) else None)
        resolved_tasks = []
        modality_cache: dict[str, dict[str, Any]] = {}
        for task in missing_tasks:
            modality_key = str(task["modalidade"]).strip().casefold()
            modality = modality_cache.get(modality_key)
            if modality is None:
                modality = _resolve_catalog_live(glpi, "Group", task["modalidade"], entity_id)
                modality_cache[modality_key] = modality
            resolved_tasks.append({**task, "modality_group": modality})
        changes = _resolve_changes(glpi, parsed.get("changes"), entity_id)

    operations: list[dict[str, Any]] = []
    noop_changes: list[dict[str, Any]] = []
    if changes:
        if changes.get("titulo"):
            if changes["titulo"] != snap["title"]:
                operations.append({"op": "update_title", "from": snap["title"], "to": changes["titulo"]})
            else:
                noop_changes.append({"op": "title_already_set", "item": changes["titulo"]})

        if changes.get("categoria"):
            if changes["categoria"]["id"] != snap["category"]["id"]:
                operations.append({"op": "update_category", "from": snap["category"], "to": changes["categoria"]})
            else:
                noop_changes.append({"op": "category_already_set", "item": changes["categoria"]})

        if changes.get("requerente"):
            requester_ids = {int(x.get("users_id") or 0) for x in snap.get("requesters", [])}
            target = int(changes["requerente"]["id"])
            if requester_ids != {target}:
                operations.append({"op": "replace_requester", "current": snap["requesters"], "to": changes["requerente"], "sensitive": True})
            else:
                noop_changes.append({"op": "requester_already_set", "item": changes["requerente"]})

        assigned_group_ids = {int(x.get("groups_id") or 0) for x in snap.get("assigned_groups", [])}
        assigned_user_ids = {int(x.get("users_id") or 0) for x in snap.get("assigned_users", [])}

        for x in changes.get("adicionar_grupo", []):
            if int(x["id"]) in assigned_group_ids:
                noop_changes.append({"op": "group_already_assigned", "item": x})
            else:
                operations.append({"op": "add_group", "item": x})
        for x in changes.get("remover_grupo", []):
            if int(x["id"]) not in assigned_group_ids:
                noop_changes.append({"op": "group_already_absent", "item": x})
            else:
                operations.append({"op": "remove_group", "item": x})
        for x in changes.get("adicionar_tecnico", []):
            if int(x["id"]) in assigned_user_ids:
                noop_changes.append({"op": "technician_already_assigned", "item": x})
            else:
                operations.append({"op": "add_technician", "item": x})
        for x in changes.get("remover_tecnico", []):
            if int(x["id"]) not in assigned_user_ids:
                noop_changes.append({"op": "technician_already_absent", "item": x})
            else:
                operations.append({"op": "remove_technician", "item": x})

    for skipped in skipped_tasks:
        task = skipped["task"]
        operations.append({
            "op": "skip_existing_task",
            "task_id": task["id"],
            "existing_task_id": skipped.get("existing_task_id"),
            "existing_logical_id": skipped.get("existing_logical_id"),
            "reason": skipped.get("reason"),
            "score": skipped.get("score"),
        })

    for item in noop_changes:
        operations.append({"op": "skip_existing_change", **item})

    if contact_receipt:
        operations.append({'op': 'contact_receipt', 'receipt': contact_receipt})
    for t in resolved_tasks:
        operations.append({
            "op": "create_task",
            "task_id": t["id"],
            "modality": t["modalidade"],
            "level": t.get("nivel"),
            "modality_group": t["modality_group"],
            "actiontime": t["actiontime"],
            "state": t["state"],
            "evidences": t["evidences"],
        })

    required_evidence_ids = sorted({e for task in resolved_tasks for e in task.get("evidences", [])})
    actionable_ops = [o for o in operations if o.get("op") not in {"skip_existing_task", "skip_existing_change"}]

    result = {
        "ticket": snap,
        "current_user_id": current_user_id,
        "parsed": parsed,
        "resolved_tasks": resolved_tasks,
        "contact_receipt": contact_receipt,
        "resolved_changes": changes,
        "operations": operations,
        "incoming_task_count": len(parsed["tasks"]),
        "task_count": len(resolved_tasks),
        "skipped_task_count": len(skipped_tasks),
        "skipped_tasks": skipped_tasks,
        "existing_task_count": len(existing_tasks),
        "required_evidence_ids": required_evidence_ids,
        "evidence_count": len(required_evidence_ids),
        "has_actionable_operations": bool(actionable_ops),
    }
    return result


@app.post("/api/plan")
def plan(payload: PlanPayload, request: Request):
    _require_local_ui(request)
    try:
        mapping = _canonical_evidence_map(payload.evidence_map)
        result = _build_plan(payload.ticket_id, payload.text, mapping)
        result["plan_id"] = _store_plan(result, payload.text, mapping)
        result["plan_ttl_seconds"] = PLAN_TTL_SECONDS
        return result
    except Exception as exc:
        _error(exc)


def _markdownish_to_html(text: str) -> str:
    # Mantém o fechamento legível e seguro, sem depender de uma lib Markdown.
    escaped = html.escape(text)
    escaped = re_sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    paragraphs = []
    for block in re_split_blank(escaped):
        paragraphs.append(f"<p>{block.replace(chr(10), '<br>')}</p>")
    return "".join(paragraphs)


def re_sub(pattern: str, repl: str, value: str) -> str:
    import re
    return re.sub(pattern, repl, value, flags=re.S)


def re_split_blank(value: str) -> list[str]:
    import re
    return [x for x in re.split(r"\n\s*\n", value.strip()) if x]


def _apply_ticket_changes(glpi: GlpiClient, ticket_id: int, snap: dict[str, Any], changes: dict[str, Any] | None, log: list[dict[str, Any]]) -> None:
    if not changes:
        return
    if changes.get("titulo") and str(changes["titulo"]) != str(snap.get("title") or ""):
        glpi.update_ticket_fields(ticket_id, {"name": str(changes["titulo"])})
        log.append({"ok": True, "op": "update_title", "title": str(changes["titulo"])})
    if changes.get("categoria") and int(changes["categoria"]["id"]) != int(snap["category"]["id"]):
        glpi.update_ticket_category(ticket_id, int(changes["categoria"]["id"]))
        log.append({"ok": True, "op": "update_category", "id": int(changes["categoria"]["id"])})

    if changes.get("requerente"):
        target = int(changes["requerente"]["id"])
        current = glpi.ticket_users(ticket_id)
        for rel in current:
            if int(rel.get("type") or 0) == 1 and int(rel.get("users_id") or 0) != target:
                glpi.delete_ticket_user_relation(int(rel["id"]))
        if not any(int(rel.get("type") or 0) == 1 and int(rel.get("users_id") or 0) == target for rel in current):
            rid = glpi.add_ticket_user(ticket_id, target, 1)
            log.append({"ok": True, "op": "replace_requester", "relation_id": rid, "user_id": target})

    groups = glpi.ticket_groups(ticket_id)
    users = glpi.ticket_users(ticket_id)

    for item in changes.get("adicionar_grupo", []):
        gid = int(item["id"])
        if not any(int(r.get("type") or 0) == 2 and int(r.get("groups_id") or 0) == gid for r in groups):
            rid = glpi.add_ticket_group(ticket_id, gid, 2)
            groups = glpi.ticket_groups(ticket_id)
            if not any(int(r.get("type") or 0) == 2 and int(r.get("groups_id") or 0) == gid for r in groups):
                raise GlpiError(f"Grupo {item.get('full_name') or gid} não apareceu como atribuído após a inclusão.")
            log.append({"ok": True, "op": "add_group", "relation_id": rid, "group_id": gid, "verified": True})

    for item in changes.get("remover_grupo", []):
        gid = int(item["id"])
        for r in list(groups):
            if int(r.get("type") or 0) == 2 and int(r.get("groups_id") or 0) == gid:
                glpi.delete_ticket_group_relation(int(r["id"]))
                log.append({"ok": True, "op": "remove_group", "relation_id": int(r["id"]), "group_id": gid})
        groups = glpi.ticket_groups(ticket_id)
        if any(int(r.get("type") or 0) == 2 and int(r.get("groups_id") or 0) == gid for r in groups):
            raise GlpiError(f"Grupo {item.get('full_name') or gid} permaneceu atribuído após a remoção.")

    for item in changes.get("adicionar_tecnico", []):
        uid = int(item["id"])
        if not any(int(r.get("type") or 0) == 2 and int(r.get("users_id") or 0) == uid for r in users):
            rid = glpi.add_ticket_user(ticket_id, uid, 2)
            users = glpi.ticket_users(ticket_id)
            if not any(int(r.get("type") or 0) == 2 and int(r.get("users_id") or 0) == uid for r in users):
                raise GlpiError(
                    f"O GLPI aceitou a solicitação, mas o técnico {item.get('full_name') or uid} "
                    "não apareceu como atribuído na releitura do chamado."
                )
            log.append({"ok": True, "op": "add_technician", "relation_id": rid, "user_id": uid, "verified": True})
        else:
            log.append({"ok": True, "op": "add_technician", "user_id": uid, "noop": True, "verified": True})

    for item in changes.get("remover_tecnico", []):
        uid = int(item["id"])
        for r in list(users):
            if int(r.get("type") or 0) == 2 and int(r.get("users_id") or 0) == uid:
                glpi.delete_ticket_user_relation(int(r["id"]))
                log.append({"ok": True, "op": "remove_technician", "relation_id": int(r["id"]), "user_id": uid})
        users = glpi.ticket_users(ticket_id)
        if any(int(r.get("type") or 0) == 2 and int(r.get("users_id") or 0) == uid for r in users):
            raise GlpiError(f"Técnico {item.get('full_name') or uid} permaneceu atribuído após a remoção.")


_EXECUTE_LOCK = threading.Lock()

@app.post("/api/execute")
def execute(
    request: Request,
    ticket_id: int = Form(...),
    text: str = Form(...),
    evidence_map: str = Form("{}"),
    plan_id: str = Form(...),
    file_ids: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
):
    _require_local_ui(request)
    if not _EXECUTE_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Outro envio está em andamento. Aguarde a confirmação.")
    try:
        try:
            raw_mapping = json.loads(evidence_map or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Mapeamento de evidências inválido.") from exc

        if not isinstance(raw_mapping, dict):
            raise ValueError("Mapeamento de evidências inválido.")

        mapping = _canonical_evidence_map(raw_mapping)
        record = _load_plan(plan_id)
        plan = record["plan"]

        # Verificações determinísticas do que veio do navegador.
        if int(ticket_id) != int(record["ticket_id"]):
            raise ValueError(
                "O número do chamado mudou desde o Dry Run. Gere um novo Dry Run."
            )
        if _text_hash(text) != record["text_hash"]:
            raise ValueError(
                "O fechamento mudou desde o Dry Run. Gere um novo Dry Run."
            )
        if _hash_json(mapping) != record["evidence_hash"]:
            raise ValueError(
                "O mapeamento das evidências mudou desde o Dry Run. Gere um novo Dry Run."
            )

        required = set(plan.get("required_evidence_ids", plan["parsed"]["evidence_ids"]))
        names = [Path(f.filename or "arquivo.bin").name for f in files]

        # 2.6.0 keeps stable client-side evidence mapping: evidence slots to stable client-side file IDs instead of
        # filenames. This makes E01 -> image B reliable even after the user
        # manually changes a select, and also permits two different uploads
        # that happen to share the same basename. The original filename is
        # preserved when the document is uploaded to GLPI.
        if not isinstance(file_ids, list):
            file_ids = []
        normalized_file_ids = [str(x or "").strip() for x in file_ids]
        if normalized_file_ids and len(normalized_file_ids) != len(files):
            raise ValueError(
                "A lista interna de arquivos ficou inconsistente. Atualize a página e gere um novo Dry Run."
            )
        if not normalized_file_ids:
            # Backward-compatible fallback for a stale frontend tab from 2.4.0.
            normalized_file_ids = names.copy()
        if any(not x for x in normalized_file_ids) or len(normalized_file_ids) != len(set(normalized_file_ids)):
            raise ValueError("Há IDs internos de arquivo vazios ou duplicados. Gere um novo Dry Run.")

        provided_ids = set(normalized_file_ids)
        missing_slots = [e for e in required if not mapping.get(e)]
        if missing_slots:
            raise ValueError(
                f"Evidências sem arquivo associado: {', '.join(sorted(missing_slots))}"
            )
        missing_files = [fid for fid in mapping.values() if fid not in provided_ids]
        if missing_files:
            missing_labels = [
                evid for evid, fid in mapping.items() if fid in set(missing_files)
            ]
            raise ValueError(
                "Arquivos mapeados não foram enviados para: " + ", ".join(sorted(missing_labels))
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="glpi-assistant-"))
        file_paths: dict[str, Path] = {}
        file_names: dict[str, str] = {}
        try:
            for file_id, up in zip(normalized_file_ids, files):
                safe_name = Path(up.filename or "arquivo.bin").name
                slot_dir = temp_dir / re.sub(r"[^A-Za-z0-9_.-]+", "_", file_id)[:120]
                slot_dir.mkdir(parents=True, exist_ok=True)
                path = slot_dir / safe_name
                with path.open("wb") as out:
                    shutil.copyfileobj(up.file, out)
                file_paths[file_id] = path
                file_names[file_id] = safe_name

            log: list[dict[str, Any]] = []
            created_tasks = []

            with _client() as glpi:
                # O estado vivo do GLPI é comparado separadamente do plano
                # resolvido. Assim o Dry Run continua seguro sem sofrer
                # falsos positivos por re-resolução de catálogo/ordenação.
                live_snap = _ticket_snapshot(glpi, ticket_id)
                live_user_id = glpi.current_user_id()

                if live_user_id != int(record["current_user_id"]):
                    raise ValueError(
                        "O usuário autenticado no GLPI mudou desde o Dry Run. "
                        "Gere um novo Dry Run."
                    )

                if _ticket_state_hash(live_snap) != record["ticket_state_hash"]:
                    raise ValueError(
                        "O estado do chamado mudou no GLPI desde o Dry Run "
                        "(categoria, status, prioridade, requerente ou atribuídos). "
                        "Recarregue o chamado e gere um novo Dry Run."
                    )

                # Barreira idempotente imediatamente antes da primeira escrita.
                # Se outro envio inseriu uma das mesmas tarefas após o Dry Run,
                # ela é interpretada como já concluída e não é duplicada.
                live_existing_tasks = _existing_task_candidates(glpi, ticket_id)
                live_missing_tasks, late_skipped_tasks = _partition_incoming_tasks(
                    plan["resolved_tasks"], live_existing_tasks
                )

                # A partir daqui podem existir efeitos no GLPI. O plano é
                # consumido antes da primeira escrita para impedir reenvio
                # acidental caso uma operação posterior falhe parcialmente.
                _consume_plan(plan_id)

                _apply_ticket_changes(
                    glpi, ticket_id, live_snap, plan["resolved_changes"], log
                )

                execution_errors: list[dict[str, Any]] = []
                planned_task_count = len(plan["resolved_tasks"])
                expected_task_count = len(live_missing_tasks)

                for task_index, task in enumerate(live_missing_tasks, start=1):
                    task_result: dict[str, Any] = {
                        "logical_id": task["id"],
                        "ordinal": task_index,
                        "task_id": None,
                        "documents": [],
                        "errors": [],
                        "verified": False,
                    }
                    created_tasks.append(task_result)

                    try:
                        marker_comment = (
                            f"<!-- glpi-assistant:{VERSION}:{html.escape(str(task['id']), quote=True)} -->"
                        )
                        placeholder_html = marker_comment + _markdownish_to_html(task["content"])
                        if (task.get('id') == 'T01' or (task_index == 1 and not live_existing_tasks)):
                            placeholder_html += whatsapp_auto.receipt_html(plan.get("contact_receipt"))
                        task_id = glpi.create_task(
                            ticket_id=ticket_id,
                            content=placeholder_html,
                            actiontime=task["actiontime"],
                            state=task["state"],
                            tech_user_id=live_user_id,
                            group_id=task["modality_group"]["id"],
                        )
                        task_result["task_id"] = task_id
                        log.append({
                            "ok": True,
                            "op": "create_task",
                            "task": task["id"],
                            "ordinal": task_index,
                            "task_id": task_id,
                        })
                    except Exception as task_exc:
                        err = {
                            "task": task["id"],
                            "ordinal": task_index,
                            "stage": "create_task",
                            "message": str(task_exc),
                        }
                        task_result["errors"].append(err)
                        execution_errors.append(err)
                        log.append({"ok": False, "op": "create_task", **err})
                        # Uma tarefa que nem chegou a ser criada não impede as seguintes.
                        continue

                    final_html = placeholder_html
                    docs = task_result["documents"]
                    for evid in task["evidences"]:
                        try:
                            file_id = mapping[evid]
                            path = file_paths[file_id]
                            filename = file_names[file_id]
                            upload = glpi.upload_document(path, live_snap["entity_id"])
                            document_id = int(upload["id"])
                            link_id = glpi.link_document_to_task(document_id, task_id)
                            doc = glpi.document(document_id)
                            tag = str(doc.get("tag") or doc.get("name") or filename)
                            img_url = (
                                f"/front/document.send.php?docid={document_id}"
                                f"&itemtype=Ticket&items_id={ticket_id}"
                            )
                            inline = (
                                f'<a href="{img_url}" target="_blank">'
                                f'<img alt="{html.escape(tag, quote=True)}" src="{img_url}" />'
                                "</a>"
                            )
                            # Use exatamente a mesma sintaxe flexível aceita
                            # pelo parser e pela Bridge.
                            final_html = _replace_evidence_marker(final_html, evid, inline)
                            doc_result = {
                                "evidence": evid,
                                "file": filename,
                                "document_id": document_id,
                                "link_id": link_id,
                            }
                            docs.append(doc_result)
                            log.append({
                                "ok": True,
                                "op": "upload_evidence",
                                "task_id": task_id,
                                **doc_result,
                            })
                        except Exception as evid_exc:
                            err = {
                                "task": task["id"],
                                "ordinal": task_index,
                                "task_id": task_id,
                                "stage": "upload_evidence",
                                "evidence": evid,
                                "message": str(evid_exc),
                            }
                            task_result["errors"].append(err)
                            execution_errors.append(err)
                            log.append({"ok": False, "op": "upload_evidence", **err})

                    try:
                        glpi.update_task_content(task_id, final_html)
                        log.append({
                            "ok": True,
                            "op": "update_task_inline",
                            "task": task["id"],
                            "task_id": task_id,
                        })
                    except Exception as update_exc:
                        err = {
                            "task": task["id"],
                            "ordinal": task_index,
                            "task_id": task_id,
                            "stage": "update_task_inline",
                            "message": str(update_exc),
                        }
                        task_result["errors"].append(err)
                        execution_errors.append(err)
                        log.append({"ok": False, "op": "update_task_inline", **err})

                # Verificação pós-escrita: confirma pela própria API que cada ID
                # devolvido no POST realmente está relacionado ao chamado.
                try:
                    observed_ids = {
                        int(x.get("id") or 0) for x in glpi.ticket_tasks(ticket_id)
                    }
                except Exception as verify_exc:
                    observed_ids = set()
                    err = {
                        "stage": "verify_tasks",
                        "message": str(verify_exc),
                    }
                    execution_errors.append(err)
                    log.append({"ok": False, "op": "verify_tasks", **err})

                for task_result in created_tasks:
                    tid = int(task_result.get("task_id") or 0)
                    if not tid:
                        continue
                    task_result["verified"] = tid in observed_ids
                    if not task_result["verified"]:
                        err = {
                            "task": task_result["logical_id"],
                            "ordinal": task_result["ordinal"],
                            "task_id": tid,
                            "stage": "verify_task",
                            "message": "A API retornou um ID de tarefa, mas ele não apareceu na releitura do chamado.",
                        }
                        task_result["errors"].append(err)
                        execution_errors.append(err)
                        log.append({"ok": False, "op": "verify_task", **err})

                verified_count = sum(1 for x in created_tasks if x.get("verified"))
                created_count = sum(1 for x in created_tasks if x.get("task_id"))

            if not execution_errors and verified_count == expected_task_count:
                _remember_applied(ticket_id, text)
            return {
                "ok": not execution_errors and verified_count == expected_task_count,
                "partial": bool(execution_errors) or verified_count != expected_task_count,
                "ticket_id": ticket_id,
                "planned_task_count": planned_task_count,
                "expected_task_count": expected_task_count,
                "created_task_count": created_count,
                "verified_task_count": verified_count,
                "skipped_existing_at_apply_count": len(late_skipped_tasks),
                "skipped_existing_at_apply": late_skipped_tasks,
                "tasks": created_tasks,
                "errors": execution_errors,
                "log": log,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as exc:
        _error(exc)

    finally:
        _EXECUTE_LOCK.release()

import proactive_api
proactive_api.register(app, _client, _resolve_catalog_live, _require_local_ui, _require_bridge_auth, lambda: {**workbench.DEFAULTS, **(get_meta("workbench_settings", {}) or {})})
