"""Build deterministic, inspectable public-beta artifacts without installation."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile

try:
    from scripts.release_metadata import RELEASE
except ModuleNotFoundError:
    from release_metadata import RELEASE


ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1790726400


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_debian(output: Path) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary) / "package"
        shutil.copytree(ROOT / "package", stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        control = stage / "DEBIAN/control"
        rows = control.read_text(encoding="utf-8").splitlines()
        control.write_text(
            "\n".join(
                f"Version: {RELEASE.debian_version}" if row.startswith("Version:") else row
                for row in rows
            ) + "\n",
            encoding="utf-8",
        )
        docs = stage / "usr/share/doc/glpi-assistant"
        docs.mkdir(parents=True)
        for source in (
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / "NOTICE.md",
            ROOT / "SUPPORT.md",
            ROOT / "docs/getting-started/quick-start.md",
            ROOT / "docs/project/known-limitations.md",
        ):
            shutil.copy2(source, docs / source.name)
        for script in (stage / "DEBIAN").iterdir():
            if script.name != "control":
                script.chmod(0o755)
                subprocess.run(["bash", "-n", str(script)], check=True)
        for script in (stage / "usr/bin").iterdir():
            script.chmod(0o755)
            if script.name != "glpi-assistant-backup":
                subprocess.run(["bash", "-n", str(script)], check=True)
        runner = stage / "usr/lib/glpi-assistant/run-container.sh"
        runner.chmod(0o755)
        subprocess.run(["bash", "-n", str(runner)], check=True)
        for path in sorted(stage.rglob("*")):
            os.utime(path, (EPOCH, EPOCH))
        os.utime(stage, (EPOCH, EPOCH))
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)],
            check=True,
            env={**os.environ, "SOURCE_DATE_EPOCH": str(EPOCH)},
            stdout=subprocess.DEVNULL,
        )
        version = subprocess.check_output(["dpkg-deb", "-f", str(output), "Version"], text=True).strip()
        if version != RELEASE.debian_version:
            raise RuntimeError("Debian version mismatch")
        return [
            {
                "path": str(path.relative_to(stage)),
                "mode": oct(path.stat().st_mode & 0o777),
                "sha256": _sha256(path),
            }
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        ]


def build_bridges(output: Path) -> None:
    manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != RELEASE.bridge_version:
        raise RuntimeError("Browser Bridge version mismatch")
    for chromium in (False, True):
        suffix = "chromium.zip" if chromium else "firefox-dev.xpi"
        config = json.loads(json.dumps(manifest))
        if chromium:
            config.pop("browser_specific_settings", None)
            config["background"] = {"service_worker": "chromium-worker.js"}
            config["minimum_chrome_version"] = "148"
        target = output / f"glpi-assistant-bridge_{RELEASE.bridge_version}_{suffix}"
        entries = {
            str(path.relative_to(ROOT / "extension")): path.read_bytes()
            for path in (ROOT / "extension").rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        entries["manifest.json"] = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode()
        if chromium:
            entries["chromium-worker.js"] = b"importScripts('browser-compat.js', 'background.js');\n"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                info = zipfile.ZipInfo(name, (2026, 9, 30, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)


def _components() -> list[dict[str, str]]:
    components: dict[tuple[str, str, str], dict[str, str]] = {}
    for line in (ROOT / "package/usr/lib/glpi-assistant/app/requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        raw_name, version = line.split("==", 1)
        name = raw_name.split("[", 1)[0]
        components[("library", name.casefold(), version)] = {
            "type": "library", "name": name, "version": version, "purl": f"pkg:pypi/{name.casefold()}@{version}"
        }
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    for path, data in lock.get("packages", {}).items():
        if not path.startswith("node_modules/") or not data.get("version"):
            continue
        name = path.removeprefix("node_modules/")
        component = {
            "type": "library", "name": name, "version": data["version"],
            "purl": f"pkg:npm/{name.replace('@', '%40')}@{data['version']}",
        }
        if data.get("license"):
            component["licenses"] = [{"license": {"id": data["license"]}}]
        components[("library", name.casefold(), data["version"])] = component
    return [components[key] for key in sorted(components)]


def write_sbom(output: Path) -> None:
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'glpi-workflow-assistant/' + RELEASE.public_version)}",
        "version": 1,
        "metadata": {
            "timestamp": "2026-09-30T00:00:00Z",
            "component": {
                "type": "application",
                "name": "glpi-workflow-assistant",
                "version": RELEASE.public_version,
                "licenses": [{"license": {"id": "AGPL-3.0-or-later"}}],
            },
            "properties": [
                {"name": "glpi-workflow-assistant:scope", "value": "Python and npm application dependencies only"},
                {"name": "glpi-workflow-assistant:excluded", "value": "Docker OS, browser runtime and WAHA transitive components"},
            ],
        },
        "components": _components(),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_release(output: Path, *, write_project_manifest: bool = False) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    for candidate in output.glob("glpi-assistant-bridge_*"):
        if candidate.is_file():
            candidate.unlink()
    for name in RELEASE.artifact_names:
        candidate = output / name
        if candidate.exists():
            candidate.unlink()
    package = output / f"glpi-assistant_{RELEASE.debian_version}_all.deb"
    manifest = build_debian(package)
    with tempfile.TemporaryDirectory() as temporary:
        rebuild = Path(temporary) / package.name
        build_debian(rebuild)
        identical = package.read_bytes() == rebuild.read_bytes()
    if not identical:
        raise RuntimeError("Debian package rebuild differs")
    package_manifest = {
        "version": RELEASE.public_version,
        "debian_version": RELEASE.debian_version,
        "bridge_version": RELEASE.bridge_version,
        "files": manifest,
        "rebuild_byte_identical": True,
    }
    (output / "package-manifest.json").write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build_bridges(output)
    write_sbom(output / "sbom.cdx.json")
    checksum_targets = [path for path in sorted(output.iterdir()) if path.is_file() and path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_targets), encoding="utf-8"
    )
    release_manifest = {
        "version": RELEASE.public_version,
        "debian_version": RELEASE.debian_version,
        "bridge_version": RELEASE.bridge_version,
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in sorted(output.iterdir()) if path.is_file()
        ],
    }
    if write_project_manifest:
        target = ROOT / "docs/project/release-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(release_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**release_manifest, "rebuild_byte_identical": True, "installed": False}


def main() -> None:
    print(json.dumps(build_release(ROOT / "dist", write_project_manifest=True), sort_keys=True))


if __name__ == "__main__":
    main()
