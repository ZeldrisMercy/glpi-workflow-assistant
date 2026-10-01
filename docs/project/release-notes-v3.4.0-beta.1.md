# GLPI Workflow Assistant v3.4.0-beta.1

This first public beta packages the project as an independent, unofficial open-source workflow assistant for GLPI. It is licensed under AGPL-3.0-or-later and is designed for local, reviewed ticketing automation.

## Highlights

- Structured T01–T05 review for existing-ticket documentation.
- Proactive single or batch ticket drafts with catalog validation.
- Dry Run, payload-bound human approval and approval invalidation after edits.
- Evidence association that separates context from final ticket evidence.
- Idempotency and explicit uncertain-result reconciliation.
- Browser Bridge 2.4.1 for structured handoff, acknowledgement and signed Firefox packaging for persistent Web Extension Manager installation.
- Optional messaging workflow with separate enablement and honest delivery states.
- Reproducible Debian and Browser Bridge artifacts with SHA-256 hashes and scoped CycloneDX SBOM.
- Eight real-UI screenshots produced from deterministic synthetic fixtures.
- English and Portuguese documentation, security model, threat model, roadmap and engineering case study.

## Safety model

Generated text is input, not authorization. A local operator reviews a concrete plan before privileged ticket writes. Any payload change invalidates the approval. Remote timeouts are treated as uncertain and do not trigger blind retries.

## Important limitations

This is a beta for a local single-operator environment. Live GLPI behavior depends on the target installation, permissions and catalog. Messaging screenshots are simulations, the signed Firefox XPI is not a Mozilla Add-ons listing claim, and clean-host installation acceptance is still pending.

See the [known limitations](known-limitations.md), [installation guide](../getting-started/debian-installation.md) and [publication report](publication-report.md).
