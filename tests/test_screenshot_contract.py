from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.capture_portfolio_screenshots import EXPECTED_SCREENSHOTS, enforce_network_boundary

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "demo" / "screenshot-scenarios.json"
GALLERY = ROOT / "docs" / "assets" / "screenshots"


class _Request:
    url = "https://tickets.example.invalid/api/ticket/900001"


class _Route:
    request = _Request()

    def __init__(self) -> None:
        self.aborted = False
        self.continued = False

    def abort(self) -> None:
        self.aborted = True

    def continue_(self) -> None:
        self.continued = True


def _scenario_document() -> dict:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))


def test_gallery_has_eight_named_scenarios() -> None:
    scenarios = _scenario_document()["scenarios"]
    assert tuple(item["file"] for item in scenarios) == EXPECTED_SCREENSHOTS
    assert len(set(item["name"] for item in scenarios)) == 8
    for filename in EXPECTED_SCREENSHOTS:
        with Image.open(GALLERY / filename) as image:
            assert image.size == (1440, 1000)


def test_all_scenarios_are_marked_synthetic() -> None:
    scenarios = _scenario_document()["scenarios"]
    assert scenarios
    assert all(item.get("synthetic") is True for item in scenarios)
    assert all(item.get("real_writes") == 0 for item in scenarios)


def test_capture_blocks_non_loopback_requests() -> None:
    route = _Route()
    blocked: list[str] = []
    enforce_network_boundary(route, blocked)
    assert route.aborted is True
    assert route.continued is False
    assert blocked == [_Request.url]


def test_capture_report_records_zero_remote_writes() -> None:
    report = json.loads((GALLERY / "capture-report.json").read_text(encoding="utf-8"))
    assert report["captures"] == list(EXPECTED_SCREENSHOTS)
    assert report["real_glpi_writes"] == 0
    assert report["external_requests_fulfilled"] == 0
    assert report["page_errors"] == []


def test_ocr_report_covers_every_png() -> None:
    report = json.loads((GALLERY / "ocr-report.json").read_text(encoding="utf-8"))
    assert tuple(item["file"] for item in report["images"]) == EXPECTED_SCREENSHOTS
    assert all(len(item["sha256"]) == 64 for item in report["images"])
    assert report["engine"].startswith("tesseract ")
    assert report["blocking_findings"] == []


def test_optional_messaging_caption_does_not_claim_delivery() -> None:
    scenario = _scenario_document()["scenarios"][-1]
    caption = scenario["caption"].casefold()
    assert scenario["file"] == "08-messaging-status.png"
    assert "simulad" in caption
    for misleading in ("entregue", "enviado com sucesso", "delivered", "sent successfully"):
        assert misleading not in caption


def test_architecture_documents_contain_six_scoped_diagrams() -> None:
    architecture = ROOT / "docs" / "architecture"
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(architecture.glob("*.md")))
    assert text.count("```mermaid") == 6
    for concept in (
        "System overview",
        "Trust boundaries",
        "Existing-ticket closure",
        "Proactive creation",
        "Approval invalidation",
        "Optional messaging",
    ):
        assert concept in text
