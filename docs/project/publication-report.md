# Publication report — v3.4.0-beta.1

Candidate validation covers application commit `ffbbf6847b7f7444a455f7e7d8d2c3c81574c31c` and tree `b62c9d89a36b4138c08fb67a3dc29400359cc16e`. A later evidence-only commit records these results without changing the validated application or release artifacts. The review was completed privately; the owner explicitly authorized public visibility immediately before publication on 2026-10-01.

## Evidence summary

| Gate | Result | Evidence boundary |
|---|---:|---|
| Python | 301 passed; 2 deprecation warnings | temporary state and simulated remote clients |
| JavaScript | 16 syntax files; 22 regression files | deterministic DOM/browser fixtures |
| Publication audit | 0 blocking findings | tracked source, release archives and OCR |
| Release build | byte-identical rebuild | Debian package, two reproducible Bridge archives, manifest, SBOM and hashes |
| SHA-256 | 5 payload checks verified | `dist/SHA256SUMS` |
| GitHub CI | passed | run `36807751963`, including `npm ci`, dependency audits and build gates |
| Screenshots | 8 passed | zero external requests, zero real GLPI writes and zero OCR findings |
| CodeQL | passed publicly | Python and JavaScript result upload succeeded in run `36811350560` |
| Clean-host installation | not executed | current runner has neither systemd nor Docker |

## Release artifacts

| Artifact | SHA-256 |
|---|---|
| `glpi-assistant_3.4.0~beta.1-1_all.deb` | `6094fcc0a563830e5172559380396aa1f8509a4115c8f9818089834722b7c181` |
| `glpi-assistant-bridge_2.4.1_chromium.zip` | `f03dc5c254bb9398630b1ecad0b16cb397f6c0d7c5ef395b1ef528132db225d7` |
| `glpi-assistant-bridge_2.4.1_firefox-dev.xpi` | `09184e113345602006a29297654bccd8e8a1c1371879d121fa3ef8006edcd2fb` |
| `package-manifest.json` | `4310754959b35ea226d595ced43a5b99fe25be8092deb69ce70e5c408eb75c8d` |
| `sbom.cdx.json` | `0822acb0dabbabf287496db54c6fc41624f07b6a6893518c849e5c6c4827a4ad` |

## Signed Firefox distribution

The signed Firefox XPI used for persistent Web Extension Manager installation is distributed outside the source tree so the public repository remains reproducible and sanitized. The supplied signed artifact for Bridge 2.4.1 has SHA-256 `36e7053ee519072ae6f92d824cc89a8eb4e090ae2dd41544f8f13f5fde22976b`.

## Screenshot review

The capture harness rendered eight application views using synthetic fixtures. It reported no page errors, no fulfilled external requests and no real writes. Tesseract 5.3.4 covered every committed PNG and the publication policy returned zero findings. The agent-assisted visual review checked identity, clipping, synthetic-state labels and misleading delivery claims; owner review remains pending.

## Claims deliberately not made

- No production-readiness, certification, adoption or measured productivity claim.
- No live GLPI compatibility guarantee across custom entities and catalogs.
- No live messaging delivery claim.
- No successful clean-host installation claim.
- No Mozilla Add-ons listing, production certification or live browser homologation claim.

## Pending publication gates

1. A disposable supported Linux host must complete install, loopback health, synthetic workflow, backup and removal/rollback acceptance, or the limitation must remain prominent.

`visibility_change_authorized: true`
