# Validation matrix — 3.4.0-beta.1

| Area | Automated evidence | Boundary |
|---|---|---|
| Python behavior | `pytest tests qa/test_waha_installer.py` | Remote integrations are simulated. |
| Browser Bridge | `python scripts/check_javascript.py` | DOM and browser APIs use deterministic fixtures. |
| Approval safety | Proactive plan/execute and evidence ACK regressions | A passing test does not authorize a real GLPI write. |
| Debian package | Two byte-identical builds, metadata and shell syntax | Clean-host installation is recorded separately. |
| Browser archives | Deterministic ZIP/XPI entries and hashes | Firefox XPI is unsigned and development-only. |
| Dependencies | CycloneDX `sbom.cdx.json` | Covers Python and npm application dependencies only. |
| Sanitization | Tree, archive and OCR publication audits | Manual screenshot review remains required. |

Actual counts, commit SHA and clean-host results are recorded in the candidate
publication report. This matrix defines checks; it is not a certification or a
production-readiness claim.
