from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
import re
from difflib import SequenceMatcher
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(os.environ.get("GLPI_ASSISTANT_DATA", "/data"))
DB_PATH = DATA_DIR / "app.db"
CONFIG_PATH = DATA_DIR / "config.json"


def _norm(value: str | None) -> str:
    value = (value or "").strip().casefold()
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(c)
    )
    return " ".join(value.split())


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except PermissionError:
        pass
    with connect() as con:
        # WAL keeps the monitor thread and the local UI from needlessly
        # blocking each other on short metadata operations.
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog (
                kind TEXT NOT NULL,
                id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                norm_name TEXT NOT NULL DEFAULT '',
                norm_full_name TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                entity_id INTEGER,
                raw_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(kind, id)
            );
            CREATE INDEX IF NOT EXISTS idx_catalog_kind_name
                ON catalog(kind, norm_name);
            CREATE INDEX IF NOT EXISTS idx_catalog_kind_full
                ON catalog(kind, norm_full_name);

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bridge_handoff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'chatgpt',
                ticket_id INTEGER,
                closure TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                task_count INTEGER NOT NULL DEFAULT 0,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_bridge_handoff_status_created
                ON bridge_handoff(status, created_at DESC);
            """
        )
    try:
        DB_PATH.chmod(0o600)
    except PermissionError:
        pass


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA synchronous=FULL")
    con.execute("PRAGMA busy_timeout=10000")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def load_config() -> dict[str, Any] | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, name = tempfile.mkstemp(prefix='.config-', dir=DATA_DIR)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(CONFIG_PATH)
        directory = os.open(DATA_DIR, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)



def set_meta(key: str, value: Any) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def get_meta(key: str, default: Any = None) -> Any:
    with connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default

def delete_meta(key: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM meta WHERE key=?", (key,))


def list_meta_prefix(prefix: str) -> dict[str, Any]:
    with connect() as con:
        rows = con.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ESCAPE '\\'",
            (prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%',),
        ).fetchall()
    result: dict[str, Any] = {}
    for row in rows:
        try:
            result[str(row['key'])] = json.loads(row['value'])
        except Exception:
            result[str(row['key'])] = None
    return result


def _user_names(item: dict[str, Any]) -> tuple[str, str, list[str]]:
    first = str(item.get("firstname") or "").strip()
    last = str(item.get("realname") or "").strip()
    login = str(item.get("name") or "").strip()
    email = str(item.get("email") or "").strip()
    full = " ".join(x for x in [first, last] if x).strip()
    display = full or login or email or f"User {item.get('id')}"
    aliases = [x for x in [full, login, email] if x]
    return display, display, aliases


def prepare_catalog_item(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    if kind == "User":
        name, full_name, aliases = _user_names(item)
    else:
        name = str(item.get("name") or "").strip()
        full_name = str(item.get("completename") or item.get("complete_name") or name).strip()
        aliases = [name, full_name]

    entity = item.get("entities_id")
    try:
        entity_id = int(entity) if entity not in (None, "") else None
    except (TypeError, ValueError):
        entity_id = None

    return {
        "kind": kind,
        "id": int(item["id"]),
        "name": name,
        "full_name": full_name,
        "norm_name": _norm(name),
        "norm_full_name": _norm(full_name),
        "aliases_json": json.dumps(sorted(set(a for a in aliases if a)), ensure_ascii=False),
        "entity_id": entity_id,
        "raw_json": json.dumps(item, ensure_ascii=False),
    }


def replace_catalog(kind: str, items: Iterable[dict[str, Any]]) -> int:
    prepared = [prepare_catalog_item(kind, i) for i in items if "id" in i]
    with connect() as con:
        con.execute("DELETE FROM catalog WHERE kind=?", (kind,))
        con.executemany(
            """
            INSERT INTO catalog(
                kind,id,name,full_name,norm_name,norm_full_name,
                aliases_json,entity_id,raw_json
            ) VALUES(
                :kind,:id,:name,:full_name,:norm_name,:norm_full_name,
                :aliases_json,:entity_id,:raw_json
            )
            """,
            prepared,
        )
    return len(prepared)


def upsert_catalog_item(kind: str, item: dict[str, Any]) -> None:
    row = prepare_catalog_item(kind, item)
    with connect() as con:
        con.execute(
            """
            INSERT INTO catalog(
                kind,id,name,full_name,norm_name,norm_full_name,
                aliases_json,entity_id,raw_json
            ) VALUES(
                :kind,:id,:name,:full_name,:norm_name,:norm_full_name,
                :aliases_json,:entity_id,:raw_json
            )
            ON CONFLICT(kind,id) DO UPDATE SET
                name=excluded.name,
                full_name=excluded.full_name,
                norm_name=excluded.norm_name,
                norm_full_name=excluded.norm_full_name,
                aliases_json=excluded.aliases_json,
                entity_id=excluded.entity_id,
                raw_json=excluded.raw_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            row,
        )


