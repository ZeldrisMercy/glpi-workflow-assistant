"""OCR the public screenshot gallery and apply the publication identity policy."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

try:
    from scripts.audit_publication import _scan_text
    from scripts.publication_policy import DEFAULT_POLICY
except ModuleNotFoundError:
    from audit_publication import _scan_text
    from publication_policy import DEFAULT_POLICY


@dataclass(frozen=True)
class OcrImage:
    file: str
    sha256: str
    text: str


@dataclass(frozen=True)
class OcrReport:
    engine: str
    images: tuple[OcrImage, ...]
    blocking_findings: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {"engine": self.engine, "images": [asdict(image) for image in self.images], "blocking_findings": list(self.blocking_findings)}


def _engine_version() -> str:
    executable = shutil.which("tesseract")
    if not executable:
        raise RuntimeError("Tesseract OCR is required by the publication gate")
    result = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    return result.stdout.splitlines()[0].strip().lower()


def _ocr(path: Path) -> str:
    result = subprocess.run(["tesseract", str(path), "stdout", "-l", "eng", "--psm", "6"], check=True, capture_output=True, text=True)
    return re.sub(r"[ \t]+", " ", result.stdout.replace("\r\n", "\n")).strip()


def ocr_screenshots(paths: Sequence[Path]) -> OcrReport:
    images: list[OcrImage] = []
    findings: list[dict[str, str]] = []
    for path in sorted(paths, key=lambda item: item.name):
        data = path.read_bytes()
        text = _ocr(path)
        images.append(OcrImage(file=path.name, sha256=hashlib.sha256(data).hexdigest(), text=text))
        for finding in _scan_text(text, path.name, DEFAULT_POLICY):
            findings.append(asdict(finding))
    return OcrReport(engine=_engine_version(), images=tuple(images), blocking_findings=tuple(sorted(findings, key=lambda item: (item["path"], item["rule"], item["excerpt_hash"]))))


def main(argv: Sequence[str] | None = None) -> int:
    supplied = list(argv if argv is not None else sys.argv[1:])
    directory = Path(supplied[0]) if supplied else Path("docs/assets/screenshots")
    paths = sorted(directory.glob("*.png"))
    if not paths:
        raise RuntimeError(f"No PNG screenshots found in {directory}")
    report = ocr_screenshots(paths)
    (directory / "ocr-report.json").write_text(json.dumps(report.as_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ocr audit: {len(report.images)} image(s), {len(report.blocking_findings)} blocking finding(s)")
    return 1 if report.blocking_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
