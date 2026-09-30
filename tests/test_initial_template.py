import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'package/usr/lib/glpi-assistant/app'))
from initial_reply import render_intro
from workbench import Settings
import pytest
from pydantic import ValidationError


def test_template_substitution_escapes_ticket_text_without_recursion():
    result = render_intro('Olá #{chamado}\n{assunto}', 123, '<script>{chamado}</script>')
    assert '#123<br>' in result
    assert '<script>' not in result
    assert '&lt;script&gt;{chamado}&lt;/script&gt;' in result


def test_pause_partial_payload_does_not_reset_other_preferences():
    assert Settings(auto_initial=False).model_dump(exclude_unset=True) == {'auto_initial': False}


def test_initial_template_size_is_bounded():
    with pytest.raises(ValidationError):
        Settings(initial_reply_template='a' * 4001)
