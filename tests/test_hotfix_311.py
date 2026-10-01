from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'package/usr/lib/glpi-assistant/app/static'


def test_closure_has_compact_evidence_preview():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert 'id="closureEvidencePreview"' in html
    assert 'id="closurePreviewStrip"' in html
    assert 'id="evidencePreviewDialog"' in html
    assert '3.4.0-beta.1 · Public Beta' in html


def test_preview_reuses_local_files_and_mapping():
    js = (STATIC / 'app.js').read_text(encoding='utf-8')
    assert 'function renderClosureEvidencePreview()' in js
    assert 'function evidenceLabelForFile' in js
    assert 'fileObjectUrlById' in js
    assert 'renderClosureEvidencePreview();' in js
    assert 'showModal' in js


def test_preview_styles_are_compact():
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    assert '.closure-preview-strip' in css
    assert 'flex:0 0 96px' in css
    assert '.evidence-preview-dialog' in css
