# Proactive ticket creation

Implemented in **GLPI Workflow Assistant 3.4.0-beta.1** and Browser Bridge **2.4.0**.

The flow converts one prompt into one or multiple reviewable ticket drafts:

```text
prompt + timestamp + evidence
  → schema validation
  → catalog and actor resolution
  → duplicate/idempotency checks
  → Dry Run
  → human approval
  → GLPI ticket and activity creation
  → receipt and audit record
```

## Catalog and defaults

- Entity and category are mandatory and resolved against GLPI.
- Requester and technician default to the authenticated operator; named alternatives must resolve without ambiguity.
- Type defaults to **Request**.
- Priority defaults to **Low/Medium**. High or above requires an explicit local choice.
- Each draft retains the originating prompt timestamp, including multi-ticket batches.

## Evidence contract

The Bridge records each image position, local identifier and target activities. Context images are excluded from final evidence. Missing files, stale captures and final evidence without an activity association block creation until reviewed.

## Safety and recovery

Editing a draft invalidates only that draft's approved plan. Operations are persisted before remote mutations. A lost response is reconciled using the operation marker; uncertain ticket creation, task creation or upload is never repeated automatically.

Successful items leave the review queue with a GLPI link and receipt. Failed or uncertain items remain available for correction or reconciliation. Proactive tickets carry a marker that excludes them from automatic initial T01 and new WAHA contact messages.

## Validation boundary

The implementation is covered by offline unit, contract, execution, storage, Bridge and responsive layout tests. The repository validation did not create a real ticket in the owner's GLPI environment; local catalog rules, permissions, timezone and priority behavior still require acceptance testing.
