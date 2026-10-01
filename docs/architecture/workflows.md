# Workflow diagrams

## Existing-ticket closure

```mermaid
flowchart TD
    A["Load ticket"] --> B["Parse T01–T05"]
    B --> C["Map evidence"]
    C --> D["Review Dry Run"]
    D --> E["Approve and verify"]
```

## Proactive creation

```mermaid
flowchart TD
    A["Structured draft"] --> B["Resolve catalog fields"]
    B --> C["Deduplicate request"]
    C --> D["Review batch"]
    D --> E["Approve creation"]
```

## Approval invalidation

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Reviewed: generate Dry Run
    Reviewed --> Draft: change text, ticket or evidence
    Reviewed --> Applying: explicit approval
    Applying --> Verified: confirm remote state
    Applying --> ReviewRequired: uncertain result
```

## Optional messaging

```mermaid
flowchart TD
    A["Eligible new assignment"] --> B{"Operator enabled it?"}
    B -->|no| C["Remain paused"]
    B -->|yes| D["Submit idempotent request"]
    D --> E["Record accepted or uncertain"]
    E -->|separate check| F["Delivery status"]
```

Messaging is not required for ticket closure. An accepted request is not called
delivered until a separate delivery status supports that claim.
