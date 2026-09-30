# Source map

This repository is a sanitized snapshot derived from GLPI Assistant 3.4.0-rc4, Browser Bridge 2.4.0 and the installer for WAHA 2026.9.1. It starts a new history and is not a byte-identical production release.

| Path | Responsibility |
|---|---|
| `package/usr/lib/glpi-assistant/app/main.py` | FastAPI routes, GLPI task operations, plan cache, evidence verification |
| `package/usr/lib/glpi-assistant/app/parser.py` | Structured closure parsing and batch boundaries |
| `package/usr/lib/glpi-assistant/app/glpi.py` | GLPI REST client, entity/profile context, catalogs |
| `package/usr/lib/glpi-assistant/app/store.py` | SQLite, configuration and local metadata |
| `package/usr/lib/glpi-assistant/app/local_security.py` | Host/origin boundary |
| `package/usr/lib/glpi-assistant/app/workbench.py` | Assignment monitoring, initial reply and personal queue |
| `package/usr/lib/glpi-assistant/app/whatsapp_auto.py` | WAHA recipient verification, reservation and delivery state |
| `package/usr/lib/glpi-assistant/app/evidence_bridge.py` | Image validation and evidence storage |
| `package/usr/lib/glpi-assistant/app/proactive*.py` | Proactive ticket contract, Dry Run, execution and recovery |
| `package/usr/lib/glpi-assistant/app/proactive_store.py` | Durable operation and reconciliation state |
| `package/usr/lib/glpi-assistant/app/static/` | Real HTML/CSS/JavaScript UI |
| `extension/` | Browser Bridge: capture, pairing and handoff |
| `package/DEBIAN/` | Debian metadata and maintainer scripts |
| `package/lib/systemd/system/` | Local service unit |
| `package/usr/bin/` | Operations, backup and WAHA installer |
| `patches/`, `security-3.4/` | Experimental WAHA restrictions; not the active installed image |
| `tests/`, `qa/` | Offline Python, JavaScript, DOM and installer regressions |

The source layout is retained to preserve test imports and installation paths. No artificial `src/` migration was performed.
