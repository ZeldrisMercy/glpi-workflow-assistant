# Configuration

The implemented environment variable is `GLPI_ASSISTANT_DATA` (default `/data`). It selects the persistent state directory. Use an isolated local directory for development. The host and port are uvicorn command-line arguments, not the speculative GLPI/WAHA variables from the earlier design.

Set the GLPI URL, app token and user token through the setup interface. Configuration is stored locally in `config.json`; the state database is `app.db`. Treat the entire directory as sensitive. Keep backups outside Git and limit access. See [privacy](privacy-and-data.md).

Workbench settings control polling, automatic initial response, stale thresholds, timezone, contact name and templates. Initial-response template supports only `{saudacao}`, `{tecnico}`, `{chamado}`, `{assunto}` (see `initial_reply.py`). A blank/invalid template is rejected. Message templates also support the ticket placeholder `|/Chamado`; use the UI preview to validate contact text.

WAHA settings are local to the messaging module and installer. Pairing, API credentials and session state must never enter fixtures, screenshots or commits. Review [WAHA integration](waha-integration.md) before enabling automatic contact.
