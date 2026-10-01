from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CAP=(ROOT/'extension/capture.js').read_text()
CONTENT=(ROOT/'extension/content.js').read_text()
MANIFEST=(ROOT/'extension/manifest.json').read_text()
WORKBENCH=(ROOT/'package/usr/lib/glpi-assistant/app/static/workbench.js').read_text()
INDEX=(ROOT/'package/usr/lib/glpi-assistant/app/static/index.html').read_text()

def test_bridge_226_and_planner_loaded():
    assert '"version": "2.4.1"' in MANIFEST
    assert '"evidence-plan.js"' in MANIFEST
    assert 'GLPiEvidencePlan?.plan(required, scoped)' in CAP

def test_first_prompt_recovery_requires_evidence_identity():
    assert 'candidates.length <= remaining.length' not in CONTENT
    assert "source: 'labeled-user-turn'" in CONTENT

def test_quick_copy_actions_are_phone_independent():
    assert 'data-copy-message="first"' in WORKBENCH
    assert 'data-copy-message="continuation"' in WORKBENCH
    assert 'data-copy-link' in WORKBENCH
    assert 'wbContinuationMessage' in INDEX
