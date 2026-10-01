# Evidence Ledger, Runtime UI Parity and Security Refinement

Date: 2026-10-01

Status: proposed for implementation review

## Intent

Make the first-prompt image flow reliable without weakening the distinction
between context and evidence, bring the runtime interface up to the visual
quality shown in the project screenshots, and carry the relevant security
findings from the public GitHub review into the next beta.

Success means that an image attached while the operator is composing the first
prompt is durably received by the local Assistant, remains ordered and scoped
to that prompt, can be associated with the correct ticket and task, and is
never silently discarded or promoted from context to evidence. The operator
must see compact, useful state instead of a large overlay. The application must
retain its local-first, human-approved and no-blind-retry safety model.

## Current failure and root cause

Bridge 2.4.0 captures image bytes early and assigns local references such as
`A01`, but delivery still depends on semantic information found later in the
assistant response. Newly captured files use `id: auto` without an evidence
role. The evidence planner only performs ordered assignment for files already
marked with `role: evidence`, so an ordinary screenshot name cannot satisfy an
`E01` requirement even when capture succeeded.

The formalization prompt asks the model to emit mappings such as
`EVIDENCIA_ANEXO: E01 | A01`, but the model does not reliably receive those
private Bridge references. Filename recovery is narrow, and `suppressRecovery`
can prevent DOM recovery merely because an unclassified local file exists.
Consequently, successful capture can still produce zero transmitted images.

The screenshots also contain capture-only layout overrides. They are useful
portfolio evidence, but some of their visual polish is not the same CSS and
state used by the runtime application. This allows the public gallery and the
installed product to drift.

## Chosen architecture

Use a prompt-scoped evidence ledger with a durable local outbox. Capture and
transport become independent from semantic classification. The model may help
classify images, but it cannot authorize a GLPI write or invent an attachment
mapping.

The alternatives rejected are:

- continuing to infer evidence from filenames or image counts, because it is
  fragile and can attach the wrong screenshot;
- exposing Bridge-only `Axx` references in prompt text as the primary protocol,
  because provider DOM changes would remain a single point of failure;
- uploading every image as evidence immediately, because context screenshots
  must never become closure evidence automatically.

## Components and boundaries

### Browser capture ledger

At prompt submission, the Bridge creates an immutable manifest containing:

- `conversation_id` and a locally generated `prompt_id`;
- prompt timestamp and provider identifier;
- each attachment's stable UUID, capture ordinal, SHA-256 digest, safe display
  name, media type, byte size and capture source;
- optional model hints such as draft reference, ticket number, evidence ID and
  source index;
- state: `captured`, `queued`, `received`, `classified`, `linked`, `expired` or
  `rejected`.

The manifest is scoped to one conversation and one prompt. It is never a global
attachment queue. The raw bytes and manifest are persisted before the page can
clear its file input. Duplicate capture events are collapsed by digest within
the prompt while ordinal order is preserved.

### Durable transport

The Bridge sends the manifest and image bytes to a dedicated localhost inbox
as soon as the prompt is submitted. This transport does not wait for a
formalization response. The Assistant acknowledges each attachment by UUID and
digest; only acknowledged items may leave the Bridge outbox.

Retries are allowed only for the idempotent local transport operation. The
idempotency key is bound to the prompt, attachment UUID and digest. A changed
payload receives a new key. Remote GLPI and WAHA writes retain the existing
rule: an uncertain result is reconciled, never blindly repeated.

### Classification and association

The formalization response may refer to ordered prompt sources through a
validated `source_index`. The Bridge and Assistant resolve that index against
the immutable manifest. Existing `EVIDENCIA_ANEXO` and `EVIDENCIA_ARQUIVO`
syntax remains supported for compatibility, but the manifest is authoritative.

Each attachment is classified as one of:

- `context`: used to understand a ticket and never offered as evidence;
- `evidence`: explicitly linked to one ticket and one evidence/task target;
- `unresolved`: retained for operator review without blocking text handoff;
- `rejected`: invalid, unsafe or outside configured limits.

