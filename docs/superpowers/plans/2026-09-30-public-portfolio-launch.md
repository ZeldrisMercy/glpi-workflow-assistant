# Public Portfolio Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a clean-history, independently branded and verifiably sanitized `v3.4.0-beta.1` portfolio repository for GLPI Workflow Assistant without exposing any employer, customer or private-environment identity.

**Architecture:** Preserve `ZeldrisMercy/glpi-assistant` as the private development archive and build `ZeldrisMercy/glpi-workflow-assistant` from one reviewed source snapshot in a separate private repository. Treat sanitization, reproducible packaging, screenshot capture and release evidence as testable build inputs; keep publication itself behind an explicit owner-confirmation gate.

**Tech Stack:** Python 3.12, FastAPI, pytest, Node.js 24, jsdom, Playwright, Debian packaging, WebExtension APIs, GitHub Actions, CodeQL, Dependabot, CycloneDX SBOM, SVG and Markdown.

**Spec:** `docs/superpowers/specs/2026-09-30-public-portfolio-launch-design.md`

## Global Constraints

- Keep `ZeldrisMercy/glpi-assistant` private as the development archive; do not rewrite or copy its Git history.
- Prepare `ZeldrisMercy/glpi-workflow-assistant` privately on `release/public-beta`; request explicit owner confirmation immediately before changing visibility.
- Publish original project code under `AGPL-3.0-or-later`; preserve third-party notices and keep WAHA patches separately identified.
- Present the project as independent and unofficial; GLPI is the only supported integration in this beta.
- Remove Meet Tecnologia, VerdanaDesk, MGLIT and every other employer, customer or private-environment identifier from source, history, fixtures, docs, images and artifacts.
- Use synthetic data only; use documentation domains and clearly reserved/non-routable fixture values wherever possible.
- First public version is `v3.4.0-beta.1`; do not claim production readiness, adoption, certification, measured productivity gains or untested live integrations.
- Default documentation language is English in `README.md`; `README.pt-BR.md` is a complete Portuguese counterpart.
- Keep `main` installable and protected; use short-lived `feature/*`, `fix/*`, `docs/*` and exceptional `release/*` branches, squash merge and Conventional Commits.
- Treat clean-host installation as a separate acceptance test; the release remains beta even when that test passes.
- Do not commit generated caches, runtime databases, credentials, tokens, session state, real logs or dependency directories.

## Review Focus

- A blocked organization name hidden by case, punctuation or Unicode normalization must fail the publication audit; Task 2 adds normalized-identifier tests.
- A secret or private identifier embedded inside `.deb`, `.zip`, `.xpi`, JSON or image OCR output must block release; Tasks 2, 6 and 9 add archive and OCR checks.
- A changed payload after Dry Run must invalidate approval and prevent execution; Task 4 preserves the existing contract tests in the exact release snapshot.
- A network request during screenshot generation must be rejected so evidence cannot contact a live GLPI or messaging endpoint; Task 6 tests the offline capture boundary.
- A release whose displayed version, Debian version, filenames, manifest, checksums or tag disagree must fail validation; Task 4 adds a single-source version contract.

---

## File Structure

The public repository keeps the existing packaging layout to minimize functional risk. New or materially changed responsibilities are:

| Path | Responsibility |
|---|---|
| `LICENSE` | Canonical GNU AGPL v3 license text. |
| `NOTICE.md` | Ownership, unofficial-project statement and third-party attribution boundaries. |
| `README.md`, `README.pt-BR.md` | Recruiter-first overview and complete bilingual project entry point. |
| `docs/assets/brand/` | Repository-native mark, hero, architecture visual and social preview source/export. |
| `docs/assets/screenshots/` | Reproducible, synthetic evidence gallery and capture/OCR reports. |
| `docs/architecture/`, `docs/getting-started/`, `docs/security/`, `docs/project/` | Focused public documentation grouped by user intent. |
| `scripts/publication_policy.py` | Normalization, path exclusions and policy shared by publication audits. |
| `scripts/audit_publication.py` | Scan source tree and built archives for secrets and blocked identities. |
| `scripts/verify_release.py` | Verify version agreement, required files, artifact names, hashes, manifest and SBOM. |
| `scripts/capture_portfolio_screenshots.py` | Produce the eight real-UI synthetic screenshots with all external traffic blocked. |
| `scripts/ocr_screenshots.py` | Produce reviewable OCR text and fail on blocked identifiers. |
| `scripts/build_portfolio.py` | Deterministically build the Debian package and browser-extension archives for the beta. |
| `tests/test_publication_audit.py` | Publication-policy and nested-archive regression coverage. |
| `tests/test_release_contract.py` | Cross-file version and release-bundle contract. |
| `tests/test_screenshot_contract.py` | Scenario count, synthetic-only fixtures, network-block and report contract. |
| `.github/workflows/ci.yml` | Regression, audit, docs and reproducible-build gates for pushes and PRs. |
| `.github/workflows/codeql.yml` | Public-repository static analysis for Python and JavaScript. |
| `.github/workflows/release.yml` | Tagged prerelease build, verification, SBOM and artifact upload. |
| `.github/dependabot.yml` | Monthly pip, npm and Actions dependency updates. |
| `docs/project/publication-report.md` | Human-readable evidence for the exact candidate commit. |

