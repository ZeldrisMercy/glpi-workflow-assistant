from __future__ import annotations

from pathlib import Path
import hashlib
import json
import struct
import re
import xml.etree.ElementTree as ET
import yaml

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


def test_packaged_runtime_version_is_consistent() -> None:
    from scripts.release_metadata import RELEASE

    main = (ROOT / "package/usr/lib/glpi-assistant/app/main.py").read_text(encoding="utf-8")
    prompt = (ROOT / "package/usr/lib/glpi-assistant/app/PROMPT_FORMALIZACAO.md").read_text(encoding="utf-8")

    assert f'VERSION = "{RELEASE.public_version}"' in main
    assert "3.4.0-rc3" not in prompt.casefold()
    assert "3.4.0-rc4" not in prompt.casefold()


def test_container_image_tag_is_consistent() -> None:
    from scripts.release_metadata import RELEASE

    postinst = (ROOT / "package/DEBIAN/postinst").read_text(encoding="utf-8")
    runner = (ROOT / "package/usr/lib/glpi-assistant/run-container.sh").read_text(encoding="utf-8")
    expected = f"IMAGE=glpi-assistant:{RELEASE.public_version}"

    assert expected in postinst
    assert expected in runner


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


def test_social_preview_dimensions() -> None:
    data = (ROOT / "docs/assets/brand/social-preview.png").read_bytes()

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1280, 640)


def test_svg_assets_have_titles() -> None:
    expected = {
        ROOT / "docs/assets/brand/mark.svg",
        ROOT / "docs/assets/brand/hero.svg",
        ROOT / "docs/assets/brand/architecture-overview.svg",
        ROOT / "docs/assets/brand/social-preview.svg",
        ROOT / "package/usr/lib/glpi-assistant/app/static/favicon.svg",
        ROOT / "extension/icons/icon.svg",
    }

    for path in expected:
        root = ET.parse(path).getroot()
        title = root.find("{http://www.w3.org/2000/svg}title")
        assert title is not None and title.text and title.text.strip(), path


def test_readmes_link_each_other() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    portuguese = (ROOT / "README.pt-BR.md").read_text(encoding="utf-8")

    assert "[Português](README.pt-BR.md)" in english
    assert "[English](README.md)" in portuguese


def test_readmes_name_beta_and_agpl() -> None:
    for path in (ROOT / "README.md", ROOT / "README.pt-BR.md"):
        text = path.read_text(encoding="utf-8").casefold()
        assert "beta" in text
        assert "agpl-3.0-or-later" in text
        assert "independent and unofficial" in text or "independente e não oficial" in text


def test_readme_claims_match_release_manifest() -> None:
    manifest = json.loads((ROOT / "docs/project/release-manifest.json").read_text(encoding="utf-8"))
    for path in (ROOT / "README.md", ROOT / "README.pt-BR.md"):
        text = path.read_text(encoding="utf-8")
        assert manifest["version"] in text
        assert manifest["bridge_version"] in text
        assert "RC3" not in text and "RC4" not in text
        assert "tests passed" not in text.casefold() and "testes aprovados" not in text.casefold()


def test_required_public_docs_exist() -> None:
    required = {
        "docs/getting-started/quick-start.md",
        "docs/getting-started/debian-installation.md",
        "docs/getting-started/browser-bridge.md",
        "docs/getting-started/configuration.md",
        "docs/getting-started/compatibility.md",
        "docs/getting-started/demo-data.md",
        "docs/getting-started/troubleshooting.md",
        "docs/getting-started/operations-and-recovery.md",
        "docs/getting-started/structured-input.md",
        "docs/security/security-model.md",
        "docs/security/threat-model.md",
        "docs/security/privacy.md",
        "docs/architecture/api-contract.md",
        "docs/architecture/evidence-model.md",
        "docs/architecture/proactive-ticket-creation.md",
        "docs/architecture/waha-integration.md",
        "docs/project/case-study.md",
        "docs/project/roadmap.md",
        "docs/project/known-limitations.md",
        "docs/project/release-process.md",
        "docs/project/source-map.md",
        "docs/project/testing.md",
        "docs/project/validation.md",
        "docs/project/screenshot-methodology.md",
    }

    assert not {path for path in required if not (ROOT / path).is_file()}


