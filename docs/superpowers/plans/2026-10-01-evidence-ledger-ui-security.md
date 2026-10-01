# Evidence Ledger, Runtime UI Parity and Security Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably preserve, transport, classify and review first-prompt images while aligning the real UI with the documented visual system and retaining the local-first security model.

**Architecture:** The Browser Bridge creates a prompt-scoped manifest and sends it through an idempotent local capture outbox before the model response exists. The Assistant stores unclassified attachments separately from closure handoffs, validates bytes and digests, then resolves model-provided associations against the immutable manifest during review. Runtime CSS, not screenshot-only overrides, provides the visual system.

**Tech Stack:** Python 3.12, FastAPI, local SQLite/meta store, vanilla JavaScript WebExtension, HTML/CSS, pytest, Node/jsdom, Playwright screenshot harness, CodeQL, pip-audit and npm audit.

**Spec:** `docs/superpowers/specs/2026-10-01-evidence-ledger-ui-security-design.md`

## Global Constraints

- Keep Assistant and WAHA loopback-only; do not activate the experimental WAHA fork.
- Preserve human review, Dry Run, payload binding, approval invalidation and no blind retry for remote GLPI or WhatsApp writes.
- Accept only PNG, JPEG and WebP after signature verification; enforce 8 MiB/file, 20 MiB/prompt and 30 attachments/prompt.
- Treat browser DOM, filenames, media type, LLM output and every attachment byte as untrusted input.
- Use server-generated opaque IDs and storage paths; never accept local paths, remote URLs or redirects for evidence.
- Preserve existing `EVIDENCIA_ANEXO`, `EVIDENCIA_ARQUIVO`, manual upload and proactive `source_index` behavior as compatibility fallbacks.
- Context never becomes GLPI evidence automatically; ambiguity remains visible and unlinked.
- Screenshots use synthetic offline fixtures and real runtime CSS only; no capture-only layout override or receipt mutation.
- Do not package a `.deb` until the operator explicitly requests a release build.
- Add PT-BR user-visible copy and patch notes explaining what changed and why.

## Review Focus

- A first prompt that creates a new provider conversation while its file input disappears must retain the original bytes under one prompt ID.
- The same digest replayed under a new attachment UUID or the same UUID reused with altered bytes must be rejected or deduplicated without changing an existing draft.
- A model response that names a ticket or E-ID not belonging to the prompt must leave the attachment unresolved instead of crossing ticket boundaries.
- Partial local acknowledgement and a browser restart must preserve only pending bytes and never resend acknowledged bytes.
- A malicious image name, MIME label, oversized body, URL-like input or cross-origin request must not create a file, fetch a URL or bypass the local boundary.

---

## File Structure

| File | Responsibility |
|---|---|
| `package/usr/lib/glpi-assistant/app/evidence_manifest.py` | Pure manifest validation, digest identity, lifecycle state transitions and safe persisted metadata. |
| `package/usr/lib/glpi-assistant/app/evidence_bridge.py` | Signature validation and content-addressed image storage used by both legacy handoffs and manifests. |
| `package/usr/lib/glpi-assistant/app/main.py` | Authenticated capture endpoints, closure association validation, Dry Run binding and inbox projection. |
| `package/usr/lib/glpi-assistant/app/local_security.py` | Explicit Bridge allowlist and bounded-body policy for the new capture routes. |
| `package/usr/lib/glpi-assistant/app/static/closure-queue.js` | Review surface for unclassified prompt attachments and explicit mapping. |
| `package/usr/lib/glpi-assistant/app/static/workspace.css` | Shared runtime design tokens and responsive review layout. |
| `extension/capture.js` | Prompt-scoped capture state, immutable attachment ordinals and compact attachment control. |
| `extension/background.js` | Persistent capture outbox, local idempotent retry and per-attachment acknowledgement cleanup. |
| `extension/content.js` | Model association extraction, manifest-aware handoff and non-blocking status display. |
| `extension/evidence-plan.js` | Pure validation of source-index/legacy mapping without auto-promoting context. |
| `extension/popup.css` | Compact extension status visual treatment. |
| `scripts/capture_portfolio_screenshots.py` | Runtime-faithful screenshot capture without product CSS mutation. |
| `docs/security/*`, `SECURITY.md`, `docs/project/*` | Security links, limitations, test record and patch notes. |

