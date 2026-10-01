# Compatibility

| Layer | Baseline | Evidence / status |
|---|---|---|
| Assistant | 3.4.0-beta.1 | Source and local regression tests verified |
| Python | Tested 3.12; Docker targets 3.13 | Full suite on 3.12; exact count is recorded in the publication report. Docker installation is not verified |
| Node | 24.19.0 | 22 JavaScript/DOM scripts and 16 syntax checks passed |
| Debian package | all, 3.4.0~beta.1-1 | Metadata, syntax and extraction checked; clean-host acceptance pending |
| Browser Bridge | 2.4.0 | Manifest and static tests checked; live browser compatibility not certified |
| Chromium extension | Manifest V3, minimum Chrome 148 | Declared in generated manifest; not live homologation |
| Firefox | Development XPI | Unsigned; not Mozilla distribution approval |
| UI browser | Headless Chromium 153 | Synthetic screenshot scenarios; no extension integration |
| GLPI | REST integration present | Mocked tests; no live version certified |
| WAHA | 2026.9.1 image pinned by installer | Offline installer tests; pairing/delivery not verified |
| Docker/systemd | Installer dependencies | Static/package checks only |
| Proactive creation | Implemented in the public beta | Offline tests passed; live GLPI acceptance pending |
