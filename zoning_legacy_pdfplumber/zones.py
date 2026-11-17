"""Step 3: read the district list from this PDF only."""

from __future__ import annotations

import re

from zoning.model import Zone
from zoning.reader import PdfDocument
from zoning.textutil import iter_lines, one_sentence

HYPHEN = re.compile(
    r"^(?:((?:Sec(?:tion)?\.?|§)\s*[0-9A-Za-z.\-]+)\s+)?"
    r"([A-Z]{1,4}(?:-[A-Z0-9]{1,4})+)\s*(?:[—–\-]|:)\s+(.+)$"
)
PLAIN = re.compile(
    r"^(?:((?:Sec(?:tion)?\.?|§)\s*[0-9A-Za-z.\-]+)\s+)?"
    r"([A-Z]{1,4}(?:-[A-Z0-9]{1,4})+)\s+(.+District)\s*$"
)
SHORT = re.compile(r"^([A-Z]{2,4})\s*(?:[—–\-]|:)\s+(.+District)\s*$")
NAME_ONLY = re.compile(
    r"^((?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}|of|and|the)){0,6})\s+District\s*$"
)
TRIGGER = re.compile(
    r"districts established|zoning districts|districts and map codes|classification of districts",
    re.I,
)
STOP_CODES = {
    "THE", "AND", "FOR", "THIS", "THAT", "WITH", "FROM", "CHAPTER", "SECTION",
    "ARTICLE", "TABLE", "ZONE", "ZONES", "CODE", "CITY", "TOWN", "IN", "OF",
    "OR", "TO", "BY", "AT", "ON", "AN", "BE", "IS", "AS", "NO", "YES",
}


def find_zones(doc: PdfDocument) -> tuple[list[Zone], bool]:
    found: dict[str, Zone] = {}
    order: list[str] = []
    pending: Zone | None = None

    def save(zone: Zone | None) -> None:
        if zone is None or not zone.zone_code:
            return
        current = found.get(zone.zone_code)
        if current is None:
            found[zone.zone_code] = zone
            order.append(zone.zone_code)
            return
        if not current.zone_meaning and zone.zone_meaning:
            current.zone_meaning = zone.zone_meaning
        if len(zone.zone_name) > len(current.zone_name):
            current.zone_name = zone.zone_name
            current.zone_group = zone.zone_group

    lines = list(iter_lines(doc.pages))
    for index, (page, line) in enumerate(lines):
        parsed = _parse_zone_line(line, page)
        if parsed:
            save(pending)
            pending = parsed
            continue
        if pending and re.search(r"\b(purpose|intent)\b", line, re.I):
            pending.zone_meaning = one_sentence(line)
            save(pending)
            pending = None
            continue
        if pending and index + 1 < len(lines) and lines[index + 1][0] != page:
            save(pending)
            pending = None
    save(pending)

    invented = False
    if len(order) < 2:
        named = _names_without_codes(lines)
        if len(named) >= 3:
            invented = True
            for page, name in named:
                code = _initials(name, set(found))
                zone = _make(code, name, "", page)
                save(zone)
    return [found[code] for code in order if code in found], invented


def group_for(name: str) -> str:
    text = name.lower()
    if "overlay" in text:
        return "Overlay"
    if "mixed use" in text or "mixed-use" in text:
        return "Mixed Use"
    if any(word in text for word in ("industrial", "manufactur", "warehouse")):
        return "Industrial"
    if any(word in text for word in ("commercial", "business", "retail", "office")):
        return "Commercial"
    if any(word in text for word in ("resid", "single-family", "single family", "two-family", "duplex", "multi-family", "apartment")):
        return "Residential"
    if any(word in text for word in ("agricult", "conservation", "open space")):
        return "Special"
    return ""


def type_for(name: str, code: str) -> str:
    text = f"{name} {code}".lower()
    if "overlay" in text:
        return "Overlay district"
    if "combining" in text:
        return "Combining district"
    if any(word in text for word in ("planned development", "pud", "special district", "special purpose")):
        return "Special district"
    return "Base district"


def _parse_zone_line(line: str, page: int) -> Zone | None:
    match = HYPHEN.match(line) or PLAIN.match(line)
    if match:
        return _make(match.group(2), match.group(3), match.group(1) or "", page)
    short = SHORT.match(line)
    if short and short.group(1) not in STOP_CODES:
        return _make(short.group(1), short.group(2), "", page)
    return None


def _make(code: str, name: str, section: str, page: int) -> Zone | None:
    name = _clean_name(name)
    if not name:
        return None
    source = " ".join(part for part in (section.strip(), f"p. {page}") if part)
    meaning = ""
    return Zone(
        zone_code=code,
        zone_name=name,
        zone_group=group_for(name),
        zone_type=type_for(name, code),
        zone_meaning=meaning,
        source_section=source,
        page=page,
    )


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" .-")
    name = re.sub(r"\.{2,}.*$", "", name).strip(" .-")
    name = re.sub(r"\s+\d{1,4}$", "", name).strip()
    if not name or len(name) > 90 or len(name.split()) > 14:
        return ""
    lowered = f" {name.lower()} "
    if " shall " in lowered or lowered.strip().startswith("the "):
        return ""
    return name


def _names_without_codes(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    collected: list[tuple[int, str]] = []
    armed = 0
    for page, line in lines:
        if TRIGGER.search(line):
            armed = 40
            continue
        if armed <= 0:
            continue
        armed -= 1
        match = NAME_ONLY.match(line)
        if match:
            collected.append((page, match.group(1).strip()))
        elif collected and line.endswith("."):
            break
    return collected


def _initials(name: str, taken: set[str]) -> str:
    skip = {"of", "the", "and", "district"}
    letters = [word[0].upper() for word in re.findall(r"[A-Za-z0-9]+", name) if word.lower() not in skip]
    base = "".join(letters)[:6] or "Z"
    code = base
    number = 2
    while code in taken:
        code = f"{base}{number}"
        number += 1
    taken.add(code)
    return code
