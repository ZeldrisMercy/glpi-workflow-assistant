# Evidence gallery

These images are reproducible evidence from the real application HTML, CSS and
JavaScript. Every ticket, person, organization and status is synthetic. The
capture harness runs against loopback-only API fixtures, aborts non-loopback
requests and records **zero real GLPI writes**.

| # | Evidence | What it demonstrates |
|---:|---|---|
| 01 | [Central queue](01-central-queue.png) | Local work queue, timing, filters and primary actions. |
| 02 | [Expanded ticket](02-expanded-ticket.png) | Ticket-level actions and message helpers. |
| 03 | [T01–T05 review](03-t01-t05-review.png) | Five parsed task cards before execution. |
| 04 | [Dry Run](04-dry-run.png) | Exact planned operations awaiting human approval. |
| 05 | [Proactive batch](05-proactive-batch.png) | Independent proactive-ticket review and batching. |
| 06 | [Evidence association](06-evidence-association.png) | Local image preview and explicit E01 mapping. |
| 07 | [Execution receipt](07-execution-receipt.png) | Clearly labelled offline simulation receipt. |
| 08 | [Optional messaging](08-messaging-status.png) | Optional integration shown paused; no delivery claim. |

## Reproduce

```bash
CHROMIUM_EXECUTABLE=/path/to/chromium python scripts/capture_portfolio_screenshots.py
python scripts/ocr_screenshots.py docs/assets/screenshots
python -m pytest tests/test_screenshot_contract.py -q
```

The T01–T05 capture applies a documented, capture-only CSS frame to arrange the
five existing UI cards in one 1440×1000 viewport. It does not alter their text,
state or application behavior. Review [capture-report.json](capture-report.json)
and [ocr-report.json](ocr-report.json) for the machine-readable evidence.