Multi-ticket prompts keep independent ticket/draft associations. An attachment
claimed by two tickets, a missing source index, duplicate evidence IDs or any
ticket mismatch is an explicit review state. The system never resolves these
conflicts by position alone.

### Assistant evidence inbox

The local Assistant stores unclassified prompt captures separately from the
closure queue. The review UI shows the prompt, ordered thumbnails and proposed
associations. The operator can change `context`, ticket, task and evidence ID
before Dry Run. Context images are excluded from GLPI payloads by construction.

An attachment is deleted only after confirmed linkage, explicit discard or
retention expiry. Expiry removes bytes and metadata together and records a
sanitized audit event without preserving image content.

## Runtime UI and visual system

The runtime application will use the same design tokens and responsive layout
that generate the documented screenshots. Capture scripts may set fixture data
and viewport size, but may not inject product layout CSS or rewrite receipt
content. Future screenshots must therefore demonstrate real runtime behavior.

The visual direction remains clean and restrained:

- deep neutral surfaces with white text and subtle blue/purple hierarchy;
- red only for destructive actions and genuine errors;
- green only for confirmed success and amber for pending or uncertain state;
- one primary, secondary, quiet and destructive button hierarchy;
- consistent 4/8 px spacing rhythm, control height, radius and focus treatment;
- responsive single-column, split and full-screen layouts without horizontal
  overflow or unreadable compressed ticket titles.

The Bridge overlay becomes a compact attachment chip. It shows a count and one
state icon, expands on demand, and never covers the prompt or send control. Its
expanded panel shows ordered thumbnails, prompt scope and only the controls
needed to resolve an ambiguity. Delivery confirmation is a small non-blocking
toast plus persistent status in the Assistant inbox.

The formalization screen uses progressive disclosure: ticket summary and
unresolved evidence first, task details second, Dry Run and execution receipt
last. Repetitive task cards become a responsive grid or list based on available
width; no screenshot-only class is required.

## Security requirements

The following requirements incorporate the prior security review and the
public GitHub state as of 2026-10-01:

- Keep Assistant and WAHA bound to loopback. Do not activate the experimental
  WAHA fork in the base package.
- Preserve WAHA API authentication, pinned image digest, disabled dashboard,
  Swagger and media/history routes, and separate session storage.
- Treat attachment names, media types, image bytes, LLM output and browser DOM
  as untrusted input.
- Accept only PNG, JPEG and WebP after signature verification and safe decode;
  enforce per-file, per-prompt and inbox quotas before parsing.
- Generate storage paths server-side from opaque IDs. Never accept arbitrary
  local paths, URL fetches or redirects for evidence. This closes the evidence
  path to traversal and SSRF.
- Store a SHA-256 digest and verify it at every transport boundary. Reject a
  UUID reused with different bytes.
- Bind manifest changes and Dry Run approval to the current prompt, closure,
  ticket state and attachment digests. Any change invalidates approval.
- Use one-time, expiring, persistently reserved authorization records so two
  concurrent executions cannot consume the same approval.
- Keep Bridge source/origin checks and signed pairing authorization. Extension
  origins may use only Bridge endpoints, never administrative or WAHA controls.
- Sanitize and re-escape GLPI HTML before display. No model-provided HTML is
  inserted directly into the DOM.
- Redact file content, tokens, phone numbers, message IDs and customer data from
  routine logs. Audit events contain opaque identifiers and state transitions.
- Do not add automatic remote retries for GLPI or WhatsApp writes after timeout
  or uncertain results. Reconcile by idempotency marker and live state.
- Preserve manual review, Dry Run and explicit approval for privileged GLPI
  writes. Capture and classification are not authorization.
- Correct the broken `SECURITY.md` documentation links and keep private
  vulnerability reporting as the supported disclosure path.

The early GitHub CI and CodeQL failures are historical setup failures, not open
findings: current public runs pass for Python and JavaScript/TypeScript. The
next change must keep both workflows green. Dependabot pull requests for
`pip-audit`, `setup-node` and CodeQL Action require compatibility review and
pinned immutable SHAs; major upgrades are not merged solely because they are
available.

