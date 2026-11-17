"""Steps 1 and 2: name the ordinance, then decide whether zoning is in this PDF."""

from __future__ import annotations

import re

from zoning.model import Check, GateResult, SourceInfo
from zoning.phrases import (
    CHAPTER_PHRASES,
    POINTER_PHRASES,
    PUBLICATION_NAMES,
    USE_LIST_PHRASES,
    ZONE_LIST_PHRASES,
    ZONING_PHRASES,
)
from zoning.reader import PdfDocument
from zoning.textutil import page_list, snippet

HEADING = re.compile(r"\b(chapter|article|appendix|title|part)\b", re.I)
URL_RE = re.compile(r"https?://[^\s]+", re.I)


def run_gate(doc: PdfDocument) -> GateResult:
    checks: list[Check] = []
    if doc.scanned:
        checks.append(
            Check(
                "text_extracted",
                "FAIL",
                "Almost no text came out of this PDF. It needs OCR before zoning can be read.",
            )
        )
        checks.append(Check("document_status", "INFO", "SCANNED_PDF"))
        return GateResult("SCANNED_PDF", True, checks, SourceInfo(), [], [], [])

    source = _source(doc.pages)
    zoning_pages = _phrase_pages(doc.pages, ZONING_PHRASES)
    chapter_pages = _chapter_pages(doc.pages)
    zone_pages = _phrase_pages(doc.pages, ZONE_LIST_PHRASES)
    use_pages = _phrase_pages(doc.pages, USE_LIST_PHRASES)
    scope = chapter_pages or zoning_pages
    pointer = _pointer(doc.pages, scope)

    checks.append(
        Check(
            "zoning_chapter_found",
            "PASS" if chapter_pages else "FAIL",
            "A zoning, land-development, or unified-development heading was found."
            if chapter_pages
            else "No chapter, article, or appendix heading for zoning was found.",
            pages=page_list(chapter_pages),
        )
    )
    checks.append(
        Check(
            "zone_list_found",
            "PASS" if zone_pages else "FAIL",
            "A district-list heading was found."
            if zone_pages
            else "No district-list heading was found yet.",
            pages=page_list(zone_pages),
        )
    )
    checks.append(
        Check(
            "use_list_found",
            "PASS" if use_pages else "FAIL",
            "Use-table language was found."
            if use_pages
            else "No permitted-use, use-table, or special-exception language was found.",
            pages=page_list(use_pages),
        )
    )
    if pointer is None:
        checks.append(
            Check(
                "external_pointer",
                "PASS",
                "Nothing in the zoning text points to a separate ordinance.",
            )
        )
    else:
        quote, raw, guess, pages = pointer
        placeholder = len(scope) <= 8 and not use_pages
        checks.append(
            Check(
                "external_pointer",
                "FAIL" if placeholder else "WARN",
                quote,
                link_raw=raw,
                link_guess=guess,
                pages=page_list(pages),
            )
        )

    if not zoning_pages and not chapter_pages:
        status, stop = "NO_ZONING_FOUND", True
    elif pointer and len(scope) <= 8 and not use_pages:
        status, stop = "ZONING_NOT_IN_PDF", True
    elif not use_pages and not zone_pages and not chapter_pages:
        status, stop = "NO_USE_TABLE", True
    else:
        status, stop = "OK", False

    checks.append(Check("document_status", "INFO", status))
    return GateResult(status, stop, checks, source, chapter_pages or zoning_pages, use_pages, [])


def _source(pages: list[str]) -> SourceInfo:
    head = "\n".join(pages[:30])
    info = SourceInfo()
    for name in PUBLICATION_NAMES:
        if name.lower() in head.lower():
            info.publication = name
            break
    supplement = re.search(r"Supplement\s+No\.\s*[0-9A-Za-z\-]+", head, re.I)
    if supplement:
        info.supplement = supplement.group(0)
    current = re.search(
        r"(?:through|includes legislation through)\s+([^.\n]{6,90})",
        head,
        re.I,
    )
    if current:
        info.current_through = clean_through(current.group(0))
    return info


def clean_through(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _phrase_pages(pages: list[str], phrases: tuple[str, ...]) -> list[int]:
    found = []
    for index, text in enumerate(pages, start=1):
        low = text.lower()
        if any(phrase in low for phrase in phrases):
            found.append(index)
    return found


def _chapter_pages(pages: list[str]) -> list[int]:
    found = []
    for index, text in enumerate(pages, start=1):
        for raw in text.splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            low = line.lower()
            if not any(phrase in low for phrase in CHAPTER_PHRASES):
                continue
            if HEADING.search(line) or len(line) <= 90:
                found.append(index)
                break
    return found


def _pointer(pages: list[str], scope: list[int]):
    numbers = scope or list(range(1, len(pages) + 1))
    for number in numbers:
        text = pages[number - 1]
        low = text.lower()
        if not any(phrase in low for phrase in POINTER_PHRASES):
            continue
        if "zoning" not in low and "land development" not in low and "development code" not in low:
            continue
        raw = _url(text)
        phrase = next(item for item in POINTER_PHRASES if item in low)
        quote = snippet(text, phrase, 320)
        return quote, raw, _link_guess(raw), [number]
    return None


def _url(text: str) -> str:
    match = URL_RE.search(text)
    if not match:
        return ""
    raw = match.group(0).rstrip(".,;)")
    rest = text[match.end() :]
    extra = re.match(r"\s+([a-z0-9][a-z0-9./_-]{1,48})", rest)
    if extra:
        raw = f"{raw} {extra.group(1).rstrip('.,;)')}"
    return raw


def _link_guess(raw: str) -> str:
    if not raw:
        return ""
    guess = re.sub(r"\s+", "-", raw.strip())
    return re.sub(r"[.,;:)]+$", "", guess)
