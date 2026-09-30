# Known limitations

- RC baseline, not a production-homologated portfolio release.
- Local single-operator deployment; no hosted login, multiuser RBAC or central tenancy.
- GLPI tokens and WAHA session state are sensitive local assets.
- Contact automation and initial replies can write after operator enablement; they are separate from closure approval.
- GLPI task and evidence writes are not globally transactional; partial success must be reconciled.
- WAHA installation is part of the Debian installer, even though messaging is optional in the UI.
- Experimental WAHA source restrictions are not the active installed image.
- Chromium Bridge declares Chrome 148 minimum. Firefox developer XPI requires appropriate developer installation/signing; this snapshot does not supply a signed Firefox release.
- Proactive creation is implemented in RC4, but live GLPI creation and local catalog variations still require acceptance testing.
- Uncertain uploads require manual reconciliation; automatic retention cleanup is not included in this candidate.
- Screenshots use the actual UI with synthetic API fixtures; they are not proof of production GLPI/WAHA delivery.
- Local tests and package inspection do not substitute for install/upgrade/rollback on a clean Linux host.
- Ownership and third-party license review must be completed before public distribution. No open-source license is selected automatically.
