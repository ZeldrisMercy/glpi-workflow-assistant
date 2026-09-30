# Security model

The UI/API bind to loopback by default. Runtime Docker settings drop capabilities, enable no-new-privileges and use a read-only root filesystem with writable local state. Host networking means loopback isolation must be reviewed if deployment changes. Local access is a trust boundary, not a substitute for multi-user authentication.

Formalization uses parser validation, evidence association, an opaque cached plan bound to content and files, expiration and state revalidation. Execution consumes the plan and reports operation-level failures; changes are not an atomic GLPI transaction. Background initial replies and messaging are separately enabled workflows and need configuration-level authorization.

Browser Bridge pairing and source checks constrain transport. Optional extension host permissions are broad; review granted domains. Treat LLM output and web content as untrusted input. Transport is not authorization.

Credentials and state remain local and sensitive. Do not expose ports, repository data or sessions without assessing the deployment. The candidate WAHA restrictions are experimental and are not active in the base installation.

Proactive creation adds per-draft approval, idempotency markers and reconciliation for uncertain remote results. See [threat model](threat-model.md), [privacy](privacy-and-data.md), [limitations](known-limitations.md), [API contract](api-contract.md) and [proactive creation](proactive-ticket-creation.md).
