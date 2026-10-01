# Sanitization policy

The public candidate is built from synthetic fixtures and is blocked whenever
the publication audit finds an organization identifier, credential-shaped
value, private network address, private domain, personal email address or
plausibly routable Brazilian phone number.

## Coverage

`python scripts/audit_publication.py . dist` scans UTF-8 source files and the
members of `.deb`, `.zip` and `.xpi` artifacts. Archive members are read in
memory with per-member and aggregate size limits; paths are never extracted to
the working tree. Findings contain a rule name and a SHA-256 digest, never the
matched value.

Generated dependencies, caches, runtime databases, build output, logs and
local sessions are excluded from traversal and from Git. Their exclusion is
not an allowlist for release artifacts: `dist/` is passed explicitly during
the release audit.

## Intentional examples

- Domains under `example.com`, `example.org`, `example.net` and
  `example.invalid` are documentation-only values.
- `192.0.2.0/24` and loopback addresses are documentation/test boundaries.
- Phone-shaped fixtures use an impossible subscriber prefix beginning with
  zero after a valid area code. They exercise formatting without identifying a
  real subscriber.
- Product names are used only when necessary to describe interoperability.

## False positives

Do not suppress a finding globally. Replace the value with a standards-based
example when possible. A narrow policy exception requires a regression test,
a documented reason and review of every generated artifact that can carry the
value.
