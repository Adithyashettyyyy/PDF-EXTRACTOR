"""S2: gate checks + external pointer."""

from __future__ import annotations

import re

GATE = {
    "zoning_chapter_found": r"(ZONING|LAND DEVELOPMENT CODE|UNIFIED DEVELOPMENT|DEVELOPMENT CODE|ZONING REGULATIONS)",
    "zone_list_found": r"(districts established|zoning districts|map codes|district listing|classification of districts)",
    "use_list_found": r"(permitted uses|use table|table of uses|land use matrix|schedule of uses|schedule of principal uses|use chart|table of principal uses|special exceptions)",
}
POINTER = r"(published separately|available at|can be found|found here|is on file|see the city website|repealed|replaced)"


def gate(pages: list[str]):
    res = []
    for name, rx in GATE.items():
        hits = [i + 1 for i, p in enumerate(pages) if re.search(rx, p, re.I)]
        res.append((name, "PASS" if hits else "FAIL", f"{len(hits)} pages", hits[:5]))
    ptr = [
        (i + 1, re.sub(r"\s+", " ", p)[:400])
        for i, p in enumerate(pages)
        if re.search(r"LAND DEVELOPMENT CODE|ZONING", p)
        and re.search(POINTER, p, re.I)
        and re.search(r"https?://\S+", p)
    ]
    return res, ptr


def norm_url(u: str) -> str:
    return re.sub(r"\s+", "-", u.strip()).rstrip(".,;)")
