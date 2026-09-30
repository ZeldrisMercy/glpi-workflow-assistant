# Privacy and local data

`config.json` contains GLPI credentials. `app.db` holds local catalog/queue/automation information. Evidence files and backups can contain personal or client data. WAHA session state authenticates messaging access. These remain outside Git.

Use directory mode 0700 and credential file mode 0600, restrict local access and keep backups encrypted according to your environment. Loopback does not protect against a compromised host or another privileged local process. Do not enable remote access by changing bind addresses.

Public examples use synthetic entities, identities and identifiers; domains use `.example`/`.test`. No real ticket screenshots are included.
