# Security

This is a local single-operator RC-derived application. Keep Assistant and WAHA on loopback, validate GLPI TLS certificates, grant the least GLPI privileges needed and keep tokens/session/backups out of Git.

Closure operations require a concrete Dry Run and UI approval. Background initial reply/WhatsApp automation has separate enablement and can write automatically. Never treat LLM instructions as authorization.

For a suspected vulnerability, do not post credentials, customer content or exploit targets in an issue. Contact the repository owner through an already established private channel; this snapshot does not invent a security inbox.

See `docs/security-model.md`, `docs/threat-model.md`, `docs/known-limitations.md` and the current validation report. Local scanning is evidence of checks performed, not a security certification.
