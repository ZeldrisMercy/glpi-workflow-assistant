from __future__ import annotations

import copy
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from urllib.parse import urlsplit


class GlpiError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _api_error(response: requests.Response) -> GlpiError:
    try:
        payload = response.json()
    except Exception:
        payload = 'Resposta não JSON; corpo omitido.'
    return GlpiError(f"GLPI HTTP {response.status_code}. Confira permissões, URL e disponibilidade do serviço.", status_code=response.status_code)


def _clean_token(value: str | None, prefix: str) -> str:
    """Accept a pasted token with harmless whitespace/prefixes, never log it."""
    token = (value or "").strip()
    lowered = token.casefold()
    wanted = f"{prefix.casefold()} "
    if lowered.startswith(wanted):
        token = token[len(wanted):].strip()
    return token


def _rows_from_envelope(value: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        rows = value.get(key)
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _flatten_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """GLPI versions/plugins may nest child entities; flatten defensively."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(item: dict[str, Any]) -> None:
        try:
            eid = int(item.get("id"))
        except (TypeError, ValueError):
            eid = 0
        if eid and eid not in seen:
            seen.add(eid)
            out.append(item)
        for child_key in ("entities", "children", "sons"):
            children = item.get(child_key)
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        walk(child)

    for row in rows:
        walk(row)
    return out


@dataclass
class GlpiConfig:
    url: str
    user_token: str
    app_token: str = ""
    verify_tls: bool = True

    def normalized_url(self) -> str:
        url = self.url.strip().rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise GlpiError('Use a URL HTTPS do GLPI, sem credenciais ou parâmetros na URL.')
        if not self.verify_tls:
            raise GlpiError('Validação TLS obrigatória. Configure a CA interna para certificados corporativos.')
        if not url.endswith("apirest.php"):
            url += "/apirest.php"
        return url

    def normalized_user_token(self) -> str:
        return _clean_token(self.user_token, "user_token")

    def normalized_app_token(self) -> str:
        return _clean_token(self.app_token, "app_token")


class GlpiClient:
    def __init__(self, config: GlpiConfig, timeout: int = 60):
        self.config = config
        self.base = config.normalized_url()
        self.timeout = timeout
        self.tls_verify = str(Path("/etc/ssl/certs/ca-certificates.crt")) if Path("/etc/ssl/certs/ca-certificates.crt").exists() else True
        self.session_token: str | None = None
        self.http = requests.Session()
        self.http.trust_env = False
        self._search_options = {}
        self._user_id = None
        self._entity_context = None
        self.request_count = 0

    def __enter__(self):
        # IMPORTANT: authentication must not depend on profile/entity switching.
        # A restricted technician can successfully initSession but be forbidden
        # from activating "all" entities. Older builds did that here and turned
        # a valid token into a false login failure.
        self.init_session()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.kill_session()
        except Exception:
            pass

    def _app_headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        app_token = self.config.normalized_app_token()
        if app_token:
            h["App-Token"] = app_token
        return h

    def _headers(self) -> dict[str, str]:
        if not self.session_token:
            raise GlpiError("Sessão GLPI não iniciada")
        h = self._app_headers()
        h["Session-Token"] = self.session_token
        return h

    def init_session(self) -> str:
        self._search_options.clear()
        self._user_id=None
        self._entity_context=None
        user_token = self.config.normalized_user_token()
        if not user_token:
            raise GlpiError("User Token vazio")
        headers = self._app_headers()
        headers["Authorization"] = f"user_token {user_token}"
        try:
            r = self.http.get(
                f"{self.base}/initSession",
                headers=headers,
                timeout=self.timeout,
                verify=self.tls_verify,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise GlpiError(f"Falha de rede/TLS ao acessar {self.base}: {exc}") from exc
        if not 200 <= r.status_code < 300:
            raise _api_error(r)
        try:
            data = r.json()
        except Exception as exc:
            raise GlpiError(
                "initSession respondeu, mas não retornou JSON válido. "
                "Confirme se a URL aponta para /apirest.php."
            ) from exc
        token = data.get("session_token") if isinstance(data, dict) else None
        if not token:
            raise GlpiError(f"initSession não retornou session_token: {data}")
        self.session_token = str(token)
        return self.session_token

    def kill_session(self) -> None:
        if not self.session_token:
            return
        self.http.get(
            f"{self.base}/killSession",
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.tls_verify,
                allow_redirects=False,
        )
        self.session_token = None

    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False):
        """GET idempotente com retry curto apenas para falhas transitórias.

        A base real mostrou falhas esporádicas em leituras longas. Repetir GET é
        seguro; POST/PUT/DELETE continuam sem retry automático para nunca
        duplicar tarefas, soluções ou alterações no chamado.
        """
        transient_status = {429, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(3):
            self.request_count += 1
            try:
                r = self.http.get(
                    f"{self.base}/{path.lstrip('/')}",
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                    verify=self.tls_verify,
                allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.20 * (2 ** attempt))
                    continue
                raise GlpiError(f"Falha de rede/TLS em GET {path}: {exc}") from exc
            except requests.RequestException as exc:
                raise GlpiError(f"Falha de rede/TLS em GET {path}: {exc}") from exc
            if 200 <= r.status_code < 300:
                return r if raw else r.json()
            if r.status_code in transient_status and attempt < 2:
                delay = 0.20 * (2 ** attempt)
                retry_after = r.headers.get('Retry-After')
                try:
                    if retry_after is not None:
                        delay = min(2.0, max(delay, float(retry_after)))
                except (TypeError, ValueError):
                    pass
                time.sleep(delay)
                continue
            raise GlpiError(f"GET {path}: {_api_error(r)}")
        raise GlpiError(f"Falha transitória em GET {path}: {last_error}")

    def post(self, path: str, payload: dict[str, Any]):
        try:
            r = self.http.post(
                f"{self.base}/{path.lstrip('/')}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                verify=self.tls_verify,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise GlpiError(f"Falha de rede/TLS em POST {path}: {exc}") from exc
        if not 200 <= r.status_code < 300:
            raise _api_error(r)
        return r.json()

    def put(self, path: str, payload: dict[str, Any]):
        try:
            r = self.http.put(
                f"{self.base}/{path.lstrip('/')}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                verify=self.tls_verify,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise GlpiError(f"Falha de rede/TLS em PUT {path}: {exc}") from exc
        if not 200 <= r.status_code < 300:
            raise _api_error(r)
        return r.json()

    def delete(self, path: str):
        try:
            r = self.http.delete(
                f"{self.base}/{path.lstrip('/')}",
                headers=self._headers(),
                timeout=self.timeout,
                verify=self.tls_verify,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise GlpiError(f"Falha de rede/TLS em DELETE {path}: {exc}") from exc
        if not 200 <= r.status_code < 300:
            raise _api_error(r)
        return r.json()

    def get_full_session(self) -> dict[str, Any]:
        return self.get("getFullSession")

    def get_my_profiles(self) -> dict[str, Any]:
        return self.get("getMyProfiles")

    def get_active_profile(self) -> dict[str, Any]:
        data = self.get("getActiveProfile")
        return data if isinstance(data, dict) else {}

    def get_my_entities(self) -> dict[str, Any]:
        return self.get("getMyEntities", {"is_recursive": "true"})

    def get_active_entities(self) -> dict[str, Any]:
        data = self.get("getActiveEntities")
        return data if isinstance(data, dict) else {}

    def profile_rows(self) -> list[dict[str, Any]]:
        return _rows_from_envelope(self.get_my_profiles(), "myprofiles")

    def entity_rows(self) -> list[dict[str, Any]]:
        return _flatten_entities(_rows_from_envelope(self.get_my_entities(), "myentities"))

    def change_active_profile(self, profile_id: int) -> None:
        self.post("changeActiveProfile", {"profiles_id": int(profile_id)})
        self._search_options.clear()
        self._entity_context = None

    def change_active_entities_all(self) -> None:
        if self._entity_context == ("all", True): return
        self.post("changeActiveEntities", {"entities_id": "all", "is_recursive": True})
        self._entity_context = ("all", True)

    def change_active_entity(self, entity_id: int, recursive: bool = False) -> None:
        context = (int(entity_id), bool(recursive))
        if self._entity_context == context: return
        self.post(
            "changeActiveEntities",
            {"entities_id": int(entity_id), "is_recursive": bool(recursive)},
        )
        self._entity_context = context

    def current_user_id(self) -> int:
        if self._user_id is not None: return self._user_id
        data = self.get_full_session()
        session = data.get("session", data) if isinstance(data, dict) else {}
        for key in (
            "glpiID", "glpiID_2", "users_id", "user_id", "glpi_user_id",
        ):
            value = session.get(key) if isinstance(session, dict) else None
            try:
                if value not in (None, ""):
                    self._user_id = int(value)
                    return self._user_id
            except (TypeError, ValueError):
                pass
        raise GlpiError("Não foi possível identificar o ID do usuário autenticado em getFullSession")

    def connection_diagnostics(self) -> dict[str, Any]:
        """Best-effort inspection after initSession; optional calls never invalidate login."""
        result: dict[str, Any] = {
            "auth_ok": bool(self.session_token),
            "user_id": None,
            "active_profile": None,
            "profiles": [],
            "entities": [],
            "warnings": [],
        }
        try:
            result["user_id"] = self.current_user_id()
        except Exception as exc:
            result["warnings"].append(f"getFullSession: {exc}")
        try:
            result["active_profile"] = self.get_active_profile()
        except Exception as exc:
            result["warnings"].append(f"getActiveProfile: {exc}")
        try:
            result["profiles"] = self.profile_rows()
        except Exception as exc:
            result["warnings"].append(f"getMyProfiles: {exc}")
        try:
            result["entities"] = self.entity_rows()
        except Exception as exc:
            result["warnings"].append(f"getMyEntities: {exc}")
        # This is intentionally diagnostic only. Some restricted profiles reject
        # entities_id=all even though their token/session is perfectly valid.
        try:
            self.change_active_entities_all()
            result["all_entities_ok"] = True
        except Exception as exc:
            result["all_entities_ok"] = False
            result["warnings"].append(f"changeActiveEntities(all): {exc}")
        return result

    def _try_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        try:
            data = self.get_ticket(ticket_id)
            if isinstance(data, dict) and int(data.get("id") or 0) == int(ticket_id):
                return data
        except GlpiError as exc:
            if exc.status_code in (403, 404):
                return None
            raise
        return None

    def activate_context_for_ticket(self, ticket_id: int) -> dict[str, Any]:
        """
        Find a profile/entity context in which this user can see the ticket.

        This is the key portability path for users with multiple profiles or
        restricted entity scopes. It never assumes the default profile/entity
        selected by GLPI is the technician context.
        """
        ticket_id = int(ticket_id)

        # Fast path: current profile/current entity.
        ticket = self._try_ticket(ticket_id)
        if ticket:
            entity_id = int(ticket.get("entities_id") or 0)
            if entity_id:
                self.change_active_entity(entity_id, recursive=False)
            return ticket

        try:
            active = self.get_active_profile()
        except Exception:
            active = {}
        try:
            active_id = int(active.get("id") or 0)
        except (TypeError, ValueError):
            active_id = 0

        try:
            profiles = self.profile_rows()
        except Exception:
            profiles = []

        # Try current profile first, then every other profile available to token.
        ordered: list[dict[str, Any]] = []
        if active_id:
            ordered.extend([p for p in profiles if int(p.get("id") or 0) == active_id])
        ordered.extend([p for p in profiles if int(p.get("id") or 0) != active_id])
        if not ordered:
            ordered = [{}]

        diagnostics: list[str] = []
        for profile in ordered:
            pid = int(profile.get("id") or 0) if profile else 0
            pname = str(profile.get("name") or pid or "perfil atual")
            if pid and pid != active_id:
                try:
                    self.change_active_profile(pid)
                except Exception as exc:
                    diagnostics.append(f"perfil {pname}: {exc}")
                    continue

            # First use GLPI's supported 'all' context for that profile.
            try:
                self.change_active_entities_all()
                ticket = self._try_ticket(ticket_id)
                if ticket:
                    entity_id = int(ticket.get("entities_id") or 0)
                    if entity_id:
                        self.change_active_entity(entity_id, recursive=False)
                        ticket = self._try_ticket(ticket_id) or ticket
                    return ticket
            except Exception as exc:
                diagnostics.append(f"perfil {pname}, entidades all: {exc}")

            # Restricted profiles may reject 'all'. Walk only their allowed entities.
            try:
                entities = self.entity_rows()
            except Exception as exc:
                diagnostics.append(f"perfil {pname}, getMyEntities: {exc}")
                entities = []

            for entity in entities:
                try:
                    eid = int(entity.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if not eid:
                    continue
                try:
                    self.change_active_entity(eid, recursive=False)
                    ticket = self._try_ticket(ticket_id)
                    if ticket:
                        return ticket
                except Exception as exc:
                    diagnostics.append(f"perfil {pname}, entidade {eid}: {exc}")

        detail = "; ".join(diagnostics[-6:])
        suffix = f" Detalhes: {detail}" if detail else ""
        raise GlpiError(
            f"Chamado #{ticket_id} não ficou visível em nenhum perfil/entidade "
            f"disponível para este User Token.{suffix}"
        )

    def list_search_options(self, itemtype: str) -> dict[str, Any]:
        if itemtype not in self._search_options:
            data = self.get(f"listSearchOptions/{itemtype}")
            self._search_options[itemtype] = data if isinstance(data, dict) else {}
        return copy.deepcopy(self._search_options[itemtype])

    def search_item_ids(self, itemtype: str, query: str, *, fields: tuple[str, ...], limit: int = 30) -> list[int]:
        """Search visible items through GLPI's legacy Search API.

        This path is useful for restricted technician profiles where GET /User
        is forbidden or incomplete but the normal GLPI user picker/search can
        still find assignable users. Search-option IDs are discovered at
        runtime so we do not hardcode a GLPI-version-specific field number.
        """
        query = str(query or "").strip()
        if not query:
            return []
        options = self.list_search_options(itemtype)
        wanted = {str(x).casefold() for x in fields}
        searchable: list[int] = []
        id_field: int | None = None
        for raw_id, opt in options.items():
            if not isinstance(opt, dict):
                continue
            try:
                oid = int(raw_id)
            except (TypeError, ValueError):
                continue
            field = str(opt.get("field") or "").casefold()
            table = str(opt.get("table") or "").casefold()
            if field == "id" and (not table or table.endswith(f"{itemtype.casefold()}s")):
                id_field = oid
            if field in wanted and not bool(opt.get("nosearch")):
                searchable.append(oid)
        if not searchable:
            return []

        params: dict[str, Any] = {
            "range": f"0-{max(0, min(int(limit), 100) - 1)}",
            "reset": "true",
        }
        for i, field_id in enumerate(searchable[:5]):
            params[f"criteria[{i}][link]"] = "AND" if i == 0 else "OR"
            params[f"criteria[{i}][field]"] = field_id
            params[f"criteria[{i}][searchtype]"] = "contains"
            params[f"criteria[{i}][value]"] = query
        if id_field is not None:
            params["forcedisplay[0]"] = id_field

        data = self.get(f"search/{itemtype}", params)
        rows = data.get("data", {}) if isinstance(data, dict) else {}
        ids: list[int] = []
        if isinstance(rows, dict):
            for key, row in rows.items():
                try:
                    ids.append(int(key))
                    continue
                except (TypeError, ValueError):
                    pass
                if id_field is not None and isinstance(row, dict):
                    try:
                        ids.append(int(row.get(str(id_field))))
                    except (TypeError, ValueError):
                        pass
        elif isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                candidate = row.get(str(id_field)) if id_field is not None else row.get("id")
                try:
                    ids.append(int(candidate))
                except (TypeError, ValueError):
                    pass
        # Preserve order while deduplicating.
        return list(dict.fromkeys(x for x in ids if x > 0))

    def search_user_ids(self, query: str, limit: int = 30) -> list[int]:
        return self.search_item_ids(
            "User", query, fields=("name", "realname", "firstname", "email"), limit=limit
        )

    def list_all(self, itemtype: str, page_size: int = 200) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        start = 0
        while True:
            end = start + page_size - 1
            r = self.get(itemtype, {"range": f"{start}-{end}"}, raw=True)
            data = r.json()
            if not isinstance(data, list):
                if data in (None, {}):
                    break
                raise GlpiError(f"Resposta inesperada ao listar {itemtype}: {data}")
            known={x.get("id") for x in result}
            if data and known and all(x.get("id") in known for x in data):
                raise GlpiError("API repetiu uma página; leitura incompleta")
            result.extend(data)
            content_range = r.headers.get("Content-Range", "")
            total = None
            m = re.search(r"/(\d+)$", content_range)
            if m:
                total = int(m.group(1))
            if not data:
                if total is not None and start < total:
                    raise GlpiError(f"Página vazia antes do total de {itemtype}")
                break
            if total is not None and start + len(data) >= total:
                break
            if total is None and len(data) < page_size:
                break
            start += len(data)
        return result

    def list_subitems(
        self, parent_type: str, parent_id: int, child_type: str, page_size: int = 200
    ) -> list[dict[str, Any]]:
        """Return every visible child row, not only GLPI's default 0-49 range."""
        result: list[dict[str, Any]] = []
        start = 0
        while True:
            end = start + page_size - 1
            r = self.get(
                f"{parent_type}/{int(parent_id)}/{child_type}",
                {"range": f"{start}-{end}", "order": "ASC"},
                raw=True,
            )
            data = r.json()
            if not isinstance(data, list):
                if data in (None, {}):
                    break
                raise GlpiError(
                    f"Resposta inesperada ao listar {child_type} de "
                    f"{parent_type}/{parent_id}: {data}"
                )
            known={x.get("id") for x in result}
            if data and known and all(x.get("id") in known for x in data):
                raise GlpiError("API repetiu uma página; leitura incompleta")
            result.extend(data)
            content_range = r.headers.get("Content-Range", "")
            total = None
            m = re.search(r"/(\d+)$", content_range)
            if m:
                total = int(m.group(1))
            if not data:
                if total is not None and start < total:
                    raise GlpiError(f"Página vazia antes do total de {child_type}")
                break
            if total is not None and start + len(data) >= total:
                break
            if total is None and len(data) < page_size:
                break
            start += len(data)
        return result

    def get_ticket(self, ticket_id: int, expand: bool = False) -> dict[str, Any]:
        value = self.get(f"Ticket/{ticket_id}", {"expand_dropdowns": "true"} if expand else None)
        try:
            valid = isinstance(value, dict) and int(value.get('id') or 0) == int(ticket_id)
            if not expand:
                valid = valid and type(value.get('status')) is not bool and int(value.get('status') or 0) in range(1, 7)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise GlpiError('Resposta de chamado incompleta ou divergente. Atualize a consulta antes de agir.')
        return value

    def ticket_users(self, ticket_id: int) -> list[dict[str, Any]]:
        return self.list_subitems("Ticket", ticket_id, "Ticket_User")

    def ticket_groups(self, ticket_id: int) -> list[dict[str, Any]]:
        return self.list_subitems("Ticket", ticket_id, "Group_Ticket")

    def find_proactive(self, marker: str, entity_id: int) -> list[dict[str, Any]]:
        ids = self.search_item_ids("Ticket", marker, fields=("content",), limit=30)
        rows = []
        for ticket_id in ids:
            ticket = self.get_ticket(ticket_id)
            if int(ticket.get("entities_id") or 0) == entity_id and marker in html.unescape(str(ticket.get("content") or "")):
                rows.append(ticket)
        return rows

    def ticket_tasks(self, ticket_id: int) -> list[dict[str, Any]]:
        return self.list_subitems("Ticket", ticket_id, "TicketTask")

    def ticket_task(self, task_id: int) -> dict[str, Any]:
        data = self.get(f"TicketTask/{task_id}")
        if not isinstance(data, dict):
            raise GlpiError(f"Resposta inesperada para TicketTask/{task_id}: {data}")
        return data

    def task_documents(self, task_id: int) -> list[dict[str, Any]]:
        return self.list_subitems("TicketTask", task_id, "Document_Item")

    def delete_task(self, task_id: int) -> None:
        self.delete(f"TicketTask/{task_id}")

    def create_task(self, ticket_id: int, content: str, actiontime: int, state: int,
                    tech_user_id: int, group_id: int) -> int:
        data = self.post("TicketTask", {"input": {
            "tickets_id": ticket_id,
            "content": content,
            "actiontime": actiontime,
            "state": state,
            "users_id_tech": tech_user_id,
            "groups_id_tech": group_id,
        }})
        try:
            return int(data["id"])
        except Exception as exc:
            raise GlpiError(f"TicketTask criada sem ID válido: {data}") from exc

    def update_task_content(self, task_id: int, content: str) -> None:
        self.put(f"TicketTask/{task_id}", {"input": {"id": task_id, "content": content}})

    def update_task(self, task_id: int, fields: dict[str, Any]) -> None:
        """Update selected TicketTask fields without replacing unrelated values."""
        allowed = {
            "content", "actiontime", "state", "users_id_tech", "groups_id_tech",
        }
        payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not payload:
            return
        payload["id"] = int(task_id)
        self.put(f"TicketTask/{task_id}", {"input": payload})

    def upload_document(self, file_path: Path, entity_id: int) -> dict[str, Any]:
        manifest = {
            "input": {
                "name": file_path.name,
                "_filename": [file_path.name],
                "entities_id": entity_id,
            }
        }
        # requests adds the multipart Content-Type/boundary. Keep App/Session headers only.
        headers = self._headers()
        headers.pop("Content-Type", None)
        with file_path.open("rb") as fh:
            files = {
                "uploadManifest": (None, json.dumps(manifest, ensure_ascii=False), "application/json"),
                "filename[0]": (file_path.name, fh),
            }
            r = self.http.post(
                f"{self.base}/Document/",
                headers=headers,
                files=files,
                timeout=max(self.timeout, 120),
                verify=self.tls_verify,
                allow_redirects=False,
            )
        if not 200 <= r.status_code < 300:
            raise _api_error(r)
        data = r.json()
        if "id" not in data:
            raise GlpiError(f"Upload sem Document ID: {data}")
        return data

    def link_document_to_task(self, document_id: int, task_id: int) -> int:
        data = self.post("Document_Item", {"input": {
            "documents_id": document_id,
            "itemtype": "TicketTask",
            "items_id": task_id,
            # The document must remain linked to TicketTask so the inline image
            # can be opened, but it should not be rendered a second time as a
            # standalone timeline attachment below the task.
            "timeline_position": -1,
        }})
        try:
            return int(data["id"])
        except Exception as exc:
            raise GlpiError(f"Document_Item sem ID: {data}") from exc

    def document(self, document_id: int) -> dict[str, Any]:
        return self.get(f"Document/{document_id}")

    def update_ticket_category(self, ticket_id: int, category_id: int) -> None:
        self.put(f"Ticket/{ticket_id}", {"input": {"itilcategories_id": category_id}})

    def update_ticket_fields(self, ticket_id: int, fields: dict[str, Any]) -> None:
        """Update a conservative allow-list of editable Ticket fields."""
        allowed = {"name", "itilcategories_id", "status", "priority"}
        payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not payload:
            return
        payload["id"] = int(ticket_id)
        self.put(f"Ticket/{ticket_id}", {"input": payload})

    def add_ticket_user(self, ticket_id: int, user_id: int, actor_type: int) -> int:
        data = self.post("Ticket_User", {"input": {
            "tickets_id": ticket_id,
            "users_id": user_id,
            "type": actor_type,
        }})
        return int(data["id"])

    def add_ticket_group(self, ticket_id: int, group_id: int, actor_type: int) -> int:
        data = self.post("Group_Ticket", {"input": {
            "tickets_id": ticket_id,
            "groups_id": group_id,
            "type": actor_type,
        }})
        return int(data["id"])

    def delete_ticket_user_relation(self, relation_id: int) -> None:
        self.delete(f"Ticket_User/{relation_id}")

    def delete_ticket_group_relation(self, relation_id: int) -> None:
        self.delete(f"Group_Ticket/{relation_id}")


def decode_glpi_text(value: Any) -> str:
    return html.unescape(str(value or ""))
