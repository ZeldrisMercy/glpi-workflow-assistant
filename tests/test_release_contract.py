from __future__ import annotations

from pathlib import Path
import hashlib
import json

from scripts.audit_publication import scan_paths
from scripts.publication_policy import DEFAULT_POLICY


ROOT = Path(__file__).resolve().parents[1]


def test_agpl_license_is_present() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")

    assert license_text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in license_text
    assert "AGPL-3.0-or-later" in notice


def test_notice_declares_independence() -> None:
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")

    assert "Ícaro de Souza Mariano" in notice
    assert "independent and unofficial" in notice.casefold()
    assert "patches/WAHA_CORE_LICENSE" in notice
    assert "patches/WAHA_FORK.md" in notice


def test_package_metadata_has_no_organization_identity() -> None:
    control = ROOT / "package/DEBIAN/control"
    text = control.read_text(encoding="utf-8")

    assert "Maintainer: GLPI Workflow Assistant Project" in text
    assert scan_paths([control], DEFAULT_POLICY).findings == ()


def test_support_document_promises_no_sla() -> None:
    support = (ROOT / "SUPPORT.md").read_text(encoding="utf-8").casefold()

    assert "best effort" in support
    assert "no service-level agreement" in support


def test_release_version_is_consistent() -> None:
    from scripts.release_metadata import RELEASE

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    extension = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    control = (ROOT / "package/DEBIAN/control").read_text(encoding="utf-8")

    assert RELEASE.public_version == "3.4.0-beta.1"
    assert RELEASE.debian_version == "3.4.0~beta.1-1"
    assert RELEASE.bridge_version == "2.4.0"
    assert package["version"] == RELEASE.public_version
    assert extension["version"] == RELEASE.bridge_version
    assert f"Version: {RELEASE.debian_version}" in control


def test_artifact_names_use_beta_version() -> None:
    from scripts.release_metadata import RELEASE

    assert set(RELEASE.artifact_names) == {
        "glpi-assistant_3.4.0~beta.1-1_all.deb",
        "glpi-assistant-bridge_2.4.0_chromium.zip",
        "glpi-assistant-bridge_2.4.0_firefox-dev.xpi",
        "package-manifest.json",
        "sbom.cdx.json",
        "SHA256SUMS",
    }


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    from scripts.build_portfolio import build_release

    first = tmp_path / "first"
    second = tmp_path / "second"
    build_release(first)
    build_release(second)

    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.iterdir()
    } == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.iterdir()
    }


def test_checksums_cover_every_release_artifact(tmp_path: Path) -> None:
    from scripts.build_portfolio import build_release
    from scripts.release_metadata import RELEASE

    output = tmp_path / "dist"
    build_release(output)
    checksum_names = {
        line.split("  ", 1)[1]
        for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    }

    assert checksum_names == set(RELEASE.artifact_names) - {"SHA256SUMS"}


def test_sbom_scope_is_explicit(tmp_path: Path) -> None:
    from scripts.build_portfolio import build_release

    output = tmp_path / "dist"
    build_release(output)
    sbom = json.loads((output / "sbom.cdx.json").read_text(encoding="utf-8"))
    properties = {item["name"]: item["value"] for item in sbom["metadata"]["properties"]}

    assert sbom["bomFormat"] == "CycloneDX"
    assert properties["glpi-workflow-assistant:scope"] == "Python and npm application dependencies only"
    assert properties["glpi-workflow-assistant:excluded"] == "Docker OS, browser runtime and WAHA transitive components"
