from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'extension'
STATIC=ROOT/'package/usr/lib/glpi-assistant/app/static'

def test_bridge_tracks_current_detection_and_ttl_cleanup():
    bg=(EXT/'background.js').read_text(encoding='utf-8')
    content=(EXT/'content.js').read_text(encoding='utf-8')
    popup=(EXT/'popup.js').read_text(encoding='utf-8')
    capture=(EXT/'capture.js').read_text(encoding='utf-8')
    assert 'bridgeLastDetected222' in bg
    assert 'bridge:contract-detected' in bg and 'bridge:contract-detected' in content
    assert 'bridge-evidence-cleanup' in bg
    assert '12 * 60 * 60 * 1000' in bg
    assert 'protectedHashes' in bg
    assert 'created_at: Date.now()' in capture
    assert 'FECHAMENTO ATUAL' in popup

def test_handoff_mirrors_single_and_batch_and_prunes_completed():
    app=(STATIC/'app.js').read_text(encoding='utf-8')
    queue=(STATIC/'closure-queue.js').read_text(encoding='utf-8')
    assert "ClosureQueue.receive(item, { activate: false, files: receivedFiles })" in app
    assert "importHandoff(item, { source: '∞ IA Browser Bridge', receivedFiles })" in app
    assert 'function pruneCompleted()' in queue
    assert "new Set(['Fechado', 'Solucionado', 'Aplicado'])" in queue
    assert "sameTicket" in queue and "conteúdo anterior foi substituído" in queue
    assert 'window.ClosureQueue = { receive, pruneCompleted' in queue


def test_partial_evidence_does_not_block_text_delivery():
    main=(ROOT/'package/usr/lib/glpi-assistant/app/main.py').read_text(encoding='utf-8')
    content=(EXT/'content.js').read_text(encoding='utf-8')
    app=(STATIC/'app.js').read_text(encoding='utf-8')
    assert 'O texto do fechamento não espera os prints' in main
    assert 'prints pendentes' in content
    segment = content[content.index("if (missing.length &&"):content.index("const unexpected = supplied.filter")]
    assert 'return null' not in segment
    assert 'const evidencePending = item.evidence_ready === false' in app
    assert 'Abrir texto' in app
