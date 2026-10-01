from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.audit_publication import scan_paths
from scripts.publication_policy import DEFAULT_POLICY, normalize_text


def _blocked(*parts: str) -> str:
    return "".join(parts)


def test_blocks_identifier_casefolded(tmp_path: Path) -> None:
    candidate = tmp_path / "notes.txt"
    candidate.write_text(_blocked("TEEM"[::-1], " AIGOLONCET"[::-1]), encoding="utf-8")

    report = scan_paths([candidate], DEFAULT_POLICY)

    assert [finding.rule for finding in report.findings] == ["blocked-identifier"]


def test_blocks_identifier_with_separators(tmp_path: Path) -> None:
    candidate = tmp_path / "notes.txt"
    candidate.write_text(_blocked("T.E.E.M"[::-1], "-AIGOLONCET"[::-1]), encoding="utf-8")

    report = scan_paths([candidate], DEFAULT_POLICY)

    assert len(report.findings) == 1
    assert normalize_text(_blocked("T.E.E.M"[::-1], "-", "AIGOLONCET"[::-1])) == _blocked(
        "teem"[::-1], " ", "aigoloncet"[::-1]
    )


def test_scans_nested_text_in_zip(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "bridge.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/config.txt", _blocked("anadrev"[::-1], "ksed"[::-1]))

    report = scan_paths([archive], DEFAULT_POLICY)

    assert report.findings[0].path.endswith("bridge.zip!nested/config.txt")
    assert report.findings[0].rule == "blocked-identifier"


def test_scans_debian_payload(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    (package / "DEBIAN").mkdir(parents=True)
    (package / "usr/share/example").mkdir(parents=True)
    (package / "DEBIAN/control").write_text(
        "Package: publication-audit-fixture\n"
        "Version: 1.0\nArchitecture: all\nMaintainer: Example\n"
        "Description: fixture\n",
        encoding="utf-8",
    )
    (package / "usr/share/example/private.txt").write_text(
        _blocked("gm"[::-1], "til"[::-1]), encoding="utf-8"
    )
    artifact = tmp_path / "fixture.deb"
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(package), str(artifact)],
        check=True,
        capture_output=True,
        text=True,
    )

    report = scan_paths([artifact], DEFAULT_POLICY)

    assert any(
        finding.rule == "blocked-identifier"
        and "usr/share/example/private.txt" in finding.path
        for finding in report.findings
    )


def test_allows_documentation_domains(tmp_path: Path) -> None:
    candidate = tmp_path / "example.txt"
    candidate.write_text(
        "https://glpi.example.invalid user@example.com 192.0.2.10 127.0.0.1",
        encoding="utf-8",
    )

    report = scan_paths([candidate], DEFAULT_POLICY)

    assert report.findings == ()


def test_ignores_generated_local_state(tmp_path: Path) -> None:
    ignored = tmp_path / ".venv"
    ignored.mkdir()
    (ignored / "leak.txt").write_text(
        _blocked("teem"[::-1], " aigoloncet"[::-1]), encoding="utf-8"
    )

    report = scan_paths([tmp_path], DEFAULT_POLICY)

    assert report.findings == ()


def test_report_never_echoes_secret_value(tmp_path: Path) -> None:
    secret = "A" * 32
    candidate = tmp_path / "config.txt"
    candidate.write_text(f"App-Token: {secret}", encoding="utf-8")

    report = scan_paths([candidate], DEFAULT_POLICY)
    serialized = json.dumps(report.as_dict(), sort_keys=True)

    assert report.findings[0].rule == "credential"
    assert len(report.findings[0].excerpt_hash) == 64
    assert secret not in serialized
    assert secret not in repr(report)
