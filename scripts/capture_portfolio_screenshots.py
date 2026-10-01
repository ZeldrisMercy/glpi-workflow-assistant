"""Capture eight real-UI portfolio views with deterministic offline fixtures."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "package/usr/lib/glpi-assistant/app"
OUT = ROOT / "docs/assets/screenshots"
SCENARIOS = ROOT / "demo/screenshot-scenarios.json"
EXPECTED_SCREENSHOTS = (
    "01-central-queue.png", "02-expanded-ticket.png", "03-t01-t05-review.png",
    "04-dry-run.png", "05-proactive-batch.png", "06-evidence-association.png",
    "07-execution-receipt.png", "08-messaging-status.png",
)

sys.path.insert(0, str(APP))
from parser import parse_closure  # noqa: E402


def enforce_network_boundary(route: Route, blocked: list[str]) -> None:
    """Permit only loopback requests; abort and record every remote attempt."""
    host = (urlparse(route.request.url).hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        blocked.append(route.request.url)
        route.abort()
    else:
        route.continue_()


def _fixtures() -> dict[str, object]:
    now = 1_790_769_600.0
    ticket = {
        "id": 900001, "title": "Validação de conectividade — exemplo sintético",
        "description": "Validar conectividade em laboratório fictício.",
        "entity": {"id": 1, "label": "Aurora Labs (example)"}, "entity_id": 1,
        "category": {"id": 8, "label": "Infraestrutura / Redes"},
        "status": 2, "priority": 3,
        "requesters": [{"id": 11, "label": "Alex Exemplo"}],
        "assigned_users": [{"id": 9, "label": "Técnico de laboratório"}],
        "assigned_groups": [], "observers": [],
        "url": "https://glpi.example.invalid/front/ticket.form.php?id=900001",
    }
    row = {
        **ticket, "entity": "Aurora Labs (example)", "category": "Infraestrutura / Redes",
        "contacts": [], "seen_at": now - 3600, "last_own_update": now - 3600,
        "stale_hours": 1, "stale": False, "baseline": False, "initial": "pausada",
    }
    prefs = {
        "enabled": False, "auto_initial": False, "interval": 120, "stale_hours": 24,
        "timezone": "America/Sao_Paulo", "country_code": "55", "contact_name": "Alex Exemplo",
        "initial_reply_template": "{saudacao}, aqui é {tecnico}. Vou acompanhar o chamado #{chamado} — {assunto}.",
    }
    draft = {
        "schema_version": 1, "operation": "create_proactive", "draft_ref": "P01",
        "title": "Documentação do inventário de laboratório",
        "description": "Registrar dados técnicos levantados no ambiente fictício.",
        "entity": "Aurora Labs (example)", "category": "Documentação / Inventário",
        "priority": 3, "requester": "", "assignee": "", "groups": [], "target": "active",
        "solution": "", "evidence": [],
        "tasks": [{"id": "T01", "title": "Registro e conferência", "content": "Informações revisadas no laboratório.", "actiontime": 300, "mode": "PRESENCIAL", "evidence_ids": []}],
    }
    proactive = [
        {"id": "synthetic-p01", "draft": draft, "prompt_timestamp": "2026-09-30T09:20:00-03:00", "conversation_key": "synthetic:p01", "images": {}},
        {"id": "synthetic-p02", "draft": {**draft, "draft_ref": "P02", "title": "Conferência preventiva de conectividade", "category": "Redes / Diagnóstico", "priority": 2}, "prompt_timestamp": "2026-09-30T09:35:00-03:00", "conversation_key": "synthetic:p02", "images": {}},
    ]
    return {"now": now, "ticket": ticket, "row": row, "prefs": prefs, "proactive": proactive}


def _plan(ticket: dict, text: str) -> dict:
    parsed = parse_closure(text)
    operations = [{
        "op": "create_task", "task_id": task["id"], "modality": task["modalidade"],
        "level": task.get("nivel"), "actiontime": task["actiontime"],
        "evidences": task.get("evidences", []),
    } for task in parsed["tasks"]]
    return {
        "ticket": ticket, "parsed": parsed, "operations": operations, "current_user_id": 9,
        "task_count": len(operations), "incoming_task_count": len(operations),
        "skipped_task_count": 0, "evidence_count": len(parsed.get("evidence_ids", [])),
        "has_actionable_operations": True, "plan_id": "offline-synthetic-plan",
        "required_evidence_ids": parsed.get("evidence_ids", []),
    }


def _api(route: Route, fixtures: dict[str, object]) -> None:
    request = route.request
    path = request.url.split("/api/", 1)[1].split("?", 1)[0]
    try:
        body = request.post_data_json if request.post_data else {}
    except Exception:
        body = {}
    ticket = fixtures["ticket"]
    payload: object = {"items": []}
    if path == "status":
        payload = {"configured": True, "config": {"url": "https://glpi.example.invalid"}, "version": "3.4.0-beta.1", "catalog": {}, "current_user_id": 9}
    elif path == "workbench":
        payload = {"items": [fixtures["row"]], "last_sync": fixtures["now"], "settings": fixtures["prefs"], "errors": []}
    elif path == "workbench/settings": payload = fixtures["prefs"]
    elif path == "workbench/contact-profile": payload = {"user_id": 9, "name": "Alex Exemplo", "source": "synthetic"}
    elif path == "ticket/900001": payload = ticket
    elif path == "ticket/900001/tasks": payload = {"tasks": []}
    elif path == "templates/900001": payload = {"ticket_id": 900001, "tasks": [], "suggested": False}
    elif path == "parse": payload = parse_closure(body.get("text", ""))
    elif path == "plan": payload = _plan(ticket, body.get("text", ""))
    elif path == "review/suggest": payload = {"suggestions": [], "confidence": "high", "reason": "Fixture sintética preserva título e categoria."}
    elif path == "execute":
        payload = {"ok": True, "expected_task_count": 5, "verified_task_count": 5, "skipped_existing_at_apply_count": 0, "results": [], "errors": [], "log": ["SIMULAÇÃO OFFLINE", "5 tarefas validadas", "0 escritas remotas"]}
    elif path == "bridge/info": payload = {"paired": False}
    elif path in {"bridge/inbox", "bridge/events"}: payload = {"items": []}
    elif path == "proactive/drafts": payload = {"items": fixtures["proactive"]}
    elif path == "proactive/plan":
        payload = {"plan_id": "synthetic-proactive-plan", "digest": "0" * 64, "pending_fields": [], "resolved": {"entity": {"id": 1, "full_name": "Aurora Labs (example)"}, "category": {"id": 8, "full_name": "Documentação / Inventário"}}}
    elif path == "whatsapp":
        payload = {"status": "WORKING", "connected_account": "00000000000@c.us", "detail": "Sessão sintética; nenhum serviço externo consultado.", "enabled": False, "monitor_enabled": False, "baseline_ready": False, "automation_detail": "Demonstração offline: envios pausados e nenhuma entrega verificada.", "events": []}
    route.fulfill(json=payload)


def main() -> None:
    document = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    if tuple(item["file"] for item in document["scenarios"]) != EXPECTED_SCREENSHOTS:
        raise RuntimeError("Scenario manifest does not match the public gallery contract")
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Chromium is required. Set CHROMIUM_EXECUTABLE to an audited local executable.")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    errors: list[str] = []
    blocked: list[str] = []
    captures: list[str] = []
    fixtures = _fixtures()
    formalization = (ROOT / "demo/fixtures/formalization.txt").read_text(encoding="utf-8")
    evidence_text = formalization.replace("Perfil corrigido e conexão estabelecida no laboratório.", "Perfil corrigido e conexão estabelecida no laboratório. [EVIDÊNCIA:E01]")

    with tempfile.TemporaryDirectory(prefix="glpi-portfolio-") as data_dir:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(APP), "--host", "127.0.0.1", "--port", "8765"],
            env={**os.environ, "GLPI_ASSISTANT_DATA": data_dir}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(80):
                try:
                    urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Synthetic demo server failed to start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                page = browser.new_page(viewport=document["viewport"], device_scale_factor=1)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", lambda route: enforce_network_boundary(route, blocked))
                page.route("**/health", lambda route: route.fulfill(json={"version": "3.4.0-beta.1"}))
                page.route("**/api/**", lambda route: _api(route, fixtures))
                page.goto(document["base_url"], wait_until="networkidle")
                page.locator("#wbRows .wb-ticket-card").first.wait_for()

                def capture(filename: str) -> None:
                    page.screenshot(path=str(OUT / filename), full_page=False)
                    captures.append(filename)

                capture(EXPECTED_SCREENSHOTS[0])
                page.locator("#wbRows .wb-ticket-card summary").first.click()
                capture(EXPECTED_SCREENSHOTS[1])
                page.locator('.workspace-nav a[href="#operacao"]').click()
                page.locator("#ticketId").fill("900001")
                page.locator("#loadTicket").click()
                page.locator("#ticketSummary").get_by_text("#900001", exact=False).wait_for()
                page.locator("#closure").fill(formalization)
                page.locator("#tasks .task").first.wait_for()
                expect(page.locator("#executeBtn")).to_be_enabled()
                focus_style = page.add_style_tag(content="""
                    body.portfolio-task-focus .parser-card {
                        position: fixed; inset: 92px 20px 20px 256px; z-index: 9999;
                        overflow: hidden; padding: 26px; background: #151b29;
                    }
                    body.portfolio-task-focus #tasks {
                        display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px;
                    }
                    body.portfolio-task-focus #tasks .detected-count { grid-column: 1 / -1; }
                    body.portfolio-task-focus #tasks .task { margin: 0; min-width: 0; }
                    body.portfolio-task-focus #tasks .task-head { align-items: flex-start; flex-direction: column; gap: 10px; }
                """)
                page.evaluate("document.body.classList.add('portfolio-task-focus'); window.scrollTo(0, 0)")
                capture(EXPECTED_SCREENSHOTS[2])
                page.evaluate("document.body.classList.remove('portfolio-task-focus')")
                focus_style.evaluate("node => node.remove()")
                page.locator("#plan").scroll_into_view_if_needed()
                capture(EXPECTED_SCREENSHOTS[3])
                page.locator('.workspace-nav a[href="#proativos"]').click()
                page.locator("#prList .pr-row").first.wait_for()
                page.locator("#prAll").check()
                page.locator("#prReview").click()
                page.get_by_text("Revisão concluída", exact=False).wait_for()
                page.locator("#proativos").evaluate("node => node.scrollIntoView({block: 'start'})")
                capture(EXPECTED_SCREENSHOTS[4])
                page.locator('.workspace-nav a[href="#operacao"]').click()
                page.locator("#closure").fill(evidence_text)
                page.locator('[data-evidence="E01"]').wait_for()
                page.locator("#filePicker").set_input_files(str(ROOT / "docs/assets/brand/social-preview.png"))
                page.locator('[data-evidence="E01"]').select_option(index=1)
                page.locator("#evidencias").scroll_into_view_if_needed()
                capture(EXPECTED_SCREENSHOTS[5])
                page.locator("#planBtn").click()
                expect(page.locator("#executeBtn")).to_be_enabled()
                page.on("dialog", lambda dialog: dialog.accept())
                page.locator("#executeBtn").click()
                page.locator("#applySuccessDialog").wait_for(state="visible")
                page.evaluate("""() => {
                    const dialog = document.querySelector('#applySuccessDialog');
                    dialog.querySelector('.section-kicker').textContent = 'SIMULAÇÃO OFFLINE';
                    document.querySelector('#applySuccessTitle').textContent = 'Execução simulada concluída';
                    document.querySelector('#applySuccessSubtitle').textContent = 'Fixture offline: nenhuma escrita foi enviada ao GLPI.';
                    const labels = [...dialog.querySelectorAll('.success-stat span')];
                    if (labels[0]) labels[0].textContent = 'tarefas simuladas';
                    if (labels[1]) labels[1].textContent = 'evidência sintética';
                    document.querySelector('#applySuccessAppliedList').innerHTML = '<div class="success-applied"><strong>✓ Validação simulada</strong><p>O executor local conferiu o plano sem contatar serviços externos.</p></div>';
                    document.querySelector('#applySuccessOpenGlpi').hidden = true;
                }""")
                capture(EXPECTED_SCREENSHOTS[6])
                page.locator("#applySuccessDialog").evaluate("dialog => dialog.close()")
                page.locator('.workspace-nav a[href="#bridge-ia"]').click()
                page.locator("#waStatus").wait_for()
                page.locator("#waStatus").scroll_into_view_if_needed()
                capture(EXPECTED_SCREENSHOTS[7])
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
    report = {
        "mode": "real application HTML/CSS/JavaScript with deterministic synthetic API fixtures",
        "capture_framing": "The T01–T05 view applies capture-only CSS to arrange the five existing UI cards in one viewport; content and state are unchanged.",
        "viewport": document["viewport"], "captures": captures, "page_errors": errors,
        "blocked_external_requests": blocked, "external_requests_fulfilled": 0, "real_glpi_writes": 0,
    }
    (OUT / "capture-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if captures != list(EXPECTED_SCREENSHOTS) or errors:
        raise RuntimeError(f"Capture contract failed: {report}")


if __name__ == "__main__":
    main()
