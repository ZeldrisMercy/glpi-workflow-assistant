# Known limitations

- Public beta; no production-readiness or universal GLPI compatibility claim.
- Local, single-operator deployment with no hosted login, multi-user RBAC or central tenancy.
- GLPI tokens, local evidence, backups and WAHA session state are sensitive administrator-managed assets.
- Ticket-task and evidence writes are not globally transactional; partial success requires reconciliation.
- Proactive creation has offline contract and UI coverage, while live entity/category variations still require acceptance testing.
- Optional messaging is independently enabled; synthetic screenshots do not prove live message delivery.
- WAHA provisioning is included in the Debian installer even when messaging remains disabled in the UI.
- Chromium Bridge declares Chrome 148 minimum. The Firefox development XPI is unsigned and needs an appropriate development installation path.
- Automatic retention cleanup is not included in this beta.
- A clean Linux install, upgrade and rollback acceptance result is recorded separately and must not be inferred from unit tests.
- Host administrators remain inside the trust boundary; loopback binding is not multi-user authentication.