### Task 1: Prompt-Scoped Manifest Domain Model

**Files:**
- Create: `package/usr/lib/glpi-assistant/app/evidence_manifest.py`
- Modify: `package/usr/lib/glpi-assistant/app/evidence_bridge.py`
- Test: `tests/test_evidence_manifest.py`

**Interfaces:**
- Produces: `validate_capture_manifest(payload: dict) -> dict`, `store_capture_manifest(manifest: dict, attachments: list[dict]) -> dict`, `acknowledge_capture_attachment(prompt_id: str, attachment_id: str, digest: str) -> dict`, `resolve_manifest_associations(prompt_id: str, associations: list[dict]) -> dict`.
- Consumes: `evidence_bridge.image_type`, `store.DATA_DIR`, `get_meta`, `set_meta`, `list_meta_prefix`.
- Later tasks use prompt IDs, attachment UUIDs, digests, ordinals and lifecycle states produced here.

- [ ] **Step 1: Write failing manifest lifecycle tests**

```python
def test_prompt_manifest_preserves_capture_order_and_rejects_uuid_digest_reuse():
    stored = store_capture_manifest(valid_manifest(), valid_attachments())
    assert [item['ordinal'] for item in stored['attachments']] == [1, 2]
    with pytest.raises(HTTPException, match='digest diferente'):
        store_capture_manifest(reused_uuid_manifest(), altered_attachment())
```

Add separate tests for `context`, `evidence`, `unresolved`, `rejected`, digest de-duplication, 30/8 MiB/20 MiB limits and retention expiry.

- [ ] **Step 2: Run the new manifest tests to verify they fail**

Run: `python -m pytest tests/test_evidence_manifest.py -q`

Expected: FAIL because `evidence_manifest` does not exist.

- [ ] **Step 3: Implement immutable manifest storage and lifecycle helpers**

Implement the declared functions in `evidence_manifest.py`. Store content-addressed files through `evidence_bridge`; persist only opaque IDs, safe generated filenames, detected media type, digest, ordinal and state. Use `captured -> queued -> received -> classified -> linked` and never transition `context` to `evidence` implicitly.

- [ ] **Step 4: Run the manifest tests to verify they pass**

Run: `python -m pytest tests/test_evidence_manifest.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the manifest domain model**

```bash
git add package/usr/lib/glpi-assistant/app/evidence_manifest.py package/usr/lib/glpi-assistant/app/evidence_bridge.py tests/test_evidence_manifest.py
git commit -m "feat: add prompt scoped evidence manifests"
```

### Task 2: Secure Local Capture API and Inbox Projection

**Files:**
- Modify: `package/usr/lib/glpi-assistant/app/main.py`
- Modify: `package/usr/lib/glpi-assistant/app/local_security.py`
- Modify: `package/usr/lib/glpi-assistant/app/evidence_bridge.py`
- Test: `tests/test_workbench.py`
- Test: `tests/test_release_security.py`

**Interfaces:**
- Consumes: Task 1 manifest functions.
- Produces: `POST /api/bridge/captures`, `GET /api/bridge/captures/{prompt_id}`, `POST /api/bridge/captures/{prompt_id}/ack`, and a prompt attachment section in `/api/bridge/inbox`.
- Later tasks use the acknowledgement response `{prompt_id, attachment_id, digest, state}` and the inbox attachment metadata.

- [ ] **Step 1: Write failing API and boundary tests**

```python
def test_pairing_token_can_store_capture_then_read_only_its_manifest(client, headers):
    created = client.post('/api/bridge/captures', headers=headers, json=capture_payload())
    assert created.status_code == 200
    assert client.get('/api/bridge/captures/' + created.json()['prompt_id'], headers=headers).status_code == 200

def test_capture_api_rejects_cross_origin_url_and_path_like_attachment(client, headers):
    assert client.post('/api/bridge/captures', headers=headers, json=unsafe_capture_payload()).status_code in (400, 403)
