from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'package/usr/lib/glpi-assistant/app'
sys.path.insert(0, str(APP))

from parser import split_closure_batch, parse_closure


def task(i, text=None):
    return f'''[TAREFA:T{i:02d}]\nmodalidade: REMOTO\nnivel: N1\ntempo: 00:0{i if i < 10 else 5}\nestado: FEITO\n\n**{i}\\. Etapa**\n{text or f'Etapa técnica {i}.'}\n[/TAREFA]'''


def full(ticket):
    return f"[GLPI_ASSISTANT:{ticket}]\n" + "\n\n".join(task(i) for i in range(1, 6))


def test_batch_splits_tickets_without_cross_contamination():
    text = f"[GLPI_BATCH]\n{full(901676)}\n\n{full(901677)}\n[/GLPI_BATCH]"
    rows = split_closure_batch(text)
    assert [x['ticket_id'] for x in rows] == [901676, 901677]
    assert all(len(parse_closure(x['closure'])['tasks']) == 5 for x in rows)
    assert '901677' not in rows[0]['closure']
    assert '901676' not in rows[1]['closure']


def test_batch_rejects_duplicate_ticket_id():
    text = f"[GLPI_BATCH]\n{full(901676)}\n\n{full(901676)}\n[/GLPI_BATCH]"
    try:
        split_closure_batch(text)
    except ValueError as exc:
        assert 'repetido' in str(exc).lower()
    else:
        raise AssertionError('ticket duplicado deveria ser rejeitado')


def test_title_is_part_of_change_contract():
    parsed = parse_closure(full(901676).split('\n', 1)[1] + '''\n[ALTERACOES_CHAMADO]\ntitulo: Falha de VPN após mudança de rede\ncategoria: Infraestrutura > Redes > VPN\n[/ALTERACOES_CHAMADO]\n''')
    assert parsed['changes']['titulo'] == 'Falha de VPN após mudança de rede'
    assert parsed['changes']['categoria'].endswith('VPN')


def test_release_ui_has_expandable_central_backup_review_and_receipt():
    html = (APP / 'static/index.html').read_text(encoding='utf-8')
    js = (APP / 'static/workbench.js').read_text(encoding='utf-8')
    appjs = (APP / 'static/app.js').read_text(encoding='utf-8')
    css = (APP / 'static/workspace.css').read_text(encoding='utf-8')
    assert '3.4.0-rc4 · Limitless' in html
    assert 'id="closureReviewPanel"' in html
    assert 'id="wbBackupProgress"' in html
    assert 'id="applySuccessDialog"' in html
    assert 'id="applySuccessOpenGlpi"' in html
    assert 'class="wb-ticket-card' in js
    assert 'SOLICITAÇÃO INICIAL' in js
    assert 'backup-existing-evidence' in js
    assert '.wb-ticket-inspection' in css
    assert '.backup-existing-evidence' in css
    assert 'showApplySuccess' in appjs


def test_bridge_22_contains_outbox_ack_generic_reinjection_and_multi_ticket_guard():
    manifest = (ROOT / 'extension/manifest.json').read_text(encoding='utf-8')
    background = (ROOT / 'extension/background.js').read_text(encoding='utf-8')
    content = (ROOT / 'extension/content.js').read_text(encoding='utf-8')
    capture = (ROOT / 'extension/capture.js').read_text(encoding='utf-8')
    assert '"version": "2.4.0"' in manifest
    assert 'bridgeOutbox22' in background
    assert 'version: 2' in background
    assert 'injectGenericBridge' in background
    assert 'browser.tabs.onUpdated.addListener' in background
    assert 'packetCount' in content
    assert 'multiTicket' in capture
    assert 'múltiplos chamados' in capture


def test_prompt_has_new_full_five_tasks_and_explicit_batch_contract():
    prompt = (ROOT / 'docs/PROMPT_FORMALIZACAO_3.2.md').read_text(encoding='utf-8')
    assert 'gere sempre as cinco etapas **T01, T02, T03, T04 e T05**' in prompt
    assert '[GLPI_BATCH]' in prompt
    assert 'Cada chamado novo/completo continua obedecendo **T01–T05 individualmente**' in prompt
    assert 'Print é evidência, não pré-requisito' in prompt


def test_literal_escaped_newlines_are_repaired_before_parsing():
    escaped = full(901713).replace('\n', '\\n')
    parsed = parse_closure(escaped)
    assert len(parsed['tasks']) == 5
    rows = split_closure_batch(escaped)
    assert rows[0]['ticket_id'] == 901713


def test_hotfix_keeps_quick_actions_and_batch_preview_visible():
    js = (APP / 'static/workbench.js').read_text(encoding='utf-8')
    queue = (APP / 'static/closure-queue.js').read_text(encoding='utf-8')
    css = (APP / 'static/workspace.css').read_text(encoding='utf-8')
    assert 'wb-row-quick' in js
    assert 'data-inspect' in js
    assert 'Prévia deste chamado' in queue
    assert 'queue-select-toggle' in queue
    assert '.queue-evidence-preview' in css
    assert 'wb-ticket-title' in js
    assert 'wb-compact-glpi' in js
    assert 'queue-section queue-evidence-section' in queue
    assert '.queue-preview-item.is-mapped' in css
    assert '@media' in css and 'min-width:0' in css
