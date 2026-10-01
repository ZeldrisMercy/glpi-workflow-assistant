# Operations, backup and recovery

## Before an upgrade

Keep the previously verified package and its required images available. Do not upgrade while a GLPI operation is in progress. The application-data backup does not include the WAHA session volume.

```bash
sudo systemctl stop glpi-assistant.service
sudo glpi-assistant-backup
sudo systemctl start glpi-assistant.service
```

The backup command prints a path under `/var/backups/glpi-assistant`. Treat that archive as sensitive. If backup fails, stop the upgrade and diagnose the failure.

## Minimum diagnostics

```bash
glpi-assistant status
journalctl -u glpi-assistant.service -n 80 --no-pager
curl --fail http://127.0.0.1:8765/health
```

Sanitize diagnostic output before sharing it. Confirm that the UI remains loopback-only and that GLPI uses HTTPS with a trusted certificate. The application intentionally provides no TLS-verification bypass.

## Uncertain results

A timeout after a write can mean that the remote system completed the operation. Inspect the GLPI history or delivery state before retrying. Do not delete idempotency records to force another attempt. The delivery-check action verifies state; it does not resend.

For partial ticket application, generate a new review from current GLPI state and apply only the unconfirmed operations.

## Rollback

1. Stop the application and preserve a private copy of current state.
2. Reinstall the previously verified package and dependencies.
3. Restore an older data backup only for a confirmed incompatibility or corruption; an unnecessary restore can reintroduce duplicate-write risk.
4. Validate archives in a private temporary directory before extracting as root.
5. Check the application version, SQLite integrity, configuration, queue and delivery/idempotency records before re-enabling automation.

A WAHA session backup requires the managed container to be stopped and its volume copied using an administrator-controlled method. Never run the current and preserved previous containers against the same session volume simultaneously.

## Incident response

Pause automation and stop optional messaging if unauthorized activity is suspected. Revoke GLPI tokens, unlink the messaging device, rotate the WAHA API key, preserve relevant local evidence and investigate the host before reconnecting accounts.

Package removal preserves `/var/lib/glpi-assistant`, messaging state, extension data and backups. Delete them only after revoking access and confirming the retention decision.