### Task 1: Create the clean private repository and import boundary

**Files:**
- Create: public repository root from the reviewed private snapshot
- Create: `.gitignore`
- Create: `docs/project/source-provenance.md`
- Exclude: `.git/`, `.venv/`, `node_modules/`, `dist/`, `.pytest_cache/`, `__pycache__/`, `.test-data-*`, `.verification-data/`

**Interfaces:**
- Consumes: approved design spec and the exact private source commit recorded during execution.
- Produces: private `ZeldrisMercy/glpi-workflow-assistant` repository, orphan clean history, and `release/public-beta` working branch.

- [ ] **Step 1: Record the source boundary before copying files**

Write `docs/project/source-provenance.md` with the private source repository name, exact source commit SHA, UTC extraction timestamp, excluded path classes and the statement that no private Git history was copied. Do not include a private clone URL or credentials.

- [ ] **Step 2: Create the destination repository privately**

Create `ZeldrisMercy/glpi-workflow-assistant` with visibility `private`, Issues enabled, no generated README/license/gitignore, and no Discussions yet. Verify the anonymous URL returns not-found while authenticated access succeeds.

- [ ] **Step 3: Initialize clean history and the release branch**

Initialize an empty repository with `main` as the default branch and create an empty root commit named `chore: initialize public repository`. Create `release/public-beta` from that commit, then import the reviewed snapshot with the exclusion list above. Use the current remote snapshot as the source of truth; do not reintroduce stale local-only workflow files.

- [ ] **Step 4: Verify the import boundary**

Run:

```bash
git log --oneline --all
git status --short
find . -type d \( -name .git -o -name node_modules -o -name __pycache__ -o -name .pytest_cache \) -prune -print
```

Expected: only new public-repository commits are present, the worktree is clean after commit, and no excluded dependency/cache directory is tracked.

- [ ] **Step 5: Commit the complete reviewed snapshot**

```bash
git add --all
git commit -m "chore: import reviewed source snapshot"
```

Expected: every imported file belongs to this single new-repository commit, and `git log --all` contains only the empty root plus public-preparation commits.

### Task 2: Make sanitization an executable release gate

**Files:**
- Create: `scripts/publication_policy.py`
- Create: `scripts/audit_publication.py`
- Create: `tests/test_publication_audit.py`
- Create: `docs/project/sanitization-policy.md`
- Modify: `.gitignore`
- Modify: `requirements-dev.txt`

**Interfaces:**
- Consumes: `scan_paths(paths: Sequence[Path], policy: PublicationPolicy) -> AuditReport` inputs from the repository and built artifacts.
- Produces: `PublicationPolicy`, `Finding(path: str, rule: str, excerpt_hash: str)`, `AuditReport(findings: tuple[Finding, ...])`, and CLI exit code `0` only when no blocking finding exists.

- [ ] **Step 1: Write failing normalization and archive tests**

Add tests named `test_blocks_identifier_casefolded`, `test_blocks_identifier_with_separators`, `test_scans_nested_text_in_zip`, `test_scans_debian_payload`, `test_allows_documentation_domains`, `test_ignores_generated_local_state`, and `test_report_never_echoes_secret_value`. Assert that blocked names include `meet tecnologia`, `verdanadesk` and `mglit`, matching is Unicode-normalized and case-insensitive, archives are inspected, `example.invalid` is allowed, and findings expose only a digest plus rule name.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m pytest tests/test_publication_audit.py -q`

Expected: FAIL because `scripts.publication_policy` and `scripts.audit_publication` do not exist.

- [ ] **Step 3: Implement the publication policy and scanner**

Implement:

```python
@dataclass(frozen=True)
class PublicationPolicy:
    blocked_identifiers: tuple[str, ...]
    secret_patterns: tuple[Pattern[str], ...]
    ignored_paths: tuple[str, ...]

def normalize_text(value: str) -> str: ...
def scan_paths(paths: Sequence[Path], policy: PublicationPolicy) -> AuditReport: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Scan UTF-8 text plus `.deb`, `.zip` and `.xpi` members without extracting outside a temporary directory. Detect credentials, private domains/IPs, email addresses, phone-like fixture values and blocked organizations; encode explicit allowlists only for standards-based example domains/addresses. Do not print matched secret contents.

- [ ] **Step 4: Replace known private identifiers and local state**

Replace `MGLIT` fixtures in `tests/test_proactive_contract.py` and `qa/test_proactive_ui.cjs` with a clearly synthetic organization such as `Aurora Labs (example)`. Review all fixtures, comments and docs for private names, domains, IPs, emails, phones, ticket IDs and logs. Add runtime/cache paths to `.gitignore`; remove tracked generated state rather than allowlisting it.

