# Portfolio case study

## Context and contribution

GLPI Assistant supports the documentation work of a Linux-based IT support operator. Its source combines a local FastAPI service, a browser handoff extension, structured text parsing, evidence mapping, reviewed GLPI writes, optional messaging and Debian packaging.

The work demonstrates troubleshooting, API integration, local security boundaries, incident documentation discipline and release engineering. It supports a transition from support/infrastructure toward security operations without claiming professional SOC seniority or describing the app as a SIEM/SOAR platform.

## Engineering decisions

- LLM output remains data; it does not carry authorization for GLPI closure.
- A concrete Dry Run binds input and evidence to a reviewed plan.
- Logical task identifiers and native history reduce duplicate submissions.
- Uncertain messaging results do not trigger blind automatic resend.
- Local-only deployment reduces exposure, with the host administrator still trusted.
- Context images and final evidence have distinct roles.

## Evidence and limits

See `source-map.md`, `validation.md`, the screenshot gallery and `internal-audit/`. Screenshots are actual UI renders with mocked data. No numerical productivity benefit, production security certification or unobserved real delivery is claimed.