```

Add tests that unauthenticated or extension-origin administrative calls fail, malformed/oversized bodies fail before parsing, image serving uses `no-store` and `nosniff`, and context is absent from legacy handoff images.

- [ ] **Step 2: Run the focused API tests to verify they fail**

Run: `python -m pytest tests/test_workbench.py -k 'capture_api or capture_manifest' tests/test_release_security.py -q`

Expected: FAIL because the capture routes do not exist.

- [ ] **Step 3: Add authenticated capture routes and explicit boundary limits**

Use `_require_bridge_auth`, add only the new capture paths to `BRIDGE_PATHS`, and enforce a capture-specific bounded-body limit. Return per-attachment acknowledgements only after digest verification and durable persistence. Do not expose raw bytes, filesystem paths, other prompts or administrative controls to extension origins.

- [ ] **Step 4: Bind legacy handoff association to a manifest when supplied**

Extend the handoff payload with optional `prompt_id` and associations. Validate that every source belongs to that prompt, every E-ID is expected by its closure, and every ticket ID agrees with the packet. Keep the current legacy image payload path unchanged when no manifest is present.

- [ ] **Step 5: Run security and workbench regressions**

Run: `python -m pytest tests/test_workbench.py tests/test_release_security.py -q`

Expected: PASS, including existing local-boundary and partial-ACK tests.

- [ ] **Step 6: Commit the capture API**

```bash
git add package/usr/lib/glpi-assistant/app/main.py package/usr/lib/glpi-assistant/app/local_security.py package/usr/lib/glpi-assistant/app/evidence_bridge.py tests/test_workbench.py tests/test_release_security.py
git commit -m "feat: add authenticated capture inbox"
```

### Task 3: Bridge Prompt Snapshot and Capture Outbox

**Files:**
- Modify: `extension/capture.js`
- Modify: `extension/background.js`
- Test: `tests/test_capture_race.js`
- Test: `tests/test_bridge_partial_ack.js`
- Test: `qa/test_capture_early.cjs`

**Interfaces:**
- Consumes: Task 2 `POST /api/bridge/captures` acknowledgement contract.
- Produces: `glpiCapture.snapshotForPrompt() -> {prompt_id, attachments, prompt_timestamp}` and background messages `bridge:capture:enqueue` / `bridge:capture:flush`.
- Later tasks use manifest attachment IDs and source ordinals rather than hidden `Axx` labels.

- [ ] **Step 1: Write failing Bridge tests for ordinary first-prompt images**

```javascript
const snapshot = await context.glpiCapture.snapshotForPrompt();
assert.equal(snapshot.attachments[0].ordinal, 1);
assert.equal(snapshot.attachments[0].state, 'queued');
assert.notEqual(snapshot.attachments[0].id, 'auto');
```

Add cases for an ordinary `Screenshot 2026-10-01.png`, Enter submission, button submission, input removal, same-tab conversation creation, rapid consecutive prompts, partial ACK and restart recovery.

- [ ] **Step 2: Run the Browser capture tests to verify they fail**

Run: `node tests/test_capture_race.js && node tests/test_bridge_partial_ack.js && JSDOM_PATH="$JSDOM_PATH" node qa/test_capture_early.cjs`

Expected: FAIL because prompt manifests and capture acknowledgements are absent.

- [ ] **Step 3: Implement prompt-scoped capture snapshots**

Replace the shared implicit capture state with a prompt ID, immutable snapshot and UUID/digest metadata. Preserve route migration only for the documented same-origin new-conversation window. Keep original file capture, paste, drop, detached input and thumbnail recovery; do not set `suppressRecovery` merely because an unresolved image exists.

- [ ] **Step 4: Implement a distinct persistent capture outbox**

Store manifest packets apart from closure handoffs. Retry only failed local capture transport with the same prompt/attachment/digest key. Remove an attachment only when the Assistant acknowledges the exact UUID and digest; retain pending files across extension restart and report compact state to content scripts.

- [ ] **Step 5: Run all Bridge regressions**

Run: `python scripts/check_javascript.py && node tests/test_capture_race.js && node tests/test_bridge_partial_ack.js && JSDOM_PATH="$JSDOM_PATH" node qa/test_capture_early.cjs`

Expected: PASS; the old explicit-name cases and the new ordinary-name first-prompt case both pass.

- [ ] **Step 6: Commit Bridge capture transport**

```bash
git add extension/capture.js extension/background.js tests/test_capture_race.js tests/test_bridge_partial_ack.js qa/test_capture_early.cjs
git commit -m "feat: persist first prompt capture manifests"
```

### Task 4: Conservative Model Association and Multi-Ticket Review

**Files:**
- Modify: `extension/evidence-plan.js`
- Modify: `extension/content.js`
- Modify: `package/usr/lib/glpi-assistant/app/static/closure-queue.js`
- Modify: `package/usr/lib/glpi-assistant/app/static/workbench.js`
- Test: `tests/test_bridge_evidence_plan.js`
- Test: `qa/test_handoff_repeat.cjs`
- Test: `qa/test_queue_evidence.cjs`
- Test: `tests/test_workbench.py`

**Interfaces:**
- Consumes: Task 3 `prompt_id`, attachment UUID and ordinal; Task 2 manifest association validation.
- Produces: `GLPiEvidencePlan.resolveManifest(requiredIds, attachments, claims) -> {assignments, unresolved, issues}` and explicit review payloads for ticket/task/E-ID/context.
- Later UI task consumes attachment state and review actions, not raw base64 data.

- [ ] **Step 1: Write failing association tests**

```javascript
const result = resolveManifest(['E01'], attachmentsForPrompt, [{source_index: 1, ticket_id: 42, evidence_id: 'E01'}]);
assert.deepEqual(result.assignments.map(x => x.attachment_id), ['attachment-1']);
assert.equal(result.unresolved.length, 0);
```

Add failures for a source index out of range, one attachment claimed by two tickets, duplicate E-ID, context claim, mismatched ticket, legacy `EVIDENCIA_ANEXO`, legacy filename fallback and a response with no mapping.

- [ ] **Step 2: Run association tests to verify they fail**

Run: `node tests/test_bridge_evidence_plan.js && JSDOM_PATH="$JSDOM_PATH" node qa/test_queue_evidence.cjs`

Expected: FAIL because manifest association is not implemented.

- [ ] **Step 3: Implement association only against the prompt manifest**

Accept `source_index` when it resolves to an attachment from the same prompt. Keep existing explicit marker support, but remove any path that turns an `auto` or `context` file into evidence solely because file counts match. Leave unresolved images in the prompt inbox and allow closure text to continue.

- [ ] **Step 4: Add review controls that modify classification before Dry Run**

Show ordered prompt thumbnails with `Contexto`, `Evidência`, ticket and task/E-ID selectors. The user can explicitly discard or link an image. Every changed association updates the manifest state and makes stale preview/plan data invalid.

- [ ] **Step 5: Run client/server association regressions**

Run: `node tests/test_bridge_evidence_plan.js && JSDOM_PATH="$JSDOM_PATH" node qa/test_handoff_repeat.cjs && JSDOM_PATH="$JSDOM_PATH" node qa/test_queue_evidence.cjs && python -m pytest tests/test_workbench.py -k 'bridge or evidence' -q`

Expected: PASS; a multi-ticket ambiguity remains visible and produces no GLPI evidence upload.

- [ ] **Step 6: Commit association and review semantics**

```bash
git add extension/evidence-plan.js extension/content.js package/usr/lib/glpi-assistant/app/static/closure-queue.js package/usr/lib/glpi-assistant/app/static/workbench.js tests/test_bridge_evidence_plan.js qa/test_handoff_repeat.cjs qa/test_queue_evidence.cjs tests/test_workbench.py
git commit -m "feat: associate prompt evidence conservatively"
```

### Task 5: Approval Binding, Retention and Reconciliation

**Files:**
- Modify: `package/usr/lib/glpi-assistant/app/main.py`
- Modify: `package/usr/lib/glpi-assistant/app/evidence_manifest.py`
- Modify: `extension/background.js`
- Test: `tests/test_workbench.py`
- Test: `tests/test_evidence_manifest.py`

**Interfaces:**
- Consumes: Tasks 1-4 manifest state and resolved attachment digest list.
- Produces: a plan record that includes `manifest_hash`, and a retention/reconciliation response with exact pending and linked attachment counts.

- [ ] **Step 1: Write failing approval-invalidation and cleanup tests**

```python
def test_dry_run_is_invalid_after_linked_attachment_digest_changes(client):
    plan = create_plan_with_manifest(client)
    replace_linked_attachment(client, plan['prompt_id'])
    assert execute_plan(client, plan).status_code == 409