- [ ] **Step 5: Run focused tests and the tree audit**

Run:

```bash
python -m pytest tests/test_publication_audit.py -q
python scripts/audit_publication.py .
```

Expected: all publication-audit tests PASS and the audit reports zero blocking findings.

- [ ] **Step 6: Document the policy and commit**

Document what is blocked, what is intentionally allowed, archive coverage and false-positive handling in `docs/project/sanitization-policy.md`.

```bash
git add .gitignore requirements-dev.txt scripts/publication_policy.py scripts/audit_publication.py tests/test_publication_audit.py tests/test_proactive_contract.py qa/test_proactive_ui.cjs docs/project/sanitization-policy.md
git commit -m "security: enforce public repository sanitization"
```

### Task 3: Apply licensing, independent identity and public metadata

**Files:**
- Create: `LICENSE`
- Rewrite: `NOTICE.md`
- Remove: `LEGAL_AND_OWNERSHIP.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `SUPPORT.md`
- Modify: `CONTRIBUTING.md`
- Modify: `SECURITY.md`
- Modify: `package/DEBIAN/control`
- Modify: `.env.example`

**Interfaces:**
- Consumes: the approved AGPL-3.0-or-later choice and the independent/unofficial positioning.
- Produces: a repository whose original-code license, package metadata, support boundary and third-party attribution agree.

- [ ] **Step 1: Add release-contract assertions for legal metadata**

In `tests/test_release_contract.py`, add `test_agpl_license_is_present`, `test_notice_declares_independence`, `test_package_metadata_has_no_organization_identity`, and `test_support_document_promises_no_sla`. Assert the SPDX identity `AGPL-3.0-or-later`, author name `Ícaro de Souza Mariano`, independent/unofficial language, neutral Debian maintainer value, and absence of blocked identifiers.

- [ ] **Step 2: Run the legal metadata tests and confirm failure**

Run: `python -m pytest tests/test_release_contract.py -k 'license or notice or metadata or support' -q`

Expected: FAIL because the license and final public metadata are not present.

- [ ] **Step 3: Write the legal and community files**

Use the unmodified GNU AGPL v3 text in `LICENSE`. In `NOTICE.md`, identify the original author, state that the project is independent and unofficial, use GLPI/WAHA names only for interoperability, and point to `patches/WAHA_CORE_LICENSE` plus `patches/WAHA_FORK.md` for the separate patch boundary. Remove the obsolete publication-review document because its decisions are now resolved.

- [ ] **Step 4: Align package and contribution metadata**

Use a neutral project maintainer in `package/DEBIAN/control`; document beta support with no SLA in `SUPPORT.md`; add a proportional contributor covenant, Conventional Commits, short-lived branch rules and DCO-style authorship confirmation in `CONTRIBUTING.md`. Keep vulnerability reports out of public Issues in `SECURITY.md`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
python -m pytest tests/test_release_contract.py -k 'license or notice or metadata or support' -q
python scripts/audit_publication.py .
```

Expected: PASS with zero blocking findings.

```bash
git add LICENSE NOTICE.md CODE_OF_CONDUCT.md SUPPORT.md CONTRIBUTING.md SECURITY.md package/DEBIAN/control .env.example tests/test_release_contract.py
git rm LEGAL_AND_OWNERSHIP.md
git commit -m "docs: establish agpl project governance"
```

### Task 4: Establish a single beta version and release contract

**Files:**
- Create: `scripts/release_metadata.py`
- Create: `scripts/verify_release.py`
- Modify: `scripts/build_portfolio.py`
- Modify: `requirements-dev.txt`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `package/DEBIAN/control`
- Modify: `extension/manifest.json`
- Create: `docs/project/release-manifest.json`
- Create: `docs/project/validation-matrix.md`
- Modify: `tests/test_release_contract.py`

**Interfaces:**
- Consumes: `ReleaseMetadata(public_version="3.4.0-beta.1", debian_version="3.4.0~beta.1-1", bridge_version="2.4.0")`.
- Produces: deterministic `.deb`, Chromium `.zip`, unsigned Firefox development `.xpi`, `SHA256SUMS`, `package-manifest.json`, CycloneDX SBOM and validation results with matching versions.

- [ ] **Step 1: Write failing cross-file version tests**

Add `test_release_version_is_consistent`, `test_artifact_names_use_beta_version`, `test_two_builds_are_byte_identical`, `test_checksums_cover_every_release_artifact`, and `test_sbom_scope_is_explicit`. Assert exact public and Debian versions, exact artifact set, byte-identical rebuilds, one checksum per artifact, and an SBOM scope that excludes unaudited Docker OS/browser/WAHA transitive components.

- [ ] **Step 2: Run the release-contract tests and confirm failure**

Run: `python -m pytest tests/test_release_contract.py -k 'version or artifact or checksum or sbom or identical' -q`

Expected: FAIL on the existing RC4 constants and missing SBOM.

- [ ] **Step 3: Implement single-source release metadata**

