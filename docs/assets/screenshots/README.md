# Interface gallery

Real RC3 HTML/CSS/JavaScript, using synthetic ticket 900001 and intercepted local API responses. The parser is the real implementation. Dry Run and result responses are simulated fixtures; these images do not prove live GLPI execution. Capture script blocks external HTTPS requests. No credentials, pairing or real recipients are used.

![Central](01-central.png)
![Ticket inspection](02-ticket-card.png)
![Initial response paused](03-t01-paused.png)
![Dry Run with five tasks](04-dry-run.png)
![Simulated application receipt](05-result-simulated.png)

Reproduce with `python scripts/capture_portfolio_screenshots.py` after installing Playwright Chromium. Optional `CHROMIUM_EXECUTABLE` selects a local QA browser. See [capture report](capture-report.json).

Batch/evidence association have regression coverage, but no additional screenshot is claimed here. Proactive creation does not exist in RC3 and has no screenshot.
