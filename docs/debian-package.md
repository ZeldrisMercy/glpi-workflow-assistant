# Debian packaging audit

Package metadata: architecture `all`, version `3.4.0~rc4-1`; base app reports 3.4.0-rc4.

`preinst` checkpoints an existing deployment. `postinst` prepares mode-0700 persistence, enables Docker, loads/builds the app image, starts `glpi-assistant.service`, and runs the managed WAHA installer. `prerm` preserves service continuity during upgrade and stops services on removal. `postrm` preserves user data even on purge.

The build script validates shell syntax, executable modes, package metadata and reproducibility using a fixed source timestamp. It generates hashes and a file manifest. It does not install the package, start Docker or contact GLPI/WAHA. Clean install, upgrade and rollback remain host acceptance checks.