Define immutable `ReleaseMetadata` and make the builder/verifier consume it. Set `public_version` to `3.4.0-beta.1`, Debian version to `3.4.0~beta.1-1`, and Browser Bridge to its verified current version. Update package, extension and Node metadata from the same contract; do not rename runtime paths solely for presentation.

- [ ] **Step 4: Generate and verify release evidence**

Generate a CycloneDX JSON SBOM for the Python and npm dependency scope, the package manifest, checksums and `docs/project/release-manifest.json` containing filenames, sizes and SHA-256 values. `scripts/verify_release.py` must reject missing, extra, renamed or mismatched artifacts.

- [ ] **Step 5: Preserve safety behavior in the release snapshot**

Run the existing approval invalidation, idempotency and uncertain-result suites explicitly:

```bash
python -m pytest tests/test_proactive_plan.py tests/test_proactive_execute.py tests/test_release_security.py tests/test_bridge_223_evidence_ack.py -q
```

Expected: PASS, including rejection of changed payloads after approval and no blind retry after uncertain writes.

- [ ] **Step 6: Run the focused build contract and commit**

Run:

```bash
python -m pytest tests/test_release_contract.py -q
python scripts/build_portfolio.py
python scripts/verify_release.py dist
```

Expected: PASS; the build reports `3.4.0-beta.1`, a byte-identical Debian rebuild and a complete verified artifact set.

```bash
git add scripts/release_metadata.py scripts/verify_release.py scripts/build_portfolio.py package.json package-lock.json package/DEBIAN/control extension/manifest.json docs/project/release-manifest.json docs/project/validation-matrix.md tests/test_release_contract.py
git commit -m "build: prepare reproducible beta release"
```

### Task 5: Build the independent visual system and bilingual entry point

**Files:**
- Create: `docs/assets/brand/mark.svg`
- Create: `docs/assets/brand/hero.svg`
- Create: `docs/assets/brand/architecture-overview.svg`
- Create: `docs/assets/brand/social-preview.svg`
- Create: `docs/assets/brand/social-preview.png`
- Rewrite: `README.md`
- Create: `README.pt-BR.md`
- Remove: `README.en.md`
- Create: `docs/project/brand-guidelines.md`
- Modify: `package/usr/lib/glpi-assistant/app/static/favicon.svg`
- Modify: `extension/icons/icon.svg`

**Interfaces:**
- Consumes: the approved graphite/near-black, electric blue/violet and verified-green visual language.
- Produces: accessible SVG sources, a 1280×640 social preview and equivalent English/Portuguese repository narratives.

- [ ] **Step 1: Add structural asset and README checks**

Extend `tests/test_release_contract.py` with `test_social_preview_dimensions`, `test_svg_assets_have_titles`, `test_readmes_link_each_other`, `test_readmes_name_beta_and_agpl`, and `test_readme_claims_match_release_manifest`. Assert 1280×640 PNG dimensions, SVG `<title>` elements, reciprocal language links, the independent/unofficial disclaimer and only evidence-backed test counts.

- [ ] **Step 2: Run the presentation contract and confirm failure**

Run: `python -m pytest tests/test_release_contract.py -k 'preview or svg or readme' -q`

Expected: FAIL because the final assets and README pair do not exist.

- [ ] **Step 3: Create the vector identity**

Create repository-native SVGs using graphite/near-black backgrounds, electric blue/violet accents, verified green only for confirmed states and monospaced technical labels. The hero should express prompt → structured draft → Dry Run → human approval → GLPI without corporate branding or exaggerated hacker motifs. Export `social-preview.png` at exactly 1280×640.

- [ ] **Step 4: Rewrite the complete bilingual READMEs**

Make English `README.md` the default and Portuguese `README.pt-BR.md` a full equivalent. Lead with the mark, one-line positioning, Beta/AGPL/Linux/Python/CI/test badges, compact workflow and links to quick start, architecture, security, gallery and alternate language. Follow with problem, real workflows, safety model, evidence, install path, project map, limitations and skills demonstrated.

- [ ] **Step 5: Validate mobile rendering, links and factual claims**

Render both READMEs at desktop and narrow width. Check that the hero remains legible, tables do not carry essential mobile-only meaning, alt text is factual, and every test/version claim is derived from `docs/project/release-manifest.json` or the latest validation output.

- [ ] **Step 6: Run checks and commit**

Run:

```bash
python -m pytest tests/test_release_contract.py -k 'preview or svg or readme' -q
python scripts/audit_publication.py README.md README.pt-BR.md docs/assets/brand
```

Expected: PASS with zero blocked identifiers.

```bash
git add README.md README.pt-BR.md docs/assets/brand docs/project/brand-guidelines.md package/usr/lib/glpi-assistant/app/static/favicon.svg extension/icons/icon.svg tests/test_release_contract.py
git rm README.en.md
git commit -m "docs: launch independent bilingual project identity"
```

### Task 6: Produce the real-UI evidence gallery and diagrams

