"""S4: detect GRID / ROTATED_GRID / DISTRICT_LISTS and assign triage bucket."""

from __future__ import annotations

import re
from collections import defaultdict

from zoning.extract_text import page_words

ZONE_TOKEN = re.compile(r"^(?:[A-Z]{1,4}(?:-[A-Z0-9]{1,4})?|[A-Z]{1,4}\d{0,2})$")
SYMBOL_TOKEN = re.compile(r"^(?:P|C|SE|CU|SUP|CUP|TP|N|X|An|—|–|-)$")


def _page_axis_score(pdf: str, page: int) -> tuple[int, int]:
    """Return (best_x_cluster_size, best_y_cluster_size) for zone-like tokens."""
    try:
        words = page_words(pdf, page)
    except Exception:
        return 0, 0
    byx: dict[int, set[str]] = defaultdict(set)
    byy: dict[int, set[str]] = defaultdict(set)
    for bb, t in words:
        tok = t.rstrip("*")
        if not ZONE_TOKEN.match(tok) or not (1 <= len(tok) <= 8):
            continue
        x = (bb[0] + bb[2]) / 2
        y = (bb[1] + bb[3]) / 2
        byx[int(round(x / 3) * 3)].add(tok)
        byy[int(round(y / 3) * 3)].add(tok)
    bestx = max((len(v) for v in byx.values()), default=0)
    besty = max((len(v) for v in byy.values()), default=0)
    return bestx, besty


def _is_rotated(bestx: int, besty: int) -> bool:
    return bestx >= 4 and bestx > besty


def _is_grid(bestx: int, besty: int) -> bool:
    return besty >= 4 and besty >= bestx


def find_table_pages(pdf: str, seed_pages: list[int], page_count: int, max_checks: int = 80) -> tuple[list[int], bool]:
    """Grow contiguous rotated/grid pages around phrase seeds. Returns (pages, rotated)."""
    if not seed_pages:
        return [], False

    lo = max(1, int(page_count * 0.05))
    hi = max(lo + 1, int(page_count * 0.92))  # drop code-index tail
    seeds = sorted({p for p in seed_pages if lo <= p <= hi})
    if not seeds:
        seeds = sorted({p for p in seed_pages if 1 <= p <= page_count})

    candidates: list[int] = []
    # Walk seeds mid-document outward: prefer denser zoning chapters over TOC.
    for s in sorted(seeds, key=lambda p: abs(p - page_count * 0.65)):
        for p in range(max(1, s - 2), min(page_count, s + 15) + 1):
            if p not in candidates:
                candidates.append(p)
        if len(candidates) >= max_checks:
            break
    candidates = candidates[:max_checks]

    rotated_pages: list[int] = []
    grid_pages: list[int] = []
    for p in candidates:
        bx, by = _page_axis_score(pdf, p)
        if _is_rotated(bx, by):
            rotated_pages.append(p)
        elif _is_grid(bx, by):
            grid_pages.append(p)

    if rotated_pages:
        pages = sorted(rotated_pages)
        filled = set(pages)
        # Fill gaps inside the current span.
        if pages[-1] - pages[0] <= 150:
            for p in range(pages[0], pages[-1] + 1):
                if p in filled:
                    continue
                bx, by = _page_axis_score(pdf, p)
                if _is_rotated(bx, by):
                    filled.add(p)
        # Walk forward to catch later matrices (e.g. Sugar Land nonresidential).
        miss = 0
        p = max(filled) + 1
        while p <= min(page_count, max(filled) + 100) and miss < 8:
            bx, by = _page_axis_score(pdf, p)
            if _is_rotated(bx, by):
                filled.add(p)
                miss = 0
            else:
                miss += 1
            p += 1
        return sorted(filled), True
    if grid_pages:
        return sorted(grid_pages), False
    return [], False


def detect_format(
    pdf: str,
    pages: list[str],
    locate_info: dict,
) -> dict:
    """Return format, table_pages, rotated, bucket, status."""
    page_count = len(pages)
    avg_chars = sum(len(p) for p in pages) / max(1, page_count)

    if page_count == 0 or avg_chars < 100:
        return {
            "format": "NONE",
            "table_pages": "",
            "rotated": "no",
            "bucket": "D",
            "status": "SCANNED_PDF",
            "text_layer": "no",
        }

    text_layer = "yes"
    seeds = locate_info.get("table_phrase_pages") or []
    # Prefer seeds that look like real tables, not TOC
    seeds = [p for p in seeds if p > 40] or seeds

    table_pages, rotated = find_table_pages(pdf, seeds, page_count)
    list_pairs = locate_info.get("list_pair_pages") or []
    pointer = locate_info.get("pointer_found") == "yes"
    zoning = locate_info.get("zoning_found") == "yes"

    # Strong grid/rotated wins over pointer (real table in-file).
    if table_pages:
        fmt = "ROTATED_GRID" if rotated else "GRID"
        return {
            "format": fmt,
            "table_pages": ",".join(str(p) for p in table_pages),
            "rotated": "yes" if rotated else "no",
            "bucket": "A",
            "status": "OK",
            "text_layer": text_layer,
        }

    # External pointer and no in-file table → C
    if pointer:
        return {
            "format": "NONE",
            "table_pages": "",
            "rotated": "no",
            "bucket": "C",
            "status": "ZONING_NOT_IN_PDF",
            "text_layer": text_layer,
        }

    # District lists
    if list_pairs or (
        len(locate_info.get("list_pages") or []) >= 5
        and zoning
        and not table_pages
    ):
        # Meredith-style: multiple permitted/special pages
        if list_pairs or len(locate_info.get("list_pages") or []) >= 8:
            pages_out = list_pairs or (locate_info.get("list_pages") or [])[:20]
            return {
                "format": "DISTRICT_LISTS",
                "table_pages": ",".join(str(p) for p in pages_out[:40]),
                "rotated": "no",
                "bucket": "B",
                "status": "OK",
                "text_layer": text_layer,
            }

    if zoning:
        return {
            "format": "NONE",
            "table_pages": "",
            "rotated": "no",
            "bucket": "E",
            "status": "NO_USE_TABLE",
            "text_layer": text_layer,
        }

    return {
        "format": "NONE",
        "table_pages": "",
        "rotated": "no",
        "bucket": "E",
        "status": "NO_ZONING_FOUND",
        "text_layer": text_layer,
    }