def clear_catalog(kind: str | None = None) -> None:
    with connect() as con:
        if kind is None:
            con.execute("DELETE FROM catalog")
        else:
            con.execute("DELETE FROM catalog WHERE kind=?", (kind,))


def catalog_stats() -> dict[str, int]:
    with connect() as con:
        rows = con.execute(
            "SELECT kind, COUNT(*) AS n FROM catalog GROUP BY kind ORDER BY kind"
        ).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def get_catalog_item(kind: str, item_id: int) -> dict[str, Any] | None:
    """Return one cached catalog item by exact GLPI id without a network call."""
    with connect() as con:
        row = con.execute(
            "SELECT id,name,full_name,entity_id,raw_json FROM catalog WHERE kind=? AND id=?",
            (kind, int(item_id)),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "full_name": row["full_name"],
        "entity_id": row["entity_id"],
        "raw": json.loads(row["raw_json"]),
    }


def list_catalog(kind: str, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    q = _norm(query)
    with connect() as con:
        if q:
            like = f"%{q}%"
            rows = con.execute(
                "SELECT id,name,full_name,entity_id,raw_json,aliases_json FROM catalog "
                "WHERE kind=? AND (norm_name LIKE ? OR norm_full_name LIKE ? OR aliases_json LIKE ?) "
                "ORDER BY CASE WHEN norm_full_name=? THEN 0 WHEN norm_name=? THEN 1 ELSE 2 END, full_name LIMIT ?",
                (kind, like, like, like, q, q, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id,name,full_name,entity_id,raw_json,aliases_json FROM catalog "
                "WHERE kind=? ORDER BY full_name LIMIT ?", (kind, limit),
            ).fetchall()

        # The autocomplete should understand the same natural person-name form
        # as resolve_catalog: "Jhonny Rocha" must still suggest
        # "Jhonny da Silva Rocha". Only use token subset matching for two or
        # more tokens to avoid flooding suggestions for a common first name.
        if kind == "User" and q and not rows and len(_tokens(q)) >= 2:
            q_tokens = _tokens(q)
            candidates = con.execute(
                "SELECT id,name,full_name,entity_id,raw_json,aliases_json "
                "FROM catalog WHERE kind='User' ORDER BY full_name LIMIT 2000"
            ).fetchall()
            matched = []
            for row in candidates:
                aliases = json.loads(row["aliases_json"] or "[]")
                values = [row["name"], row["full_name"], *aliases]
                if any(q_tokens.issubset(_tokens(str(v))) for v in values if v):
                    matched.append(row)
                    if len(matched) >= limit:
                        break
            rows = matched
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "full_name": r["full_name"],
            "entity_id": r["entity_id"],
        }
        for r in rows
    ]


_STOPWORDS = {
    "a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em",
    "no", "na", "nos", "nas", "para", "por", "com", "um", "uma",
}


def _stem_token(token: str) -> str:
    """Pequena normalização lexical para busca tolerante, sem NLP externo."""
    token = _norm(token)
    if token.endswith("coes") and len(token) > 5:
        # configuracoes -> configuracao / alteracoes -> alteracao
        token = token[:-4] + "cao"
    elif token.endswith("oes") and len(token) > 5:
        token = token[:-3] + "ao"
    elif token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token


