"""A small literal template contract; no expression execution or HTML rendering."""
import re

DEFAULT_CONTACT_MESSAGE = (
    '{saudacao}, tudo bem? Sou {tecnico}, da Equipe de Suporte. '
    'Estou entrando em contato referente ao chamado #{chamado} – {assunto}. '
    'Podemos prosseguir por aqui?'
)
DEFAULT_CONTINUATION_MESSAGE = (
    '{saudacao}, tudo bem? Sou {tecnico}, da Equipe de Suporte. '
    'Estou dando continuidade ao atendimento referente ao chamado #{chamado} – {assunto}. '
    'Podemos prosseguir por aqui?'
)
CONTACT_FIELDS = {'saudacao', 'nome', 'tecnico', 'chamado', 'assunto', 'empresa'}


def normalize_contact_template(value: str) -> str:
    # Accept the shorthand suggested by the user, but store one canonical syntax.
    return re.sub(r'\|/Chamado\b', '{chamado}', value, flags=re.I)


def validate_contact_template(value: str) -> str:
    value = normalize_contact_template(value)
    if not value.strip() or len(value) > 2000:
        raise ValueError('A mensagem deve conter entre 1 e 2000 caracteres.')
    tokens = re.findall(r'\{([^{}]*)\}', value)
    if any(token not in CONTACT_FIELDS for token in tokens):
        invalid = next(token for token in tokens if token not in CONTACT_FIELDS)
        raise ValueError('Marcador não reconhecido: {' + invalid + '}. Use os botões de inserção.')
    rest = re.sub(r'\{[^{}]*\}', '', value)
    if '{' in rest or '}' in rest or '|/' in rest:
        raise ValueError('Há um marcador incompleto. Use os botões para inseri-lo novamente.')
    if 'chamado' not in tokens:
        raise ValueError('Mantenha {chamado} no texto para preencher o número automaticamente.')
    if re.search(r'\b(?:chamado|ticket)\s*#?\s*\d+', value, re.I):
        raise ValueError('Troque o número fixo do chamado por {chamado}.')
    return value
