# Screenshot methodology

The portfolio gallery is generated from the real application UI at 1440×1000 with a fresh temporary data directory and deterministic synthetic fixtures. The capture harness intercepts application API responses and rejects every non-loopback request.

`scripts/capture_portfolio_screenshots.py` records page errors, blocked requests, fulfilled external requests and real-write count in [capture-report.json](../assets/screenshots/capture-report.json). `scripts/ocr_screenshots.py` records Tesseract output and SHA-256 hashes in [ocr-report.json](../assets/screenshots/ocr-report.json), then applies the same publication policy used for source and archives.

The eight scenarios cover the central queue, expanded ticket, T01–T05 review, Dry Run, proactive batch, evidence association, simulated execution receipt and optional messaging state. Simulated receipts and messaging are labeled; no screenshot claims live delivery.

After generation, each image is manually reviewed for clipping, browser chrome, private identifiers, misleading state and consistent framing. Any external request, OCR finding, page error or real write blocks the evidence set.
