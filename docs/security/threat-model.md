# Threat model

| Threat | Implemented mitigation / limit |
|---|---|
| Malformed or injected LLM content | Parser validation; human review. LLM output is untrusted. |
| Wrong ticket/evidence | Ticket checks and explicit evidence mapping; operator must inspect content. |
| Replay or state change | Bound, expiring, consumed plan; live state rechecks. Partial failures are not atomic rollback. |
| Silent background write | Initial reply/messaging need configuration-level authorization; separate from closure approval. |
| Credential/session leak | Private local state, ignored runtime files, publication review. Host compromise remains a risk. |
| Exposed local API | Loopback default and local request checks; not a multi-user authentication system. |
| Wrong category/requester | Catalog resolution and review; ambiguity must be resolved before applying. |
| Extension scope | Pairing/source controls; optional host permissions remain broad. |
| WAHA privilege | Base image/installer restrictions and localhost; experimental patch is not active. |

Proactive creation persists an operation marker before remote writes, binds approval to the current draft and blocks automatic retries when a result is uncertain. Live GLPI acceptance testing remains required.
