# Validation record

The public-beta candidate is validated offline with temporary SQLite state, fake GLPI/WAHA clients and intercepted browser responses. Exact final counts and artifact hashes belong in the candidate-bound publication report produced after a clean checkout.

| Area | Current gate | Boundary |
|---|---|---|
| Python | Full pytest suite | temporary local state; mocked remote clients |
| JavaScript/DOM | syntax and regression scripts | simulated browser and API responses |
| Publication | normalized source/archive audit | blocked identities and secret-like values |
| Screenshots | eight captures plus OCR | loopback-only harness; zero real writes |
| Release | deterministic build and verifier | artifact manifest, hashes and scoped SBOM |
| Clean host | separate acceptance record | disposable supported Linux environment |

Commands are documented in [testing](testing.md), expected behaviors in the [validation matrix](validation-matrix.md), and release inputs in the [release manifest](release-manifest.json).

Passing these gates demonstrates behavior under the stated fixtures. It does not establish vulnerability-free software, production certification, or compatibility with every GLPI customization.
