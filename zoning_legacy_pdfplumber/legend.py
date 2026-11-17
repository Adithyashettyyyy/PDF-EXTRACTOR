"""Step 5: read this city's legend and the rule for uses that are not listed."""

from __future__ import annotations

import re

from zoning.model import LegendEntry, UnlistedRule
from zoning.phrases import APPROVAL_BODIES
from zoning.reader import PdfDocument
from zoning.textutil import clean

SYMBOL = r"(blank|—|–|-|−|\*|[A-Z]{1,4})"
LEGEND_LINE = re.compile(
    rf"(?:^|\s)(?P<sym>{SYMBOL})\s*(?:=|means|indicates)\s*(?P<mean>[^.;\n]{{3,100}})",
    re.I,
)
UNLISTED = re.compile(
    r"([^.\n]{0,70}\b(?:uses?\s+not\s+(?:specifically\s+)?listed|unlisted uses?|any use not)[^.\n]{0,100}\.)",
    re.I,
)
BLANK_RULE = re.compile(r"blank(?:\s+cells?)?[^\n]{0,40}(prohibited|not permitted)", re.I)
DASHES = {"—", "–", "-", "−"}


def find_legend(doc: PdfDocument, focus_pages: list[int]) -> tuple[list[LegendEntry], UnlistedRule]:
    numbers = _window(focus_pages, doc.page_count)
    entries: list[LegendEntry] = []
    seen: set[str] = set()
    rule = UnlistedRule()
    for number in numbers:
        text = doc.pages[number - 1]
        for raw in text.splitlines():
            line = clean(raw)
            for match in LEGEND_LINE.finditer(line):
                symbol = _symbol(match.group("sym"))
                if not symbol or symbol in seen:
                    continue
                meaning = clean(match.group("mean"))
                permission = classify_meaning(meaning)
                body = approval_body(line) or approval_body(meaning)
                entries.append(LegendEntry(symbol, permission, meaning, body))
                seen.add(symbol)
                if symbol == "blank" and permission == "Not permitted":
                    rule.blank_is_prohibited = True
        if BLANK_RULE.search(text):
            rule.blank_is_prohibited = True
        if not rule.quote:
            found = UNLISTED.search(clean(text))
            if found:
                rule.quote = found.group(1).strip()
                rule.page = number
                rule.missing_uses_are = missing_from(rule.quote)
    if rule.blank_is_prohibited and rule.missing_uses_are == "Unclear" and not rule.quote:
        rule.missing_uses_are = "Not permitted"
    return entries, rule


def classify_meaning(meaning: str) -> str:
    text = meaning.lower()
    if any(word in text for word in ("not permitted", "prohibited", "not allowed", "unpermitted")):
        return "Not permitted"
    if "temporary" in text:
        return "Temporary"
    if any(word in text for word in ("conditional", "special exception", "special use", "specific use", "cup", "sup")):
        return "Conditional"
    if any(word in text for word in ("condition", "footnote", "supplemental", "limited", "standard", "asterisk")):
        return "Permitted with conditions"
    if any(word in text for word in ("permitted", "allowed", "by right", "by-right")):
        return "Permitted"
    return "Unclear"


def permission_for(symbol: str, legend: list[LegendEntry], rule: UnlistedRule) -> tuple[str, str]:
    """Return the standard permission and the symbol to store."""
    raw = (symbol or "").strip()
    if raw.lower() == "blank" or raw == "":
        if rule.blank_is_prohibited or rule.missing_uses_are == "Not permitted":
            return "Not permitted", "-"
        return rule.missing_uses_are or "Unclear", raw
    entry = lookup(raw, legend)
    if entry:
        permission = entry.permission
        if _has_note(raw) and permission == "Permitted":
            return "Permitted with conditions", raw
        if "/" in raw and permission == "Permitted":
            return "Permitted with conditions", raw
        return permission, raw
    if "/" in raw:
        return "Permitted with conditions", raw
    return "Unclear", raw


def lookup(symbol: str, legend: list[LegendEntry]) -> LegendEntry | None:
    raw = symbol.strip()
    by_symbol = {entry.symbol: entry for entry in legend}
    if raw in by_symbol:
        return by_symbol[raw]
    upper = raw.upper()
    if upper in by_symbol:
        return by_symbol[upper]
    if raw in DASHES:
        for entry in legend:
            if entry.symbol in DASHES:
                return entry
    base = re.match(r"([A-Za-z]{1,4})", raw)
    if base and base.group(1).upper() in by_symbol:
        return by_symbol[base.group(1).upper()]
    return None


def approval_body(text: str) -> str:
    low = text.lower()
    for body in APPROVAL_BODIES:
        if body.lower() in low:
            return body
    return ""


def missing_from(quote: str) -> str:
    text = quote.lower()
    if any(word in text for word in ("prohibited", "not permitted", "not allowed")):
        return "Not permitted"
    if any(word in text for word in ("director", "administrator", "similar")):
        return "Unclear"
    return "Unclear"


def covered_symbols(legend: list[LegendEntry]) -> set[str]:
    return {entry.symbol.upper() for entry in legend} | {entry.symbol for entry in legend}


def symbol_known(symbol: str, legend: list[LegendEntry]) -> bool:
    raw = symbol.strip()
    if not raw or raw in DASHES:
        return True
    return lookup(raw, legend) is not None


def _symbol(value: str) -> str:
    text = value.strip()
    if text.lower() == "blank":
        return "blank"
    if text in DASHES:
        return text
    if text.isalpha():
        return text.upper()
    return text


def _has_note(symbol: str) -> bool:
    return bool(re.search(r"\*|\([A-Za-z0-9]+\)", symbol))


def _window(focus: list[int], count: int) -> list[int]:
    if not focus:
        return list(range(1, min(count, 40) + 1))
    numbers = set()
    for page in focus:
        for number in range(max(1, page - 1), min(count, page + 2) + 1):
            numbers.add(number)
    return sorted(numbers)
