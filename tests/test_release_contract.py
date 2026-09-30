from __future__ import annotations

from pathlib import Path

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
