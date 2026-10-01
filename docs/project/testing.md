# Reproducible validation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r package/usr/lib/glpi-assistant/app/requirements.txt -r requirements-dev.txt
GLPI_ASSISTANT_DATA="$PWD/.test-data" python -m pytest tests qa/test_waha_installer.py -q
python3 scripts/check_javascript.py
python3 scripts/build_portfolio.py
```

The data environment variable must be set before imports: runtime defaults to `/data`. The tests use fake GLPI clients and WAHA calls. Installer tests use a fake Docker executable and do not touch the host daemon.

Browser captures run via `scripts/capture_portfolio_screenshots.py`; they render the real static application and intercept API traffic with synthetic fixtures. Do not configure a production token in this flow. Actual delivery, host installation, and proactive creation require separate acceptance tests.

CI runs these same commands. Dependency/security checks provide findings, not a guarantee that the system is vulnerability-free. See [validation](validation.md).
