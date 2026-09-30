# Contributing

Thank you for improving GLPI Workflow Assistant. This is a single-maintainer
beta, so small, reviewable changes with concrete evidence are easiest to merge.

## Workflow

1. Open or reference an Issue for behavior changes.
2. Branch from `main` using `feature/*`, `fix/*` or `docs/*`.
3. Add a failing regression test before changing behavior.
4. Run the Python, JavaScript and publication-audit commands documented in
   `docs/testing.md`.
5. Open a focused pull request using the repository template.

Use Conventional Commits, such as `feat:`, `fix:`, `docs:`, `test:`, `build:`,
`ci:` and `security:`. Branches are short-lived; there is no permanent
`develop` branch. Maintainers normally squash merge after required checks pass.

## Safety and evidence

Never commit credentials, customer data, private organizations, GLPI catalogs
from real environments, sessions, databases, logs or original screenshots.
Use synthetic fixtures and preserve their formatting relationships. Treat LLM
content as untrusted input, keep it separate from authorization and never add a
blind retry after an uncertain remote write.

## Certificate of origin

By contributing, you certify that you created the contribution or have the
right to submit it, and that it may be distributed under
`AGPL-3.0-or-later`. Add `Signed-off-by: Your Name <address>` to commits with
`git commit -s`. This is a lightweight Developer Certificate of Origin-style
attestation; no contributor license agreement is required.