def _tokens(value: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", _norm(value))
    return {
        _stem_token(t)
        for t in raw
        if t and t not in _STOPWORDS and len(t) > 1
    }


def _fuzzy_score(target: str, candidate: str) -> float:
    """
    Similaridade conservadora para categorias.

    Prioriza a cobertura das palavras informadas pelo usuário (ex.:
    "regra de firewall" deve favorecer uma categoria que contenha tanto
    "regra" quanto "firewall" mesmo que a ordem/caminho seja diferente).
    """
    q = _norm(target)
    c = _norm(candidate)
    if not q or not c:
        return 0.0

    qt = _tokens(q)
    ct = _tokens(c)
    if not qt or not ct:
        return SequenceMatcher(None, q, c).ratio()

    common = qt & ct
    coverage = len(common) / len(qt)
    jaccard = len(common) / len(qt | ct)
    sequence = SequenceMatcher(None, q, c).ratio()

    # Cobrir todos os termos pedidos pesa mais do que a semelhança literal.
    score = (0.56 * coverage) + (0.18 * jaccard) + (0.26 * sequence)

    # Pequeno bônus quando todos os termos da consulta estão presentes.
    if coverage == 1.0:
        score += 0.06

    return min(score, 1.0)


def _catalog_result(row: sqlite3.Row, *, query: str, method: str, score: float) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "full_name": row["full_name"],
        "entity_id": row["entity_id"],
        "raw": json.loads(row["raw_json"]),
        "match": {
            "query": query,
            "method": method,
            "score": round(float(score), 4),
        },
    }


def _scope_candidates(rows: list[sqlite3.Row], entity_id: int | None) -> list[sqlite3.Row]:
    if entity_id is None or len(rows) <= 1:
        return rows
    scoped = [r for r in rows if r["entity_id"] in (entity_id, 0, None)]
    same = [r for r in scoped if r["entity_id"] == entity_id]
    if len(same) == 1:
        return same
    if len(scoped) == 1:
        return scoped
    return rows


def _fuzzy_category_candidates(
    rows: list[sqlite3.Row], query: str, entity_id: int | None
) -> list[tuple[float, sqlite3.Row]]:
    ranked: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        aliases = json.loads(row["aliases_json"] or "[]")
        values = [row["name"], row["full_name"], *aliases]
        score = max((_fuzzy_score(query, str(v)) for v in values if v), default=0.0)
        if entity_id is not None:
            if row["entity_id"] == entity_id:
                score = min(1.0, score + 0.025)
            elif row["entity_id"] in (0, None):
                score = min(1.0, score + 0.01)
        ranked.append((score, row))
    ranked.sort(key=lambda x: (-x[0], str(x[1]["full_name"]), int(x[1]["id"])))
    return ranked


