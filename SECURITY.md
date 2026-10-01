# Security policy

## Supported versions

Only the latest tagged beta receives security fixes. The project is local,
single-operator software and is not represented as production ready or as a
security-certified product.

## Report a vulnerability privately

Do not open a public Issue with exploit details, credentials, customer content
or affected private endpoints. Use GitHub's **Report a vulnerability** private
advisory flow on the Security tab. If that flow is unavailable, contact the
repository owner through the private contact method listed on their GitHub
profile and disclose only enough information to establish a safe channel.

Include the affected version, prerequisites, minimal reproduction, impact and
sanitized evidence. Do not test against systems you do not own or have explicit
permission to assess. No response or remediation SLA is offered.

## Security boundaries

- Bind the assistant and optional WAHA service to loopback.
- Validate GLPI TLS certificates and grant the least API privileges required.
- Keep tokens, sessions, databases, backups and real screenshots outside Git.
- Treat generated text and browser context as input, never authorization.
- Require a current Dry Run and human approval for privileged GLPI writes.
- Do not automatically retry a write whose result is uncertain.

See `docs/security-model.md`, `docs/threat-model.md` and
`docs/known-limitations.md` for the current technical model. Automated checks
are evidence of controls exercised, not certification.
