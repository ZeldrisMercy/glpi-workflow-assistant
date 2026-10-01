# Quick start

Run the public beta locally with isolated, synthetic state before connecting any real service. The application binds to loopback and supports Linux with Python 3.12.

## Local application

```bash
git clone https://github.com/ZeldrisMercy/glpi-workflow-assistant.git
cd glpi-workflow-assistant
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r package/usr/lib/glpi-assistant/app/requirements.txt
mkdir -p .local-data
chmod 700 .local-data
GLPI_ASSISTANT_DATA="$PWD/.local-data" uvicorn main:app --app-dir package/usr/lib/glpi-assistant/app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

Open `http://127.0.0.1:8765`. The empty local state does not contact GLPI or a messaging service. Review the [synthetic demo data](demo-data.md) and the [configuration boundary](configuration.md) before adding authorized credentials.

## Validate the source snapshot

```bash
python -m pip install -r requirements-dev.txt
npm ci
python -m pytest -q
python scripts/check_javascript.py
python scripts/audit_publication.py .
```

## Build the beta artifacts

```bash
python scripts/build_portfolio.py
python scripts/verify_release.py dist
sha256sum --check dist/SHA256SUMS
```

The expected Debian artifact is `dist/glpi-assistant_3.4.0~beta.1-1_all.deb`. Read the [Debian installation guide](debian-installation.md) before installing it because the package changes system services and provisions an optional messaging runtime.

## Safety boundary

- Use only systems and API credentials you are authorized to access.
- Keep `.local-data`, backups, tokens, screenshots and session state out of Git.
- Treat Dry Run and approval as required review controls, not as proof of production compatibility.
- Do not expose port 8765 beyond loopback without adding an authentication and network-security layer.