def create_bridge_handoff(
    *,
    source: str,
    ticket_id: int | None,
    closure: str,
    content_hash: str,
    task_count: int,
    evidence_count: int,
) -> tuple[dict[str, Any], bool]:
    """Persist a browser-bridge handoff, deduplicated by content hash.

    Returns (row, created). Re-sending the exact same closure for the same
    ticket returns the original row instead of creating timeline noise.
    """
    with connect() as con:
        row = con.execute(
            "SELECT * FROM bridge_handoff WHERE content_hash=?",
            (content_hash,),
        ).fetchone()
        if row:
            return dict(row), False
        cur = con.execute(
            """
            INSERT INTO bridge_handoff(
                source,ticket_id,closure,content_hash,status,task_count,evidence_count
            ) VALUES(?,?,?,?,'pending',?,?)
            """,
            (source, ticket_id, closure, content_hash, task_count, evidence_count),
        )
        row = con.execute(
            "SELECT * FROM bridge_handoff WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row), True


def list_bridge_handoffs(*, limit: int = 30, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with connect() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM bridge_handoff WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM bridge_handoff WHERE status != 'completed' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_bridge_handoff(handoff_id: int) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM bridge_handoff WHERE id=?",
            (int(handoff_id),),
        ).fetchone()
    return dict(row) if row else None


def set_bridge_handoff_status(handoff_id: int, status: str) -> dict[str, Any] | None:
    allowed = {"pending", "imported", "dismissed"}
    if status not in allowed:
        raise ValueError(f"Status de handoff inválido: {status}")
    with connect() as con:
        con.execute(
            "UPDATE bridge_handoff SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status != 'completed'",
            (status, int(handoff_id)),
        )
        row = con.execute(
            "SELECT * FROM bridge_handoff WHERE id=?",
            (int(handoff_id),),
        ).fetchone()
    return dict(row) if row else None


def delete_bridge_handoff(handoff_id: int) -> bool:
    with connect() as con:
        cur = con.execute("UPDATE bridge_handoff SET status='dismissed' WHERE id=? AND status != 'completed'", (int(handoff_id),))
        return bool(cur.rowcount)


def resolve_catalog(kind: str, query: str, entity_id: int | None = None) -> dict[str, Any]:
    target = _norm(query)
    if not target:
        raise ValueError(f"Valor vazio para {kind}")

    with connect() as con:
        rows = con.execute(
            "SELECT * FROM catalog WHERE kind=?",
            (kind,),
        ).fetchall()

    exact: list[sqlite3.Row] = []
    contains: list[sqlite3.Row] = []
    for r in rows:
        aliases = json.loads(r["aliases_json"] or "[]")
        norms = {_norm(r["name"]), _norm(r["full_name"]), *(_norm(a) for a in aliases)}
        norms.discard("")
        if target in norms:
            exact.append(r)
        elif any(target in n for n in norms):
            contains.append(r)

    candidates = _scope_candidates(exact or contains, entity_id)
    if candidates:
        if len(candidates) > 1:
            names = ", ".join(f"{r['full_name']} (ID {r['id']})" for r in candidates[:8])
            raise LookupError(f"{kind} ambíguo para '{query}': {names}")
        method = "exact" if exact else "contains"
        return _catalog_result(candidates[0], query=query, method=method, score=1.0 if exact else 0.97)

    # Pessoas podem chegar pelo prompt usando nome natural (por exemplo
    # "Jhonny Rocha") enquanto o GLPI exibe um nome completo com nomes do meio.
    # Para User aceitamos SOMENTE um subconjunto de tokens inequívoco e com pelo
    # menos dois tokens. Isso é mais tolerante que substring literal, mas não
    # permite escolher silenciosamente entre homônimos.
    if kind == "User" and rows:
        q_tokens = _tokens(target)
        if len(q_tokens) >= 2:
            token_matches: list[sqlite3.Row] = []
            for row in rows:
                aliases = json.loads(row["aliases_json"] or "[]")
                values = [row["name"], row["full_name"], *aliases]
                if any(q_tokens.issubset(_tokens(str(v))) for v in values if v):
                    token_matches.append(row)
            token_matches = _scope_candidates(token_matches, entity_id)
            if len(token_matches) == 1:
                return _catalog_result(
                    token_matches[0], query=query, method="token_subset", score=0.95
                )
            if len(token_matches) > 1:
                names = ", ".join(
                    f"{r['full_name']} (ID {r['id']})" for r in token_matches[:8]
                )
                raise LookupError(f"User ambíguo para '{query}': {names}")

    # Busca aproximada ampla continua habilitada SOMENTE para categorias.
    # Grupos e usuários não recebem fuzzy livre: para pessoas, o bloco acima
    # permite apenas correspondência de tokens inequívoca.
    if kind == "ITILCategory" and rows:
        ranked = _fuzzy_category_candidates(rows, query, entity_id)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        top_score = top[0]
        margin = top_score - (second[0] if second else 0.0)

        # Exige confiança razoável e distância do segundo colocado. Isso
        # permite "regra de firewall" -> "Firewall > ... Regras ...", mas
        # bloqueia escolhas silenciosas quando duas categorias são parecidas.
        if top_score >= 0.72 and (second is None or margin >= 0.08):
            return _catalog_result(top[1], query=query, method="fuzzy", score=top_score)

        suggestions = [
            f"{r['full_name']} (ID {r['id']}, {score * 100:.0f}%)"
            for score, r in ranked[:5]
            if score >= 0.30
        ]
        suffix = f" Sugestões: {'; '.join(suggestions)}" if suggestions else ""
        if top_score >= 0.62 and second is not None and margin < 0.08:
            raise LookupError(
                f"{kind} aproximado ambíguo para '{query}'.{suffix}"
            )
        raise LookupError(
            f"{kind} não encontrado com confiança suficiente para '{query}'.{suffix}"
        )

    raise LookupError(f"{kind} não encontrado no catálogo: {query}")


ensure_storage()
