"""Read one code PDF and name the place from its own pages."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber

from zoning.phrases import STATE_ABBR
from zoning.textutil import clean, state_abbr, title_place

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

PLACE_LINE = re.compile(
    r"(City|Town|Village|Township|Borough)\s+of\s+([A-Za-z0-9][A-Za-z0-9 .'\-]{1,60}?)(?:,\s*([A-Za-z][A-Za-z ]{1,40}))?$",
    re.I,
)


class PdfDocument:
    """Text for every page, plus word boxes and ruled tables on the pages we ask for."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._pdf = pdfplumber.open(str(self.path))
        self.page_count = len(self._pdf.pages)
        self.pages: list[str] = []
        self.chars_per_page = 0.0
        self.scanned = False

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None

    def read_text(self) -> None:
        texts: list[str] = []
        total = 0
        for page in self._pdf.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            texts.append(text)
            total += len(text)
        self.pages = texts
        self.chars_per_page = total / max(len(texts), 1)
        self.scanned = bool(texts) and self.chars_per_page < 100

    def words(self, number: int) -> list[dict]:
        try:
            page = self._pdf.pages[number - 1]
            return page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
        except Exception:
            return []

    def ruled_tables(self, number: int) -> list[list[list]]:
        try:
            page = self._pdf.pages[number - 1]
            return page.extract_tables(
                {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 4,
                    "join_tolerance": 4,
                    "intersection_tolerance": 5,
                }
            ) or []
        except Exception:
            return []


def identify_place(pages: list[str], overrides: dict) -> dict:
    place = {"state": "", "municipality": "", "type": "", "county": ""}
    lines = []
    for text in pages[:30]:
        lines.extend(clean(line) for line in text.splitlines() if clean(line))
    for line in lines:
        match = PLACE_LINE.search(line)
        if not match:
            continue
        place["type"] = match.group(1).capitalize()
        place["municipality"] = title_place(match.group(2).strip(" .,-"))
        if match.group(3):
            place["state"] = _match_state(match.group(3))
        break
    for line in lines:
        county = re.search(r"\b([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)\s+County\b", line)
        if county:
            place["county"] = county.group(1)
            break
    if not place["state"]:
        for line in lines[:40]:
            found = _match_state(line)
            if found and line.lower().strip() in STATE_ABBR:
                place["state"] = found
                break
    for key, value in overrides.items():
        if value:
            place[key] = value
    return place


def file_stem(place: dict) -> str:
    state = re.sub(r"[^A-Za-z0-9]", "", place.get("state") or "") or "UnknownState"
    city = re.sub(r"[^A-Za-z0-9]", "", place.get("municipality") or "") or "UnknownCity"
    kind = re.sub(r"[^A-Za-z0-9]", "", place.get("type") or "") or "Place"
    return f"{state}_{city}_{kind}_Zoning"


def _match_state(text: str) -> str:
    words = text.replace(",", " ").split()
    known = set(STATE_ABBR.values())
    for size in (3, 2, 1):
        if len(words) < size:
            continue
        chunk = " ".join(words[:size])
        abbr = state_abbr(chunk)
        if abbr in known:
            return abbr
    return ""
