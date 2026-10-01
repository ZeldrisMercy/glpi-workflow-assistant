# Debian installation

The beta package targets Debian/Ubuntu-compatible Linux hosts and installs a local, single-operator service. Perform the first installation on a disposable test host.

## Inspect and verify

```bash
python scripts/build_portfolio.py
python scripts/verify_release.py dist
sha256sum --check dist/SHA256SUMS
dpkg-deb --info dist/glpi-assistant_3.4.0~beta.1-1_all.deb
dpkg-deb --contents dist/glpi-assistant_3.4.0~beta.1-1_all.deb
```

## Install

```bash
sudo apt install ./dist/glpi-assistant_3.4.0~beta.1-1_all.deb
```

The installer prepares mode-0700 persistence, enables the local application service, and provisions the pinned WAHA runtime used by the optional messaging workflow. It does not pair a messaging account or enable message delivery. Review `package/DEBIAN/postinst` before installation.

Verify the service locally:

```bash
glpi-assistant status
curl --fail http://127.0.0.1:8765/health
journalctl -u glpi-assistant.service -n 80 --no-pager
```

## Files and service effects

- Application state: `/var/lib/glpi-assistant`
- Sensitive backups: `/var/backups/glpi-assistant`
- systemd unit: `glpi-assistant.service`
- Web UI/API: `127.0.0.1:8765`
- Optional WAHA endpoint: loopback only

The container uses host networking, a read-only root filesystem, a writable data mount, dropped capabilities and resource limits. Loopback isolation is not a substitute for multi-user authentication; local administrators remain trusted.

## Backup, upgrade and rollback

Before upgrading, stop active writes and run `sudo glpi-assistant-backup`. Store the resulting archive privately. The package creates an upgrade checkpoint, but this does not replace a tested backup and rollback plan.

For rollback, preserve the current state, reinstall the previously verified package, restore data only when necessary, and inspect idempotency/message records before re-enabling automation. Follow [operations and recovery](operations-and-recovery.md).

## Remove

```bash
sudo apt remove glpi-assistant
```

Removal stops managed services. Persistent application and messaging state is intentionally preserved to prevent accidental data loss; permanent deletion is a separate administrator action after backup and credential/session revocation.
