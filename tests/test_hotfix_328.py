from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'package/usr/lib/glpi-assistant/app'
WORKBENCH=(APP/'workbench.py').read_text()
MY=(APP/'static/my-tickets.js').read_text()
INDEX=(APP/'static/index.html').read_text()
CSS=(APP/'static/workspace.css').read_text()


def test_assigned_queue_is_strictly_active_and_never_solved():
    assert "equals_any(status_field,(1,2,3,4))" in WORKBENCH
    assert "current_status not in (1,2,3,4)" in WORKBENCH
    assert '<option value="5">Solucionado</option>' not in MY
    assert 'Todos atribuídos ativos' in MY


def test_closure_workspace_splits_solved_and_closed_with_today_and_7_days():
    assert "view not in ('assigned','solved','closed')" in WORKBENCH
    assert "target_status=5 if view=='solved' else 6" in WORKBENCH
    assert 'own_solution_info' in WORKBENCH
    assert 'data-closure-view="solved"' in MY
    assert 'data-closure-view="closed"' in MY
    assert '<option value="0">Hoje</option>' in MY
    assert '<option value="7">7 dias</option>' in MY
    assert 'Fechamentos' in INDEX and 'Solução aprovada' in MY


def test_queue_has_visible_counter_and_readability_layout():
    assert 'my-queue-counter' in MY
    assert 'data-count' in MY
    assert '.my-ticket-card' in CSS
    assert '.ticket-query-grid' in CSS
    assert '.closure-state-tabs' in CSS
    assert '3.4.0-rc4 · Limitless' in INDEX
