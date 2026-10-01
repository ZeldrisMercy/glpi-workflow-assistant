# Publication report — v3.4.0-beta.1

Candidate validation covers remote commit `0bc3ad6db87b7c703dfecc303ac2067837e10907` and tree `dbd89a12082629580a7a1702d8c03e03d6959a2a`. The repository remained private throughout this review.

## Evidence summary

| Gate | Result | Evidence boundary |
|---|---:|---|
| Python | 297 passed; 2 deprecation warnings | temporary state and simulated remote clients |
| JavaScript | 16 syntax files; 22 regression files | deterministic DOM/browser fixtures |
| Publication audit | 0 blocking findings | tracked source, release archives and OCR |
| Release build | byte-identical rebuild | Debian package, two Bridge archives, manifest, SBOM and hashes |
| SHA-256 | 5 payload checks verified | `dist/SHA256SUMS` |
| GitHub CI | passed | run `36803589457`, including `npm ci`, dependency audits and build gates |
| Screenshots | 8 passed | zero external requests, zero real GLPI writes and zero OCR findings |
| CodeQL | configured; upload deferred while private | analysis ran for Python and JavaScript; GitHub rejected result upload because code scanning is unavailable |
| Clean-host installation | not executed | current runner has neither systemd nor Docker |

## Release artifacts

| Artifact | SHA-256 |
|---|---|
| `glpi-assistant_3.4.0~beta.1-1_all.deb` | `4261673eba720ef4eac0c00f39177c81d16a3a84178a15fbd212a865c324fc1a` |
| `glpi-assistant-bridge_2.4.0_chromium.zip` | `23dd4319ac152df43697538d319aa9c5d483710ab1ab61a13ddcda091a0317ec` |
| `glpi-assistant-bridge_2.4.0_firefox-dev.xpi` | `85a81dab93572fd2b8258d3732507ab1d538d04e4522471778579db9411c9a13` |
| `package-manifest.json` | `91c62693ab530c24ddf1390bd7b1bd90b7e6c052a5a6015b80d2858a7564c886` |
| `sbom.cdx.json` | `0822acb0dabbabf287496db54c6fc41624f07b6a6893518c849e5c6c4827a4ad` |

## Screenshot review

The capture harness rendered eight application views using synthetic fixtures. It reported no page errors, no fulfilled external requests and no real writes. Tesseract 5.3.4 covered every committed PNG and the publication policy returned zero findings. The agent-assisted visual review checked identity, clipping, synthetic-state labels and misleading delivery claims; owner review remains pending.

## Claims deliberately not made

- No production-readiness, certification, adoption or measured productivity claim.
- No live GLPI compatibility guarantee across custom entities and catalogs.
- No live messaging delivery claim.
- No successful clean-host installation claim.
- No signed Firefox distribution claim.

## Pending publication gates

1. CodeQL result upload must finish successfully after public code scanning becomes available.
2. A disposable supported Linux host must complete install, loopback health, synthetic workflow, backup and removal/rollback acceptance, or the limitation must remain prominent.
3. The owner must review the private PR and final packet.
4. The owner must give a fresh, explicit authorization immediately before repository visibility changes.

`visibility_change_authorized: false`
