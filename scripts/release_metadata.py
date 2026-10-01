from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseMetadata:
    public_version: str
    debian_version: str
    bridge_version: str

    @property
    def artifact_names(self) -> tuple[str, ...]:
        return (
            f"glpi-assistant_{self.debian_version}_all.deb",
            f"glpi-assistant-bridge_{self.bridge_version}_chromium.zip",
            f"glpi-assistant-bridge_{self.bridge_version}_firefox-dev.xpi",
            "package-manifest.json",
            "sbom.cdx.json",
            "SHA256SUMS",
        )


RELEASE = ReleaseMetadata(
    public_version="3.4.0-beta.1",
    debian_version="3.4.0~beta.1-1",
    bridge_version="2.4.1",
)
