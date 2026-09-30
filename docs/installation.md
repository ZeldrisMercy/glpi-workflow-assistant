# Installation and local development

Target: Linux with Docker and systemd; Debian/Ubuntu package format. This snapshot was tested with Python 3.12 in an isolated environment. No clean host installation or production GLPI/WAHA delivery was performed for this portfolio snapshot.

## Run without installing services

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r package/usr/lib/glpi-assistant/app/requirements.txt
mkdir -p .local-data
chmod 700 .local-data
GLPI_ASSISTANT_DATA="$PWD/.local-data" uvicorn main:app --app-dir package/usr/lib/glpi-assistant/app --host 127.0.0.1 --port 8765 --no-proxy-headers
```

Open `http://127.0.0.1:8765`. Configure your authorized GLPI HTTPS URL and API tokens in the local UI. Do not commit `.local-data`. The standalone server does not install WAHA and does not automatically start the assignment monitor unless configured.

## Build and inspect the Debian package

```bash
python3 scripts/build_portfolio.py
dpkg-deb --info dist/glpi-assistant_3.4.0~rc4-1_all.deb
sha256sum -c dist/SHA256SUMS
```

The package is built from the sanitized RC4 source. Install only in a disposable test environment after reviewing the installer:

```bash
sudo apt install ./dist/glpi-assistant_3.4.0~rc4-1_all.deb
```

The package depends on Python, pip, Docker, CA certificates, xdg-utils and util-linux. `postinst` starts Docker, builds the app image, enables/restarts the Assistant systemd service, then installs/configures WAHA. WAHA is optional for user workflows but its installation is currently part of the Debian installer. The installer does not pair a WhatsApp account or enable messaging.

Both services use loopback. The app container uses host networking, read-only root filesystem, a writable `/data` mount, dropped capabilities and resource limits. Host-network isolation is not a VM boundary; local processes and host administrators remain trusted.

## Upgrade, backup, removal

Run `sudo glpi-assistant-backup` and store the sensitive backup privately before upgrades. The upgrade `preinst` creates a checkpoint; the WAHA installer retains a previous managed container and attempts rollback if health checks fail. Review the scripts and [operations](OPERACAO_E_RECUPERACAO.md) before recovery.

`sudo apt remove glpi-assistant` stops the app and managed WAHA service. Even purge intentionally preserves `/var/lib/glpi-assistant` and the session. Permanent data deletion is a separate explicit operation after backup. Docker itself is not removed by uninstalling the app.
