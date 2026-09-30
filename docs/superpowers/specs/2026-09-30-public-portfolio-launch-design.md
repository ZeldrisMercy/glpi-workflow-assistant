# Public Portfolio Launch Design

## Status

Approved design for preparing a public, sanitized portfolio repository from the
private GLPI Assistant development archive.

## Purpose

Publish a technically credible, visually polished and independently owned open
source case study that demonstrates Linux, API integration, security controls,
testing, packaging and release engineering. The public project must help
recruiters understand the work quickly while remaining usable and auditable by
support and infrastructure professionals.

The project was created personally by Ícaro de Souza Mariano to reduce
repetitive ticketing work. It must not imply development for, endorsement by or
affiliation with Meet Tecnologia, VerdanaDesk, any customer, or the GLPI
Project.

## Repository model

- Preserve `ZeldrisMercy/glpi-assistant` as the private development archive.
- Create `ZeldrisMercy/glpi-workflow-assistant` as a separate repository.
- Create the public repository privately, prepare it on
  `release/public-beta`, review it through a pull request, and make it public
  only after the publication gate passes.
- Start from a reviewed source snapshot. Do not copy the private Git history.
- Publish the first release as `v3.4.0-beta.1`.

## Positioning

The public description is:

> An independent, local-first workflow assistant for GLPI with Dry Run, human
> approval, evidence handling and auditable automation.

GLPI is the first and only supported integration in this beta. Documentation
must not claim a generic multi-ITSM platform or future compatibility as present
functionality.

The repository serves three audiences:

1. Technical recruiters who need a two-minute overview of the problem,
   contribution and demonstrated skills.
2. Support and infrastructure professionals who want to install and evaluate
   the workflow with synthetic data.
3. Developers who need architecture, tests, security boundaries and
   contribution instructions.

## License and third-party identity

- License original project code under AGPL-3.0-or-later.
- Preserve all required third-party notices and licenses.
- Document WAHA patches separately from original project code.
- State prominently that the project is independent and unofficial.
- Use third-party product names only to describe interoperability.

## Visual system

Use an open source technical identity:

- Graphite and near-black backgrounds.
- Electric blue and violet accents.
- Green reserved for verified or approved states.
- Monospaced typography for technical elements.
- Visual language based on terminals, pipelines, logs and graphs.
- No employer or customer visual identity.
- No generic cyberpunk or exaggerated “hacker” styling.

Create repository-native SVG brand assets, a 1280×640 social preview and a
consistent frame for screenshots. All assets must remain legible on GitHub
desktop and mobile layouts.

## README experience

The default `README.md` is English, with a complete Portuguese counterpart in
`README.pt-BR.md`. Neither version is a reduced translation.

The opening section contains:

- Project mark, title and one-line value proposition.
- Beta, AGPL, Linux, Python, CI and test badges.
- A compact flow: prompt → structured draft → Dry Run → human approval → GLPI.
- Direct links to quick start, architecture, security, evidence gallery and the
  alternate language.

The remainder explains the problem, main workflows, safety model, proof of
quality, installation and project map. Deep detail belongs in `docs/`.

## Evidence gallery

Capture the real application UI with synthetic fixtures for:

1. Central queue.
2. Expanded ticket card.
3. T01–T05 review.
4. Dry Run.
5. Proactive batch creation.
6. Evidence association.
7. Execution receipt.
8. Optional messaging status.

Every image has a consistent frame, a factual caption and a synthetic-data
notice. Screenshots must be visually inspected and scanned with OCR before
publication.

Provide diagrams for:

- Overall architecture.
- Trust boundaries.
- Existing-ticket closure.
- Proactive creation.
- Plan approval and invalidation.
- Optional WAHA integration.

## Public repository structure

```text
.github/
  ISSUE_TEMPLATE/
  workflows/
demo/
docs/
  architecture/
  getting-started/
  security/
  project/
  assets/
extension/
package/
patches/
qa/
scripts/
tests/
CHANGELOG.md
CODE_OF_CONDUCT.md
CONTRIBUTING.md
LICENSE
NOTICE.md
README.md
README.pt-BR.md
SECURITY.md
SUPPORT.md
```

The application and Debian packaging layout may remain intact where moving
files would create unnecessary functional risk. Documentation must explain any
packaging-oriented paths.

