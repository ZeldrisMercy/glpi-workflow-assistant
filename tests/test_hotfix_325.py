from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'package/usr/lib/glpi-assistant/app/static/index.html').read_text()
APP=(ROOT/'package/usr/lib/glpi-assistant/app/static/app.js').read_text()
CAP=(ROOT/'extension/capture.js').read_text()

def test_receipt_markup_precedes_app_script_and_has_tabs():
    assert HTML.index('id="applySuccessDialog"') < HTML.index('/static/app.js?v=3.4.0-beta.1')
    assert 'id="applySuccessVisualTab"' in HTML
    assert 'id="applySuccessLogTab"' in HTML
    assert 'id="applySuccessAppliedList"' in HTML

def test_receipt_buttons_have_handlers():
    for ident in ('applySuccessOpenGlpi','applySuccessStay','applySuccessNext','applySuccessVisualTab','applySuccessLogTab'):
        assert ident in APP
    assert 'renderApplySuccessVisual' in APP

def test_first_prompt_route_promotion_is_supported():
    assert 'canPromoteCapturedRoute' in CAP
    assert "from.hostname === 'chatgpt.com'" in CAP
    assert "!oldHasConversation && newHasConversation" in CAP
    assert 'for (const delay of [0, 80, 180, 350, 700, 1200, 2200])' in CAP