**Files:**
- Modify: `scripts/capture_portfolio_screenshots.py`
- Create: `scripts/ocr_screenshots.py`
- Modify: `demo/screenshot-scenarios.json`
- Modify: `requirements-dev.txt`
- Create: `tests/test_screenshot_contract.py`
- Rewrite: `docs/assets/screenshots/README.md`
- Create/replace: `docs/assets/screenshots/01-central-queue.png`
- Create/replace: `docs/assets/screenshots/02-expanded-ticket.png`
- Create/replace: `docs/assets/screenshots/03-t01-t05-review.png`
- Create/replace: `docs/assets/screenshots/04-dry-run.png`
- Create/replace: `docs/assets/screenshots/05-proactive-batch.png`
- Create/replace: `docs/assets/screenshots/06-evidence-association.png`
- Create/replace: `docs/assets/screenshots/07-execution-receipt.png`
- Create/replace: `docs/assets/screenshots/08-messaging-status.png`
- Create: `docs/assets/screenshots/capture-report.json`
- Create: `docs/assets/screenshots/ocr-report.json`
- Create: `docs/architecture/system-overview.md`
- Create: `docs/architecture/trust-boundaries.md`
- Create: `docs/architecture/workflows.md`

**Interfaces:**
- Consumes: real application HTML/CSS/JavaScript and deterministic synthetic API fixtures.
- Produces: exactly eight 1440×1000 screenshots, capture metadata with `real_glpi_writes: 0`, OCR output, and six compact Mermaid diagrams.

- [ ] **Step 1: Write failing screenshot-boundary tests**

