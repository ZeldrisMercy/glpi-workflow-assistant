# Release process

Use a sanitized baseline and new history. Run the full Python/JavaScript suite, package validation, dependency and secret/privacy scans. Compare source-map and README claims with the exact snapshot. Capture the real UI using synthetic fixtures. Inspect every artifact for state, client data and embedded secrets.

A public release requires the owner to resolve ownership/licensing and authorize public visibility. The owner completed those gates for `v3.4.0-beta.1` on 2026-10-01. Future visibility, release or ownership changes require their own explicit authorization. Candidate WAHA patches are not represented as deployed.

Build with `python3 scripts/build_portfolio.py`; publish hashes, package manifest, the Python SBOM and validation matrix with any eventual release. SBOM scope must explicitly exclude unaudited Docker OS/browser/WAHA transitive components.
