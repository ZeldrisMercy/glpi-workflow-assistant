# WAHA integration

Messaging is a configurable workflow; Debian installation also provisions its WAHA infrastructure. The current installer pins WAHA `2026.9.1` by digest and binds the service to localhost port 3000. See `package/DEBIAN/postinst` and `waha_runtime.py` for exact behavior.

Configure and pair only in a controlled environment. Session material, API credentials, message bodies and delivery receipts are sensitive. Polling and initial contact can write after configuration-level enablement; they do not all use the formalization Dry Run approval flow.

`security-3.4/modified-source` is an experimental upstream patch candidate. It is not installed by the Debian package and is not a claim that the base image enforces all proposed restrictions. Its local policy test is limited; full upstream build, live authorization and delivery are unverified.

No WhatsApp pairing or message delivery was performed for this portfolio snapshot. The fixtures are offline and must never be used as real recipients.
