from initial_reply import request_summary
from whatsapp_auto import receipt_html


def test_form_is_readable_without_interpreting_injected_html():
    result = request_summary('Dados do formulário 1) Unidade: Aurora &amp;#62; Contratos 2) Nome: Ana 3) Descrição: &lt;script&gt;alert(1)&lt;/script&gt;')
    assert result.count('<li>') == 3
    assert 'Aurora &gt; Contratos' in result and '&amp;#62;' not in result
    assert '<script>' not in result and '&lt;script&gt;' in result


def test_nonsequential_numbered_text_is_not_reclassified():
    result = request_summary('Versões 2) antiga 5) nova 9) teste')
    assert '<ul>' not in result


def test_receipt_dates_are_readable_and_no_internal_identifier():
    result = receipt_html({'ack':2,'at':'2026-09-24T17:39:23.312479-03:00','delivery_observed_at':'2026-09-24T20:40:05+00:00','ticket_id':123,'phone':'••••6274','message_id':'private-message-id','text':'Olá <img src=x>\nTeste'})
    assert '24/09/2026 às 17:39:23 (Brasília)' in result
    assert '24/09/2026 às 17:40:05 (Brasília)' in result
    assert 'private-message-id' not in result and '<img' not in result and '&lt;img' in result
    assert 'Leitura confirmada' not in result