```

Add a test that context attachment changes do not create an evidence upload, expired unacknowledged items stay until warning/expiry policy is met, and completed ticket reconciliation does not resurrect an old capture.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_evidence_manifest.py tests/test_workbench.py -k 'manifest or approval or completed_packets' -q`

Expected: FAIL because plan records do not bind a manifest hash.

- [ ] **Step 3: Bind plans to resolved evidence manifest state**

Hash the ordered linked attachment UUID/digest/ticket/task/E-ID set at Dry Run. Compare it immediately before execution alongside the existing text and evidence-map hash. Preserve one-time plan consumption and live ticket rechecks.

- [ ] **Step 4: Implement conservative retention and reconciliation**

Keep acknowledged attachments only as metadata needed for audit; clean bytes after confirmed link or configured expiry. Never delete a queued/unacknowledged item because a closure text ACK arrived. Do not retry uncertain GLPI or WAHA writes.

- [ ] **Step 5: Run security-sensitive regression suite**

Run: `python -m pytest tests/test_evidence_manifest.py tests/test_workbench.py tests/test_release_security.py -q`

Expected: PASS, including one-use plan and completed-packet protection.

- [ ] **Step 6: Commit approval and retention work**

```bash
git add package/usr/lib/glpi-assistant/app/main.py package/usr/lib/glpi-assistant/app/evidence_manifest.py extension/background.js tests/test_evidence_manifest.py tests/test_workbench.py
git commit -m "security: bind evidence manifests to approval"
```

