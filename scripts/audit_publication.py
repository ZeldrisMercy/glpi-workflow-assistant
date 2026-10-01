from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from scripts.publication_policy import DEFAULT_POLICY, PublicationPolicy, normalize_text
except ModuleNotFoundError:  # Direct execution from scripts/.
    from publication_policy import DEFAULT_POLICY, PublicationPolicy, normalize_text


MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    excerpt_hash: str


@dataclass(frozen=True)
class AuditReport:
    findings: tuple[Finding, ...]

    def as_dict(self) -> dict[str, object]:
        return {"findings": [asdict(finding) for finding in self.findings]}


def _ignored(path: Path, policy: PublicationPolicy) -> bool:
    return any(
        fnmatch.fnmatch(part, pattern)
        for part in path.parts
        for pattern in policy.ignored_paths
    )


def _iter_files(paths: Sequence[Path], policy: PublicationPolicy) -> Iterable[Path]:
    seen: set[Path] = set()
    for supplied in paths:
        path = supplied.resolve()
        if not path.exists() or _ignored(path, policy):
            continue
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink() and not _ignored(candidate, policy):
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate


def _finding(path: str, rule: str, matched: str) -> Finding:
    digest = hashlib.sha256(matched.encode("utf-8", errors="replace")).hexdigest()
    return Finding(path=path, rule=rule, excerpt_hash=digest)


def _scan_text(text: str, display_path: str, policy: PublicationPolicy) -> list[Finding]:
    findings: list[Finding] = []
    normalized = normalize_text(text)
    compact = normalized.replace(" ", "")
    for blocked in policy.blocked_identifiers:
        target = normalize_text(blocked)
        if target in normalized or target.replace(" ", "") in compact:
            findings.append(_finding(display_path, "blocked-identifier", blocked))
    for pattern in policy.secret_patterns:
        for match in pattern.finditer(text):
            findings.append(_finding(display_path, "credential", match.group(0)))
    return findings


def _decode_and_scan(data: bytes, display_path: str, policy: PublicationPolicy) -> list[Finding]:
    if len(data) > MAX_MEMBER_BYTES or b"\x00" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return _scan_text(text, display_path, policy)


def _scan_zip(path: Path, policy: PublicationPolicy) -> list[Finding]:
    findings: list[Finding] = []
    consumed = 0
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir() or member.file_size > MAX_MEMBER_BYTES:
                continue
            consumed += member.file_size
            if consumed > MAX_ARCHIVE_BYTES:
                break
            findings.extend(
                _decode_and_scan(archive.read(member), f"{path}!{member.filename}", policy)
            )
    return findings


def _scan_tar_bytes(data: bytes, archive_path: Path, label: str, policy: PublicationPolicy) -> list[Finding]:
    findings: list[Finding] = []
    consumed = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.size > MAX_MEMBER_BYTES:
                continue
            consumed += member.size
            if consumed > MAX_ARCHIVE_BYTES:
                break
            handle = archive.extractfile(member)
            if handle is not None:
                findings.extend(
                    _decode_and_scan(
                        handle.read(), f"{archive_path}!{label}/{member.name}", policy
                    )
                )
    return findings


def _scan_deb(path: Path, policy: PublicationPolicy) -> list[Finding]:
    findings: list[Finding] = []
    for option, label in (("--fsys-tarfile", "data"), ("--ctrl-tarfile", "control")):
        process = subprocess.run(
            ["dpkg-deb", option, str(path)],
            check=True,
            capture_output=True,
        )
        findings.extend(_scan_tar_bytes(process.stdout, path, label, policy))
    return findings


def scan_paths(paths: Sequence[Path], policy: PublicationPolicy) -> AuditReport:
    findings: list[Finding] = []
    for path in _iter_files(paths, policy):
        suffix = path.suffix.casefold()
        if suffix in {".zip", ".xpi"}:
            findings.extend(_scan_zip(path, policy))
        elif suffix == ".deb":
            findings.extend(_scan_deb(path, policy))
        else:
            findings.extend(_decode_and_scan(path.read_bytes(), str(path), policy))
    return AuditReport(findings=tuple(sorted(findings, key=lambda item: (item.path, item.rule, item.excerpt_hash))))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a public candidate without echoing matched secrets.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = scan_paths(args.paths, DEFAULT_POLICY)
    payload = report.as_dict()
    payload["finding_count"] = len(report.findings)
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"publication audit: {len(report.findings)} blocking finding(s)")
        for finding in report.findings:
            print(f"- {finding.path}: {finding.rule} [{finding.excerpt_hash[:12]}]")
    return 1 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
