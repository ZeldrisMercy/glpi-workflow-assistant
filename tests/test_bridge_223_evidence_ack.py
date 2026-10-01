from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'extension'
APP=ROOT/'package/usr/lib/glpi-assistant/app'
STATIC=APP/'static'

def test_partial_ack_preserves_captured_evidence():
    bg=(EXT/'background.js').read_text(encoding='utf-8')
    content=(EXT/'content.js').read_text(encoding='utf-8')
    assert 'if (!evidencePending) await cleanupCapturedEvidence(current)' in bg
    assert "if (message.evidence_ready !== false)" in content
    assert 'prints preservados' in content

def test_staged_evidence_is_merged_server_side():
    evidence=(APP/'evidence_bridge.py').read_text(encoding='utf-8')
    main=(APP/'main.py').read_text(encoding='utf-8')
    assert 'Merge evidence updates by E-ID instead of replacing the whole set' in evidence
    assert "merged[item['id']]" in evidence
    assert 'handoff_view = _bridge_row(row, include_closure=False)' in main
    assert 'handoff_view["evidence_ready"]' in main

def test_batch_has_visible_drag_drop_fallback():
    queue=(STATIC/'closure-queue.js').read_text(encoding='utf-8')
    css=(STATIC/'workspace.css').read_text(encoding='utf-8')
    assert 'data-evidence-dropzone' in queue
    assert 'data-drop-clip' in queue and '📎 <span>Arraste aqui</span>' in queue
    assert "dropzone.addEventListener('drop'" in queue
    assert "panel.addEventListener('paste'" in queue
    assert '.queue-evidence-section.is-dragging' in css