def test_docs_have_no_rc_or_obsolete_version_claims() -> None:
    obsolete_paths = {
        "docs/CHANGELOG_3.4.0-rc4.md",
        "docs/INSTALACAO_E_ROLLBACK.md",
        "docs/PROMPT_FORMALIZACAO_3.2.md",
        "docs/PROMPT_FORMALIZACAO_3.4.0-rc4.md",
        "docs/SEGURANCA_ESTABILIDADE_3.4.0-rc4.md",
        "docs/VALIDACAO_3.4.0-rc4.json",
        "docs/WHATSAPP_WAHA.md",
        "docs/publication-checklist.md",
        "docs/release-draft.md",
    }
    public_docs = [ROOT / "README.md", ROOT / "README.pt-BR.md", *sorted((ROOT / "docs").rglob("*.md"))]

    assert not {path for path in obsolete_paths if (ROOT / path).exists()}
    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:RC3|RC4|3\.3\.0|3\.4\.0[-~]rc4)\b", text, re.IGNORECASE), path


def test_case_study_links_real_evidence() -> None:
    text = (ROOT / "docs/project/case-study.md").read_text(encoding="utf-8")

    assert "../assets/screenshots/README.md" in text
    assert "../assets/screenshots/capture-report.json" in text
    assert "../assets/screenshots/ocr-report.json" in text
    assert "validation-matrix.md" in text
    assert "internal-audit/" not in text


def test_docs_do_not_reference_missing_paths() -> None:
    markdown_files = [ROOT / "README.md", ROOT / "README.pt-BR.md", *sorted((ROOT / "docs").rglob("*.md"))]
    link_pattern = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")

    for source in markdown_files:
        for raw_target in link_pattern.findall(source.read_text(encoding="utf-8")):
            target = raw_target.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (source.parent / target).resolve().exists(), f"{source.relative_to(ROOT)} -> {target}"


def _workflow(path: str) -> dict[str, object]:
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_ci_invokes_every_release_gate() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    serialized = json.dumps(workflow)

    for command in (
        "pytest tests qa/test_waha_installer.py",
        "check_javascript.py",
        "audit_publication.py .",
        "pip_audit",
        "npm audit",
        "missing_paths",
        "build_portfolio.py",
        "verify_release.py dist",
        "sha256sum --check SHA256SUMS",
    ):
        assert command in serialized


def test_workflows_use_minimal_permissions() -> None:
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    for path in workflows:
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        permissions = workflow.get("permissions", {})
        assert permissions.get("contents") == "read", path
        assert "write-all" not in json.dumps(workflow), path


def test_workflows_pin_actions_to_commit_shas() -> None:
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if "uses" not in step:
                    continue
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"]), (path, step["uses"])


def test_release_requires_beta_tag() -> None:
    workflow = _workflow(".github/workflows/release.yml")
    serialized = json.dumps(workflow)

    assert "v3.4.0-beta.1" in serialized
    assert "workflow_dispatch" in serialized
    assert "tags" in serialized
    assert "branches" not in workflow["on"].get("push", {})


def test_codeql_covers_python_and_javascript() -> None:
    workflow = _workflow(".github/workflows/codeql.yml")
    serialized = json.dumps(workflow)

    assert "python" in serialized
    assert "javascript-typescript" in serialized
    assert "security-events" in serialized
    assert "write" in serialized
    assert "continue-on-error" in serialized
    assert "github.event.repository.private" in serialized


def test_dependabot_covers_pip_npm_actions() -> None:
    config = yaml.load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}

    assert ecosystems == {"pip", "npm", "github-actions"}
    assert all(update["schedule"]["interval"] == "monthly" for update in config["updates"])