### Task 6: Runtime Design System and Compact Bridge UI

**Files:**
- Modify: `package/usr/lib/glpi-assistant/app/static/workspace.css`
- Modify: `package/usr/lib/glpi-assistant/app/static/closure-queue.css`
- Modify: `package/usr/lib/glpi-assistant/app/static/workbench.css`
- Modify: `extension/capture.js`
- Modify: `extension/popup.css`
- Test: `qa/test_form_layout.cjs`
- Test: `qa/test_whatsapp_controls.cjs`
- Create: `qa/test_evidence_ledger_layout.cjs`

**Interfaces:**
- Consumes: Task 4 review DOM attributes and Task 3 compact capture status.
- Produces: shared runtime token variables and deterministic responsive layout selectors used by screenshot capture.

- [ ] **Step 1: Write failing visual contract tests**

```javascript
assert.equal(css('.bridge-capture-chip').position, 'fixed');
assert.notEqual(css('.bridge-capture-chip').width, '330px');
assert.equal(css('.evidence-ledger-list').gridTemplateColumns.includes('minmax'), true);
```

Test full, split and narrow viewports; focus-visible, reduced-motion, no horizontal overflow, compact chip non-overlap with the composer, semantic success/warning/error color states and readable ticket titles.

- [ ] **Step 2: Run the visual contract tests to verify they fail**

Run: `JSDOM_PATH="$JSDOM_PATH" node qa/test_evidence_ledger_layout.cjs && JSDOM_PATH="$JSDOM_PATH" node qa/test_form_layout.cjs`

Expected: FAIL because the runtime token and compact-chip selectors do not exist.

- [ ] **Step 3: Consolidate runtime tokens and control hierarchy**

Define a small shared token set for neutral surface, white text, blue/purple primary hierarchy, red destructive/error, amber pending and green confirmed. Normalize button variants, control heights, focus rings, gaps and card radius without changing operational actions or introducing decorative gradients.

- [ ] **Step 4: Implement responsive evidence review and compact Bridge control**

Replace the always-wide overlay with a count/status chip that expands on demand. Use adaptive grid/list behavior for prompt attachments and task review. Ensure the sidebar becomes scrollable navigation and content keeps usable width in split and narrow windows.

- [ ] **Step 5: Run UI regressions**

Run: `JSDOM_PATH="$JSDOM_PATH" node qa/test_evidence_ledger_layout.cjs && JSDOM_PATH="$JSDOM_PATH" node qa/test_form_layout.cjs && JSDOM_PATH="$JSDOM_PATH" node qa/test_whatsapp_controls.cjs`

Expected: PASS with no existing selector regressions.

- [ ] **Step 6: Commit runtime visual parity**

