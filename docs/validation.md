# Validation record

RC4 snapshot reviewed on 2026-09-30. Results cover offline execution with mocked remote integrations.

| Check | Result | Boundary |
|---|---:|---|
| Python | 260 passed | temporary SQLite data; fake GLPI and WAHA clients |
| JavaScript/DOM | 22 scripts passed; 16 syntax checks | simulated browser and API responses |
| Responsive layout | 480, 768 and 1280 px without horizontal overflow | sampled synthetic scenarios |
| Debian package | metadata, maintainer scripts and extraction checked | package not installed on a clean host |
| Proactive creation | contract, plan, execute, persistence and UI tests passed | no ticket created in a live GLPI |
| Messaging | reservation, recipient and delivery-state tests passed | no real WhatsApp delivery |

The machine-readable record is [VALIDACAO_3.4.0-rc4.json](VALIDACAO_3.4.0-rc4.json). Commands are documented in [testing](testing.md).

Passing tests show that the reviewed snapshot behaves as specified under these fixtures. They do not establish production homologation, compatibility with every GLPI customization or the absence of vulnerabilities.
