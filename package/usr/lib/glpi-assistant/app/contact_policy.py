"""Conservative exemption for tickets whose only individual actor is the technician."""
import html
import re


def self_only_ticket(glpi, ticket, user_id, relations=None):
    """True only when GLPI confirms the requester is the assigned technician.

    Errors, empty requester lists and outside contact information fail closed.
    This predicate is used to skip WhatsApp and its receipt for personal work.
    """
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        people = relations if relations is not None else glpi.ticket_users(int(ticket['id']))
        people = [r for r in people if int(r.get('type') or 0) in (1, 2, 3)]
        requesters = [r for r in people if int(r.get('type') or 0) == 1]
        assigned = [r for r in people if int(r.get('type') or 0) == 2]
        if not requesters or not assigned or any(int(r.get('users_id') or 0) != uid for r in people):
            return False
        description = html.unescape(re.sub(r'<[^>]+>', ' ', str(ticket.get('content') or '')))
        # A number or contact label in the description may point to another
        # person. Do not apply the self-only exemption when its owner is unknown.
        if re.search(r'(?<!\d)(?:\+?55\s*)?\(?[1-9]\d\)?[\s().-]*9?\d{4}[\s.-]*\d{4}(?!\d)', description):
            return False
        if re.search(r'\b(?:contato|telefone|celular|whatsapp|fone)\s*[:\-]', description, re.I):
            return False
        return True
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
