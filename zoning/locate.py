"""S3: locate zoning / use-table / list / pointer pages."""

from __future__ import annotations

import re

from zoning.gate import POINTER, norm_url
from zoning.phrases_triage import LIST_PHRASES, USE_TABLE_PHRASES, ZONING_PHRASES

URL_RE = re.compile(r"https?://[^\s]+(?:\s+[a-z][\w-]*)?", re.I)


def _hits(pages: list[str], phrases: list[str]) -> list[int]:
    out = []
    for i, text in enumerate(pages):
        low = text.lower()
        if any(re.search(p, low) for p in phrases):
            out.append(i + 1)
    return out


def locate(pages: list[str]) -> dict:
    zoning_pages = _hits(pages, ZONING_PHRASES)
    table_phrase_pages = _hits(pages, USE_TABLE_PHRASES)
    list_pages = _hits(pages, LIST_PHRASES)

    # District-list signal: same page has permitted + (special exception|conditional)
    list_pair_pages = [
        i + 1
        for i, text in enumerate(pages)
        if re.search(r"permitted\s+uses", text, re.I)
        and re.search(r"special\s+exceptions|conditional\s+uses", text, re.I)
    ]

    pointer_page = ""
    pointer_link = ""
    pointer_found = "no"
    for i, text in enumerate(pages):
        if not re.search(r"LAND DEVELOPMENT CODE|ZONING", text, re.I):
            continue
        if not re.search(POINTER, text, re.I):
            continue
        m = URL_RE.search(text)
        if not m:
            continue
        raw = m.group(0)
        pointer_found = "yes"
        pointer_page = str(i + 1)
        pointer_link = norm_url(raw)
        break

    return {
        "zoning_found": "yes" if zoning_pages else "no",
        "zoning_pages": zoning_pages,
        "table_phrase_pages": table_phrase_pages,
        "list_pages": list_pages,
        "list_pair_pages": list_pair_pages,
        "pointer_found": pointer_found,
        "pointer_page": pointer_page,
        "pointer_link": pointer_link,
    }
