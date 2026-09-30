from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = (ROOT / 'extension/content.js').read_text(encoding='utf-8')
CAPTURE = (ROOT / 'extension/capture.js').read_text(encoding='utf-8')
MANIFEST = (ROOT / 'extension/manifest.json').read_text(encoding='utf-8')
BACKGROUND = (ROOT / 'extension/background.js').read_text(encoding='utf-8')


def test_bridge_225_versioned():
    assert '"version": "2.4.0"' in MANIFEST
    assert "bridge_generation: '2.4.0'" in CONTENT
    assert "bridgeGeneration: '2.4.0'" in BACKGROUND


def test_first_prompt_has_dom_recovery_fallback():
    assert 'nearestPriorUserTurn' in CONTENT
    assert 'recoverUserTurnEvidence' in CONTENT
    assert 'waitAndRecoverUserTurnEvidence' in CONTENT
    assert "credentials: 'include'" in CONTENT
    assert "source: 'labeled-user-turn'" in CONTENT


def test_dom_recovery_is_conservative_not_guessy():
    assert 'candidates.length <= remaining.length' not in CONTENT
    assert "source: 'unclassified-context'" in CONTENT
    assert 'canRecoverExactRemainder' not in CONTENT


def test_send_waits_bounded_time_for_first_prompt_images():
    assert 'for (const delay of [0, 350, 900, 1700])' in CONTENT
    assert 'The first structured response can finish while ChatGPT is still replacing' in CONTENT


def test_capture_snapshots_before_submit():
    assert "document.addEventListener('pointerdown'" in CAPTURE
    assert "document.addEventListener('click'" in CAPTURE
    assert "document.addEventListener('keydown'" in CAPTURE
    assert 'scanFileInputs();' in CAPTURE


def test_health_exposes_evidence_recovery_diagnostic():
    assert 'evidence_recovery: lastEvidenceRecovery' in CONTENT
