# Clean-host installation record

## Candidate

- Version: `3.4.0-beta.1`
- Debian artifact: `glpi-assistant_3.4.0~beta.1-1_all.deb`
- Validated tree: `dbd89a12082629580a7a1702d8c03e03d6959a2a`

## Current result

**Not executed.** The available Ubuntu 24.04 validation container does not run systemd and has no Docker or compatible container runtime. Running the package maintainer scripts there would not represent a supported installation and could create a false pass.

The package was instead built twice byte-identically, inspected with `dpkg-deb --contents`, checked for maintainer-script shell syntax and scanned as an archive. These checks do not replace installation acceptance.

## Required disposable-host procedure

1. Start a fresh supported Debian/Ubuntu VM with systemd, Docker access and no existing Assistant state.
2. Verify `SHA256SUMS`, inspect package metadata and install the exact artifact.
3. Confirm `glpi-assistant.service`, `http://127.0.0.1:8765/health` and loopback-only listeners.
4. Run a synthetic workflow without real GLPI or messaging credentials.
5. Create and inspect a backup.
6. Exercise upgrade/rollback or removal while confirming persistent-state behavior.
7. Record OS image, Docker version, commands, timestamps and sanitized results here.

Until this record is completed, installation instructions remain beta guidance rather than a verified clean-host claim.