## Branch and contribution model

- `main` is protected and must remain installable.
- Use short-lived `feature/*`, `fix/*`, `docs/*` and exceptional
  `release/*` branches.
- Do not create a permanent `develop` branch.
- Require CI before merge.
- Prefer squash merge and Conventional Commit messages.
- Use semantic versioning.
- Provide issue templates for bugs, features and documentation.
- Provide a pull request template with security, testing and evidence checks.
- Enable Issues and Discussions.

Governance stays proportional to a single-maintainer beta. Do not invent a
foundation, team, steering process or support guarantee.

## Automation and release evidence

Public CI validates:

- Python regression tests.
- JavaScript/DOM regression tests.
- JavaScript syntax.
- Deterministic package build.
- Secret and organization-identifier scan.
- Dependency audit.
- Documentation links.
- Artifact hashes.
- SBOM generation.

Enable Dependabot and CodeQL after the repository is public. Use GitHub secret
scanning and push protection when available.

The `v3.4.0-beta.1` prerelease contains:

- Debian package.
- Chromium Bridge archive.
- Unsigned Firefox development XPI, labeled clearly.
- SHA-256 checksums.
- Package manifest.
- SBOM with an explicit scope statement.
- Validation matrix.
- Release notes.
- Known limitations and rollback instructions.

## Sanitization gate

Publication is blocked until all checks pass:

- Replace MGLIT and every private entity with synthetic organizations.
- Remove Meet Tecnologia, VerdanaDesk and every other legal entity unrelated to
  third-party interoperability.
- Remove private domains, IPs, users, email addresses, phone numbers, tickets,
  logs, databases, tokens, cookies and session data.
- Remove obsolete documentation that could misrepresent the beta.
- Review source, tests, fixtures, comments and generated artifacts.
- Inspect the Debian package, ZIP and XPI contents.
- Inspect every image manually and with OCR.
- Review dependency licenses and third-party notices.
- Run secret and privacy scans on the final tree.
- Confirm that the new public history contains only reviewed content.

Synthetic Brazilian phone numbers must be clearly reserved examples and must
not identify real subscribers. Use documentation domains and non-routable
fixtures where possible.

## Quality claims

The public project may report only reproduced results from the exact published
snapshot. It may describe automated coverage, build reproducibility and
security controls, but must not claim:

- Production readiness.
- Corporate adoption or endorsement.
- Measured productivity gains without a study.
- Security certification.
- Live GLPI or WAHA interoperability not exercised in the public validation.

A clean-host installation is a separate acceptance test. Until completed, the
release remains beta.

## LinkedIn and portfolio deliverables

Create:

- GitHub social preview.
- Reusable architecture visual.
- A short portfolio case study.
- A problem → review → approval → receipt evidence sequence.
- A concise “skills demonstrated” section covering Python/FastAPI, REST APIs,
  Linux/Debian, Docker, applied security, testing, CI/CD, human-in-the-loop
  automation, documentation and release engineering.

The LinkedIn material links to the public repository and uses the same factual
limitations.

## Launch sequence

1. Create the new repository privately.
2. Create `release/public-beta`.
3. Import only the reviewed snapshot.
4. Apply independent branding and documentation.
5. Sanitize source, fixtures, assets and artifacts.
6. Run all automated and manual validation.
7. Open a pull request with evidence.
8. Merge to protected `main`.
9. Create the `v3.4.0-beta.1` prerelease.
10. Present the final repository and sanitization report to the owner.
11. Obtain final confirmation immediately before changing visibility.
12. Make the repository public and verify the anonymous view.

## Success criteria

- A recruiter can understand the problem, contribution and technical depth in
  two minutes.
- A technical reader can install or run the beta from documented commands.
- CI and release validation pass on the published commit.
- No private organization or customer material is present.
- Every screenshot and fixture is demonstrably synthetic.
- License, support boundaries and third-party notices are unambiguous.
- The repository looks deliberate and professional without overstating project
  maturity or community size.

## Out of scope

- Refactoring the product into a generic adapter platform.
- Adding integrations beyond GLPI.
- Building a marketing website.
- Promising production support or SLAs.
- Publishing the private development history.
- Claiming stable production readiness.
