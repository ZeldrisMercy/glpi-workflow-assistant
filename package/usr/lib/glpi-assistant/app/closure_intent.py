"""Review-only handoff intent; never authorizes a GLPI write by itself."""
import re

OPEN = re.compile(r'^\s*\[DESTINO_CHAMADO\]\s*$', re.I | re.M)
CLOSE = re.compile(r'^\s*\[/DESTINO_CHAMADO\]\s*$', re.I | re.M)
BLOCK = re.compile(r'^\s*\[DESTINO_CHAMADO\]\s*\n(?P<body>[\s\S]*?)^\s*\[/DESTINO_CHAMADO\]\s*$', re.I | re.M)


def parse_intent(closure):
    """Return validated per-ticket review fields; reject ambiguous instructions."""
    source = str(closure or '')
    blocks = list(BLOCK.finditer(source))
    if len(blocks) != len(OPEN.findall(source)) or len(blocks) != len(CLOSE.findall(source)) or len(blocks) > 1:
        raise ValueError('DESTINO_CHAMADO incompleto ou repetido. Revise a instrução de conclusão.')
    if not blocks:
        return None
    block = blocks[0]
    last_task = list(re.finditer(r'\[/TAREFA\]', source, re.I))
    if not last_task or block.start() < last_task[-1].end():
        raise ValueError('DESTINO_CHAMADO deve vir depois das tarefas do mesmo chamado.')
    lines = block.group('body').splitlines()
    fields = {}
    current = None
    for line in lines:
        key = re.match(r'^\s*(acao|incluir_no_lote|solucao)\s*:\s*(.*)$', line, re.I)
        if key:
            current = key.group(1).lower()
            if current in fields:
                raise ValueError('Campo repetido em DESTINO_CHAMADO.')
            fields[current] = key.group(2).strip()
        elif current == 'solucao':
            fields['solucao'] += '\n' + line
        elif line.strip():
            raise ValueError('Campo desconhecido em DESTINO_CHAMADO.')
    if set(fields) != {'acao', 'incluir_no_lote', 'solucao'}:
        raise ValueError('DESTINO_CHAMADO exige acao, incluir_no_lote e solucao.')
    action = fields['acao'].lower()
    batch = fields['incluir_no_lote'].lower()
    solution = fields['solucao'].strip()
    if action not in ('solucionar', 'fechar') or batch not in ('sim', 'nao'):
        raise ValueError('Destino ou escolha de lote inválidos.')
    if len(solution) < 10 or len(solution) > 4000 or re.search(r'^\s*\[/?(?:GLPI_ASSISTANT|GLPI_BATCH|TAREFA|DESTINO_CHAMADO)', solution, re.I | re.M):
        raise ValueError('Descreva uma solução factual, entre 10 e 4000 caracteres, sem marcadores de outros chamados.')
    return {'target': 'solve' if action == 'solucionar' else 'close', 'solution': solution, 'include_in_batch': batch == 'sim'}
