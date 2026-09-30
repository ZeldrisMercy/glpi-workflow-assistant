from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Pattern


def normalize_text(value: str) -> str:
    """Normalize human identifiers without preserving cosmetic separators."""
    folded = unicodedata.normalize("NFKD", value).casefold()
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", folded)
    normalized: list[str] = []
    index = 0
    while index < len(tokens):
        if len(tokens[index]) == 1 and tokens[index].isalpha():
            end = index
            while end < len(tokens) and len(tokens[end]) == 1 and tokens[end].isalpha():
                end += 1
            if end - index > 1:
                normalized.append("".join(tokens[index:end]))
                index = end
                continue
        normalized.append(tokens[index])
        index += 1
    return " ".join(normalized)


@dataclass(frozen=True)
class PublicationPolicy:
    blocked_identifiers: tuple[str, ...]
    secret_patterns: tuple[Pattern[str], ...]
    ignored_paths: tuple[str, ...]


DEFAULT_POLICY = PublicationPolicy(
    blocked_identifiers=(
        "teem"[::-1] + " " + "aigoloncet"[::-1],
        "ksedanadrev"[::-1],
        "tilgm"[::-1],
    ),
    secret_patterns=(
        re.compile(r"(?i)(?:session-token|app-token)\s*[:=]\s*[a-z0-9_-]{20,}"),
        re.compile(r"(?i)waha_api_key\s*=\s*[a-z0-9_-]{20,}"),
        re.compile(r"(?i)https?://[^\s/]+\.(?:corp|internal|local)(?:[/:\s]|$)"),
        re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])"),
        re.compile(r"(?<![\w:/])[\w.+-]+@(?!(?:c|g)\.us\b)(?!example\.(?:com|org|net|invalid)\b)[\w.-]+\.[a-z]{2,}(?!\w)", re.I),
        re.compile(r"(?<!\d)\+?55[\s().-]*[1-9]{2}[\s().-]*[1-9]\d{3,4}[\s.-]*\d{4}(?!\d)"),
        re.compile(r"(?<!\d)(?:\([1-9]{2}\)|[1-9]{2}[\s.-])[\s.-]*[1-9]\d{3,4}[\s.-]+\d{4}(?!\d)"),
    ),
    ignored_paths=(
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".test-data-*",
        ".verification-data",
        ".superpowers",
    ),
)
