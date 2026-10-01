from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Sequence

try:
    from scripts.release_metadata import RELEASE
except ModuleNotFoundError:
    from release_metadata import RELEASE


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release(output: Path) -> dict[str, object]:
    expected = set(RELEASE.artifact_names)
    actual = {path.name for path in output.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError(f"release artifact set mismatch: expected {sorted(expected)}, got {sorted(actual)}")

    checksum_lines = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = dict(line.split("  ", 1)[::-1] for line in checksum_lines)
    if set(checksums) != expected - {"SHA256SUMS"}:
        raise ValueError("checksum coverage does not match release artifacts")
    for name, digest in checksums.items():
        if _sha256(output / name) != digest:
            raise ValueError(f"checksum mismatch: {name}")

    manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != RELEASE.public_version or manifest.get("debian_version") != RELEASE.debian_version:
        raise ValueError("package manifest version mismatch")
    if manifest.get("rebuild_byte_identical") is not True:
        raise ValueError("package rebuild was not byte-identical")

    package_name = f"glpi-assistant_{RELEASE.debian_version}_all.deb"
    debian_version = subprocess.check_output(
        ["dpkg-deb", "-f", str(output / package_name), "Version"], text=True
    ).strip()
    if debian_version != RELEASE.debian_version:
        raise ValueError("Debian metadata version mismatch")

    sbom = json.loads((output / "sbom.cdx.json").read_text(encoding="utf-8"))
    properties = {item["name"]: item["value"] for item in sbom["metadata"]["properties"]}
    if sbom.get("bomFormat") != "CycloneDX" or properties.get("glpi-workflow-assistant:scope") != "Python and npm application dependencies only":
        raise ValueError("SBOM scope is missing or invalid")

    return {
        "version": RELEASE.public_version,
        "debian_version": RELEASE.debian_version,
        "artifacts": sorted(expected),
        "checksums_verified": len(checksums),
        "rebuild_byte_identical": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the exact public beta artifact set.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_release(args.output)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"release verification failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