Add `test_gallery_has_eight_named_scenarios`, `test_all_scenarios_are_marked_synthetic`, `test_capture_blocks_non_loopback_requests`, `test_capture_report_records_zero_remote_writes`, `test_ocr_report_covers_every_png`, and `test_optional_messaging_caption_does_not_claim_delivery`. Stub an attempted HTTPS request and assert it is aborted and recorded, not fulfilled.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m pytest tests/test_screenshot_contract.py -q`

Expected: FAIL because only the partial gallery exists.

- [ ] **Step 3: Extend the deterministic capture harness**

Define one synthetic scenario per required view in `demo/screenshot-scenarios.json`. Capture the real UI at 1440×1000, use a fresh temporary data directory, intercept all `/api/` responses, abort every non-loopback request, record page/console errors, and label simulated receipts and messaging state honestly.

- [ ] **Step 4: Generate OCR evidence and block identity leaks**

Implement `ocr_screenshots(paths: Sequence[Path]) -> OcrReport`; write normalized text plus image hashes to `ocr-report.json`, then run it through the same blocked-identifier policy from Task 2. If OCR is unavailable, fail the publication gate instead of recording a pass.

- [ ] **Step 5: Capture and inspect all eight images**

Run:

```bash
python scripts/capture_portfolio_screenshots.py
python scripts/ocr_screenshots.py docs/assets/screenshots
python -m pytest tests/test_screenshot_contract.py -q
```

Expected: exactly eight PNGs, no page errors, no external requests, zero real writes and zero blocked OCR findings. Manually inspect every image for clipping, accidental browser chrome, private data, misleading status and consistent framing.

- [ ] **Step 6: Write architecture and workflow diagrams**

Use compact Mermaid diagrams for overall architecture, trust boundaries, existing-ticket closure, proactive creation, approval invalidation and optional WAHA integration. Mark local/remote boundaries, human approval, optional components and unverified live paths explicitly.

- [ ] **Step 7: Commit**

```bash
git add scripts/capture_portfolio_screenshots.py scripts/ocr_screenshots.py demo/screenshot-scenarios.json tests/test_screenshot_contract.py docs/assets/screenshots docs/architecture
git commit -m "docs: add reproducible synthetic evidence gallery"
```

### Task 7: Reorganize public documentation around user intent

**Files:**
- Create: `docs/getting-started/quick-start.md`
- Create: `docs/getting-started/debian-installation.md`
- Create: `docs/getting-started/browser-bridge.md`
- Create: `docs/security/security-model.md`
- Create: `docs/security/threat-model.md`
- Create: `docs/security/privacy.md`
- Create: `docs/project/case-study.md`
- Create: `docs/project/roadmap.md`
- Create: `docs/project/known-limitations.md`
- Create: `docs/project/release-process.md`
- Move/update: the exact legacy-to-public mappings listed in Step 3; keep `docs/adr/*.md` in place
- Remove: `docs/PROMPT_FORMALIZACAO_3.2.md`
- Remove: `docs/INSTALACAO_E_ROLLBACK.md`
- Remove: `docs/WHATSAPP_WAHA.md`

**Interfaces:**
- Consumes: validated behavior and claims from Tasks 2, 4 and 6.
- Produces: task-oriented docs with no stale RC3/RC4 claims, nonexistent paths or private-environment assumptions.

- [ ] **Step 1: Add documentation integrity checks**

Extend `tests/test_release_contract.py` with `test_required_public_docs_exist`, `test_docs_have_no_rc_or_obsolete_version_claims`, `test_case_study_links_real_evidence`, and `test_docs_do_not_reference_missing_paths`. Assert the exact public structure from the spec and reject links such as the current nonexistent `internal-audit/` reference.

- [ ] **Step 2: Run the docs contract and confirm failure**

Run: `python -m pytest tests/test_release_contract.py -k 'public_docs or obsolete or case_study or missing_paths' -q`

Expected: FAIL on stale or missing documentation.

- [ ] **Step 3: Build the task-oriented documentation tree**

Move and rewrite material by reader intent using this mapping:

| Current path | Public path |
|---|---|
| `docs/installation.md` | `docs/getting-started/quick-start.md` |
| `docs/debian-package.md` | `docs/getting-started/debian-installation.md` |
| `docs/browser-bridge.md` | `docs/getting-started/browser-bridge.md` |
| `docs/configuration.md` | `docs/getting-started/configuration.md` |
| `docs/compatibility.md` | `docs/getting-started/compatibility.md` |
| `docs/demo-data.md` | `docs/getting-started/demo-data.md` |
| `docs/troubleshooting.md` | `docs/getting-started/troubleshooting.md` |
| `docs/OPERACAO_E_RECUPERACAO.md` | `docs/getting-started/operations-and-recovery.md` |
| `docs/PROMPT_FORMALIZACAO_3.4.0-rc4.md` | `docs/getting-started/structured-input.md` |
| `docs/security-model.md` | `docs/security/security-model.md` |
| `docs/threat-model.md` | `docs/security/threat-model.md` |
| `docs/privacy-and-data.md` | `docs/security/privacy.md` |
| `docs/api-contract.md` | `docs/architecture/api-contract.md` |
| `docs/evidence-model.md` | `docs/architecture/evidence-model.md` |
| `docs/proactive-ticket-creation.md` | `docs/architecture/proactive-ticket-creation.md` |
| `docs/waha-integration.md` | `docs/architecture/waha-integration.md` |
| `docs/portfolio-case-study.md` | `docs/project/case-study.md` |
| `ROADMAP.md` | `docs/project/roadmap.md` |
| `docs/known-limitations.md` | `docs/project/known-limitations.md` |
| `docs/release-process.md` | `docs/project/release-process.md` |
| `docs/source-map.md` | `docs/project/source-map.md` |
| `docs/testing.md` | `docs/project/testing.md` |
| `docs/validation.md` | `docs/project/validation.md` |
| `docs/screenshot-strategy.md` | `docs/project/screenshot-methodology.md` |

Preserve useful ADRs at `docs/adr/`. Quick start must run the app with synthetic/local state before any real service connection. Debian installation must include effects, backup and rollback. Security docs must distinguish enforced controls, assumptions and roadmap items.

- [ ] **Step 4: Write the portfolio case study**

Structure `docs/project/case-study.md` as problem → constraints → design → review/approval → evidence → receipt → engineering proof → limitations. Add a concise skills-demonstrated section for Python/FastAPI, REST APIs, Linux/Debian, Docker, applied security, testing, CI/CD, human-in-the-loop automation, documentation and release engineering. Do not mention any employer or customer.

- [ ] **Step 5: Remove obsolete or misleading documents**

Delete superseded `docs/CHANGELOG_3.4.0-rc4.md`, `docs/INSTALACAO_E_ROLLBACK.md`, `docs/PROMPT_FORMALIZACAO_3.2.md`, `docs/SEGURANCA_ESTABILIDADE_3.4.0-rc4.md`, `docs/VALIDACAO_3.4.0-rc4.json`, `docs/WHATSAPP_WAHA.md`, `docs/publication-checklist.md` and `docs/release-draft.md` after merging any still-valid facts into the mapped documents. Repair every inbound link.

- [ ] **Step 6: Verify and commit**

Run:

```bash
python -m pytest tests/test_release_contract.py -k 'public_docs or obsolete or case_study or missing_paths' -q
python scripts/audit_publication.py docs
```

Expected: PASS; zero missing internal links and zero blocking findings.

```bash
git add README.md README.pt-BR.md docs tests/test_release_contract.py
git commit -m "docs: publish task-oriented technical documentation"
```

### Task 8: Add proportional governance and public CI

**Files:**
- Modify: `.github/ISSUE_TEMPLATE/bug_report.md`
- Modify: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/ISSUE_TEMPLATE/documentation.md`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Modify: `.github/pull_request_template.md`
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/codeql.yml`
- Rewrite: `.github/workflows/release.yml`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: audit, release verification and screenshot contracts from prior tasks.
- Produces: required CI gates, public CodeQL/Dependabot configuration, manual/tagged prerelease pipeline and contributor templates.

- [ ] **Step 1: Write workflow policy tests**

Extend `tests/test_release_contract.py` with `test_ci_invokes_every_release_gate`, `test_workflows_use_minimal_permissions`, `test_release_requires_beta_tag`, `test_codeql_covers_python_and_javascript`, and `test_dependabot_covers_pip_npm_actions`. Parse workflow YAML as data; do not assert fragile formatting.

- [ ] **Step 2: Run workflow tests and confirm failure**

Run: `python -m pytest tests/test_release_contract.py -k 'workflow or codeql or dependabot' -q`

Expected: FAIL because public-only automation is incomplete.

- [ ] **Step 3: Expand CI gates**

Make CI run Python regressions, JavaScript/DOM regressions, JavaScript syntax, publication audit, dependency audit, documentation link checks, deterministic build, release verification and SBOM validation. Pin action major versions, set least-privilege permissions, timeouts and concurrency cancellation.

- [ ] **Step 4: Configure public security automation**

Configure CodeQL for Python and JavaScript and monthly Dependabot updates for pip, npm and GitHub Actions. Keep these files committed while the repo is private; enable execution/settings after public visibility if GitHub plan restrictions require it.

- [ ] **Step 5: Define the prerelease workflow and templates**

Allow release build only for an exact `v3.4.0-beta.1` tag or explicit manual candidate input. Upload the Debian package, both bridge archives, hashes, manifest, SBOM, validation matrix and release notes. Templates must request reproducible steps, security impact, tests, evidence and confirmation that no private data was added.

- [ ] **Step 6: Verify and commit**

Run:

```bash
python -m pytest tests/test_release_contract.py -k 'workflow or codeql or dependabot' -q
python scripts/audit_publication.py .github
```

Expected: PASS with least-privilege workflow assertions satisfied.

```bash
git add .github tests/test_release_contract.py
git commit -m "ci: enforce public beta quality gates"
```

### Task 9: Validate the exact candidate and write the publication report

**Files:**
- Create: `docs/project/publication-report.md`
- Create: `docs/project/publication-report.json`
- Create: `docs/project/release-notes-v3.4.0-beta.1.md`
- Create: `docs/project/clean-host-installation.md`
- Create: `docs/project/linkedin-launch-kit.md`
- Update: `CHANGELOG.md`

**Interfaces:**
- Consumes: exact candidate commit, generated artifacts, scan results, OCR report and clean-host result.
- Produces: immutable evidence table tying checks and SHA-256 hashes to the candidate commit; no visibility change.

- [ ] **Step 1: Run the full regression suite from a clean checkout**

Run:

```bash
python -m pip install -r package/usr/lib/glpi-assistant/app/requirements.txt -r requirements-dev.txt
npm ci
GLPI_ASSISTANT_DATA="$(mktemp -d)" python -m pytest tests qa/test_waha_installer.py -q
python scripts/check_javascript.py
```

Expected: all tests and syntax checks PASS. Record actual counts; never copy historical counts into the report.

- [ ] **Step 2: Build and inspect the final artifacts**

Run:

```bash
python scripts/build_portfolio.py
python scripts/verify_release.py dist
python scripts/audit_publication.py . dist
cd dist && sha256sum --check SHA256SUMS
```

Expected: byte-identical build, complete manifest/SBOM, valid hashes and zero blocking findings. Inspect `dpkg-deb --contents` and every ZIP/XPI member list, then scan their extracted contents.

- [ ] **Step 3: Reproduce screenshots and perform the manual review**

Regenerate all eight images and OCR report. Record reviewer, UTC timestamp, image hashes and pass/fail for identity, clipping, factual status and synthetic-data notice. Any failed image blocks the candidate.

- [ ] **Step 4: Perform the clean-host acceptance test**

Install the Debian artifact in a disposable, supported Linux environment; verify install, loopback health, synthetic workflow, backup and rollback/uninstall. Record environment image/version and exact results in `docs/project/clean-host-installation.md`. A failure is documented as a beta limitation and blocks claims of successful clean-host installation, but does not convert the project into production-ready software.

- [ ] **Step 5: Write candidate-bound release evidence**

Create JSON and Markdown reports with candidate SHA, commands, actual test counts, artifact hashes, dependency-audit result, link-check result, OCR/manual review, license review, clean-host status, known limitations and the explicit statement `visibility_change_authorized: false`.

- [ ] **Step 6: Prepare the LinkedIn launch kit without publishing it**

Write `docs/project/linkedin-launch-kit.md` in Portuguese with a concise launch post, a shorter portfolio description, the verified skills list, the social-preview/architecture asset paths and the four-frame problem → review → approval → receipt sequence. Use placeholders for the future public repository and release URLs; do not publish externally during this task.

- [ ] **Step 7: Self-audit the final tracked tree**

Run:

```bash
git ls-files -z | xargs -0 python scripts/audit_publication.py
git status --short
git log --oneline --decorate --all
```

Expected: no findings, only reviewed files tracked, no private history, and only intentional report changes uncommitted.

- [ ] **Step 8: Commit**

```bash
git add CHANGELOG.md docs/project/publication-report.md docs/project/publication-report.json docs/project/release-notes-v3.4.0-beta.1.md docs/project/clean-host-installation.md docs/project/linkedin-launch-kit.md
git commit -m "release: validate v3.4.0 beta candidate"
```

### Task 10: Review, merge and stage the private prerelease

**Files:**
- Modify only if review finds defects: files owned by Tasks 1–9
- GitHub settings: branch protection, merge policy, Issues, Discussions, security settings and social preview

**Interfaces:**
- Consumes: green `release/public-beta` candidate and publication report.
- Produces: protected `main`, private `v3.4.0-beta.1` prerelease draft/assets and a final owner-review packet.

- [ ] **Step 1: Push the release branch and open the review PR**

Open `release/public-beta` → `main` with links to the spec, plan, publication report, CI run, screenshot/OCR evidence, artifact manifest and clean-host record. Keep the repository private.

- [ ] **Step 2: Review the PR by risk area**

Review legal/identity, application safety, repository history, artifacts, images, documentation claims and workflow permissions separately. Resolve each finding with a focused commit and rerun the owning task's tests plus the full CI.

- [ ] **Step 3: Merge and protect `main`**

After all required checks pass, squash merge. Protect `main` with required PR and CI checks, disallow force pushes/deletion and prefer squash merging. Do not require an impossible second maintainer approval for the single-maintainer beta.

- [ ] **Step 4: Configure public-facing repository metadata while still private**

Set description, topics, homepage if one exists, social preview, Issues and Discussions. Enable secret scanning/push protection where the account permits. Keep repository visibility private.

- [ ] **Step 5: Build the exact tag candidate without publishing visibility**

Create the signed or annotated `v3.4.0-beta.1` tag on the reviewed `main` commit and produce a prerelease draft with all required assets. Verify the tag commit equals the publication-report commit and every uploaded hash matches.

- [ ] **Step 6: Present the final owner-review packet**

Provide the authenticated repository/PR/release-draft links, candidate SHA, green checks, remaining limitations, anonymous-view status, exact visibility action still pending and a concise LinkedIn draft. Stop here until the owner explicitly authorizes public visibility.

- [ ] **Step 7: Commit any final metadata-only corrections**

If corrections are necessary, repeat Task 9 and update/recreate the candidate tag before asking for approval. Never move a published tag silently.

### Task 11: Execute the explicit publication gate

**Files:**
- Modify: `docs/project/publication-report.json` only through a new post-publication evidence commit if needed
- GitHub settings: repository visibility and public security features

**Interfaces:**
- Consumes: explicit owner confirmation naming `ZeldrisMercy/glpi-workflow-assistant` and `v3.4.0-beta.1` after review of the final packet.
- Produces: public repository, published prerelease, verified anonymous view and LinkedIn-ready public URLs.

- [ ] **Step 1: Obtain explicit final confirmation**

Ask one unambiguous question immediately before the visibility change. Proceed only if the owner confirms making `ZeldrisMercy/glpi-workflow-assistant` public at the reviewed candidate SHA. Earlier approval of the design or this plan does not satisfy this gate.

- [ ] **Step 2: Change visibility and verify anonymously**

Set repository visibility to public. In an unauthenticated view, verify README assets, alternate language, docs, Issues/Discussions, license detection, social preview, branch protection indicators and absence of private-only links.

- [ ] **Step 3: Enable public-only security features**

Confirm CodeQL, Dependabot alerts/updates, secret scanning and push protection are active where available. Trigger required workflows and wait for green results on public `main`.

- [ ] **Step 4: Publish the prerelease**

Publish `v3.4.0-beta.1` as a GitHub prerelease, not a stable release. Re-download every asset anonymously, verify `SHA256SUMS`, and confirm the unsigned Firefox development XPI and SBOM scope are clearly labeled.

- [ ] **Step 5: Record post-publication evidence**

Record the public URL, release URL, public CI run, anonymous verification timestamp and any GitHub security-feature limitations. If the report changes, use a new `docs:` commit and do not rewrite the release tag.

- [ ] **Step 6: Deliver the LinkedIn package**

Provide the final Portuguese LinkedIn post, social preview, architecture visual and a short evidence sequence linking problem → review → approval → receipt. Keep every claim within the verified publication report.

---

## Final Acceptance Checklist

- [ ] The destination history contains no private-repository commits.
- [ ] Full Python and JavaScript suites pass on the exact tagged snapshot.
- [ ] The release build is deterministic and all artifacts verify against published SHA-256 hashes.
- [ ] Tree, archive and OCR audits report zero blocked identities or secrets.
- [ ] Eight real-UI screenshots use synthetic fixtures and record zero real writes/external requests.
- [ ] English and Portuguese READMEs are complete, factual and visually reviewed on desktop/mobile.
- [ ] AGPL-3.0-or-later, third-party notices and WAHA patch boundaries are clear.
- [ ] No employer, customer or unrelated legal entity is named or implied.
- [ ] The clean-host result and known limitations are stated without production-readiness claims.
- [ ] `main` is protected and CI is required before merge.
- [ ] The owner gives fresh, explicit confirmation immediately before public visibility.
- [ ] Anonymous repository and release views are verified after publication.