```bash
git add package/usr/lib/glpi-assistant/app/static/workspace.css package/usr/lib/glpi-assistant/app/static/closure-queue.css package/usr/lib/glpi-assistant/app/static/workbench.css extension/capture.js extension/popup.css qa/test_evidence_ledger_layout.cjs qa/test_form_layout.cjs qa/test_whatsapp_controls.cjs
git commit -m "feat: align runtime evidence UI with design system"
```

### Task 7: Screenshot Fidelity, Documentation and Security Gates

**Files:**
- Modify: `scripts/capture_portfolio_screenshots.py`
- Modify: `SECURITY.md`
- Modify: `docs/security/security-model.md`
- Modify: `docs/security/threat-model.md`
- Modify: `docs/project/known-limitations.md`
- Modify: `docs/project/testing.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_release_contract.py`
- Test: `tests/test_release_security.py`

**Interfaces:**
- Consumes: Tasks 1-6 real runtime UI and security behavior.
- Produces: faithful synthetic screenshots, correct security navigation and release-ready test documentation. No package artifact is created in this task.

- [ ] **Step 1: Write failing documentation and screenshot integrity tests**

```python
def test_security_policy_links_resolve_and_screenshot_harness_has_no_runtime_css_injection():
    assert all(link_exists(link) for link in security_links())
    assert 'portfolio-task-focus' not in capture_script_text()
```

Add assertions that receipt state comes from fixture/API data rather than DOM text replacement, and the gallery includes a real unresolved-to-linked evidence state.

- [ ] **Step 2: Run release-contract tests to verify they fail**

Run: `python -m pytest tests/test_release_contract.py tests/test_release_security.py -q`

Expected: FAIL because the legacy capture-only override and broken `SECURITY.md` links remain.

- [ ] **Step 3: Remove capture-only product styling and document verified limits**

Capture screenshots with the same runtime CSS loaded by the app. Fix `SECURITY.md` links to `docs/security/*`; update threat model, limitations and testing matrix with manifest, retention and clean-host/live-acceptance boundaries. Add patch notes explaining the first-prompt evidence fix and its security rationale.

- [ ] **Step 4: Review GitHub security maintenance inputs without blind merges**

Confirm the current CI and CodeQL runs for the implementation commit, inspect Dependabot updates for `pip-audit`, `actions/setup-node` and CodeQL Action, and preserve immutable action SHA pinning. Record compatibility results; do not merge a major dependency update without passing the same suite.

- [ ] **Step 5: Run complete verification and synthetic screenshot capture**

Run: `python -m pytest tests qa/test_waha_installer.py -q && python scripts/check_javascript.py && python scripts/audit_publication.py . && python scripts/capture_portfolio_screenshots.py && python scripts/build_portfolio.py && python scripts/verify_release.py dist && python scripts/audit_publication.py dist`

Expected: all tests pass; screenshot capture makes no external request, audit has no blocking findings, and deterministic release verification passes. Do not describe Debian/Docker/WAHA live acceptance as complete unless it is actually run on an authorized disposable host.

- [ ] **Step 6: Commit documentation and release gates**

```bash
git add scripts/capture_portfolio_screenshots.py SECURITY.md docs/security docs/project CHANGELOG.md tests/test_release_contract.py tests/test_release_security.py
git commit -m "docs: document evidence ledger security controls"
```

## Plan Self-Review

- Spec coverage: Tasks 1-5 implement prompt-scoped capture, storage, association, Dry Run binding, retention and failure recovery. Task 6 makes runtime UI match the design direction. Task 7 handles screenshot fidelity, security documentation, GitHub maintenance checks and final verification.
- Step scan: each task has an explicit failing-test, fail verification, minimal implementation, pass verification and commit sequence. The code signatures and payload names are defined by their producing tasks.
- Type consistency: prompt IDs, attachment UUIDs, digest, ordinal, lifecycle state, `source_index` and association fields have one producer/consumer chain across Tasks 1-5.
- Review Focus coverage: first-prompt creation and rapid prompts are Task 3; replay/digest identity is Task 1; cross-ticket association is Task 4; partial ACK/restart is Task 3; hostile inputs and cross-origin behavior are Task 2.
- Proportion: the plan describes contracts and checks rather than implementation bodies. Each task can be reviewed and tested independently.