## Failure handling

- If browser capture succeeds but localhost is offline, the outbox remains
  queued and the prompt may continue. The UI reports `aguardando aplicação`.
- If only part of a prompt is acknowledged, acknowledged and pending items are
  tracked separately; confirmed bytes are not resent.
- If classification is incomplete, text reaches the closure/proactive draft
  while attachments remain `unresolved` for review.
- If an image fails signature or decode validation, it is rejected with a safe
  reason and cannot be previewed or linked.
- If a conversation route changes during first-prompt creation, migration is
  allowed only from the provider's new-chat route to the newly created
  conversation in the same origin and within the bounded submission window.
- If two prompts are submitted rapidly, they receive different prompt IDs and
  snapshots. Late asynchronous capture cannot migrate between them.
- Cleanup never deletes a file that lacks an Assistant acknowledgement unless
  it has expired and the operator is warned.

## Compatibility and migration

Existing Bridge 2.4.0 storage is imported once into an `unresolved legacy`
manifest. Existing closure markers, `EVIDENCIA_ANEXO`, `EVIDENCIA_ARQUIVO`,
manual uploads and proactive `source_index` remain accepted. Manual upload is a
recovery path, not the normal first-prompt flow.

The Assistant database receives additive tables or metadata records. Package
upgrade preserves settings, GLPI configuration, WAHA sessions and unfinished
drafts. Rolling back ignores the new records without corrupting previous state.

## Test strategy

Implementation follows test-first development. Required regression layers:

- pure planner tests for context/evidence/unresolved classifications and
  cross-ticket conflict detection;
- browser tests for first prompt, Enter and button submission, paste, drag,
  input replacement, route migration, rapid prompts, duplicate events and
  reload recovery;
- transport tests for partial ACK, offline queue, digest mismatch, replay,
  quota enforcement, malformed images and expiry;
- API tests proving context never enters GLPI evidence payloads and approval is
  invalidated when attachment state changes;
- UI tests at full, split and narrow widths with keyboard focus, reduced motion
  and no overlay obstruction;
- screenshot capture using only real runtime CSS and synthetic offline fixtures;
- complete Python and JavaScript regressions, publication audit, dependency
  audits, CodeQL, deterministic build, SBOM and archive hash verification.

Live acceptance remains explicit: Debian/systemd/Docker installation and real
browser-to-Assistant capture must be exercised on a disposable host before a
production-ready claim. Real WAHA delivery is separate and must use an
authorized test recipient.

## Acceptance criteria

1. An ordinary image attached to the first prompt is visible in the Assistant
   inbox after one submission, in the original order, without renaming.
2. The same image is never uploaded twice after reload, route creation or local
   retry.
3. A context screenshot cannot become evidence without an explicit validated
   association.
4. Two tickets in one prompt keep independent ordered attachments; ambiguous
   images remain unresolved and visible.
5. Text handoff continues when images are pending, and later classification can
   complete the same draft without duplicating tasks or tickets.
6. Changing an attachment, ticket, task or evidence association invalidates the
   previous Dry Run approval.
7. The compact Bridge control does not cover the composer or send button at the
   supported viewport widths.
8. Runtime screens match the documented design system without capture-only
   product CSS or mutated receipt text.
9. Security regressions cover traversal, SSRF, replay, MIME spoofing, oversized
   payloads, cross-origin access and uncertain remote results.
10. CI and CodeQL pass for the reviewed commit, and release notes explain what
    changed and why.

## Delivery sequence

1. Evidence ledger schema, transport contract and compatibility import.
2. Browser capture/outbox and Assistant inbox with security validation.
3. Classification, multi-ticket association and Dry Run binding.
4. Runtime design tokens, responsive formalization UI and compact Bridge UI.
5. Real-runtime screenshot harness, documentation and security link repair.
6. Full regression, clean-host acceptance, release notes and packaging only
   after the operator requests the release build.
