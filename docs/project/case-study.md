# Engineering case study

## Problem

Ticket documentation is repetitive but sensitive: a useful assistant must preserve technical detail without turning generated text into authorization. GLPI Workflow Assistant converts structured input into reviewable operations for existing tickets and proactive requests while keeping the operator in control.

## Constraints

- Local, single-operator Linux deployment.
- GLPI is the first supported integration; installations can have different entities, categories and permissions.
- Evidence may contain sensitive information and must remain distinct from temporary context.
- Network writes can time out after succeeding, so blind retry is unsafe.
- Optional messaging has a separate enablement, recipient and delivery boundary.

## Design

The local FastAPI application receives a structured handoff from the Browser Bridge, parses logical tasks and evidence, and builds a concrete plan. A Dry Run freezes the reviewed payload. Human approval is invalidated when the payload changes. Confirmed operations are then sent through the GLPI REST boundary with idempotency and receipt records.

Proactive creation follows the same principle: structured draft, validated categorization, duplicate protection, Dry Run, approval and only then a privileged create request. Optional messaging remains a separate workflow and never supplies ticket approval.

## Review and approval

The interface exposes T01–T05 tasks, evidence associations, planned operations and receipts before and after execution. A model can help draft content, but only the local operator approves a write. The [workflow diagrams](../architecture/workflows.md) document approval invalidation and uncertain-result handling.

## Evidence

- [Real-UI synthetic gallery](../assets/screenshots/README.md)
- [Offline capture report](../assets/screenshots/capture-report.json)
- [OCR and image hashes](../assets/screenshots/ocr-report.json)
- [Validation matrix](validation-matrix.md)
- [Release manifest](release-manifest.json)

The eight screenshots are deterministic renders of the application UI with intercepted synthetic API responses. The report records zero external requests and zero real writes. They demonstrate interface behavior, not production delivery.

## Receipt and engineering proof

Execution receipts distinguish simulated, confirmed and uncertain states. Regression tests cover approval invalidation, idempotency, evidence acknowledgement and no blind retry after an uncertain response. The release builder produces deterministic Debian and bridge artifacts, checksums, a manifest and a scoped CycloneDX SBOM.

## Skills demonstrated

- Python, FastAPI and REST API integration
- Linux, systemd, Docker and Debian packaging
- Human-in-the-loop automation and idempotency
- Applied security, trust boundaries and threat modeling
- Python and JavaScript regression testing
- CI/CD and reproducible release engineering
- Technical documentation and synthetic evidence design

## Limitations

This is a public beta, not a production-homologated service. Live GLPI compatibility depends on local schema and permissions. Clean-host acceptance, signed Firefox distribution and hosted multi-user authentication remain separate work. See [known limitations](known-limitations.md).
