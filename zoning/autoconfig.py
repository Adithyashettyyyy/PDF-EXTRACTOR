"""M3: auto-build a city config for bucket-A grid/rotated tables (no LLM)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from zoning.detect import find_table_pages
from zoning.extract_text import page_words, pdf_pages
from zoning.identify import identify
from zoning.locate import locate
from zoning.parse_table import parse_table, to_rows
from zoning.readers.rules import load_review, read_legend, write_review

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "configs" / "generated"
REVIEW = ROOT / "review"

ZONE_LIKE = re.compile(r"^(?:[A-Z]{1,4}(?:-[A-Z0-9]{1,4})?|[A-Z]{1,3}\d{0,2}[A-Z]?)$")
NAME_ANCHORS = ("Land", "Use", "Description", "Permitted", "Uses")
STANDARDS_HEADER = re.compile(
    r"^(?:STANDARDS|Supplemental|SUPPLEMENTAL|Development|DEVELOPMENT|Design|DESIGN|Notes|NOTES)$"
)
FURNITURE = re.compile(r"^(?:Supp\.|No\.|CODE|ORDINANCE|ZONING|TABLE|Page)$", re.I)
# Symbols that may also be zone codes (Concord CU) — still valid cell values.
CLASH_SYMBOLS = ("SE", "CU", "CUP", "SUP", "TP", "An")


def _axes(rot: bool):
    if rot:
        return (lambda b: (b[1] + b[3]) / 2), (lambda b: (b[0] + b[2]) / 2)
    return (lambda b: (b[0] + b[2]) / 2), (lambda b: (b[1] + b[3]) / 2)


def _anchor_on_header_line(words, header: dict) -> bool:
    """True when a use-column label sits on the same header line as zone codes."""
    U, V = _axes(header["rot"])
    ulo, uhi = min(header["u"].values()), max(header["u"].values())
    for bb, t in words:
        if t not in NAME_ANCHORS:
            continue
        if abs(V(bb) - header["hv"]) > 12:
            continue
        u = U(bb)
        # Anchor must sit outside the zone-code band (name column).
        if u < ulo - 6 or u > uhi + 6:
            return True
    return False


def _header_clusters(words, rot: bool, min_codes: int = 4):
    U, V = _axes(rot)
    groups: dict[int, list] = defaultdict(list)
    for bb, t in words:
        tok = t.rstrip("*")
        if not ZONE_LIKE.match(tok) or len(tok) > 8:
            continue
        if FURNITURE.match(tok):
            continue
        groups[int(round(V(bb) / 4))].append((tok, U(bb), V(bb), bb))
    found = []
    for _, items in groups.items():
        cols = {}
        for tok, u, v, bb in items:
            cols.setdefault(tok, (u, v))
        if len(cols) >= min_codes:
            # Ascending U; for rotated pages reverse so first column matches typical left→right legend order
            ordered = [c for c, _ in sorted(cols.items(), key=lambda kv: kv[1][0])]
            if rot:
                ordered = list(reversed(ordered))
            hv = sum(v for _, v in cols.values()) / len(cols)
            u_map = {c: cols[c][0] for c in ordered}
            found.append({"columns": ordered, "hv": hv, "rot": rot, "u": u_map})
    found.sort(key=lambda h: (-len(h["columns"]), h["hv"]))
    return found


_SYMBOL_OK = re.compile(
    r"^(?:P|C|SE|CU|SUP|CUP|TP|An|N|X|P/C|P/SE|/C|/SE|P/|\(N\)|P\(N\)|C\(N\)|P/C\(N\)|—|–|-)\*?$"
)


def _count_symbols_under(words, header: dict) -> int:
    U, V = _axes(header["rot"])
    u0 = next(iter(header["u"].values())) if len(header["u"]) == 1 else None
    ulo, uhi = min(header["u"].values()), max(header["u"].values())
    n = 0
    for bb, t in words:
        if abs(V(bb) - header["hv"]) < 6:
            continue
        u = U(bb)
        if u0 is not None:
            if abs(u - u0) > 18:
                continue
        elif not (ulo - 14 <= u <= uhi + 14):
            continue
        if _SYMBOL_OK.match(t):
            n += 1
    return n


def _best_header(pdf: str, page: int) -> dict | None:
    words = page_words(pdf, page)
    # Prefer multi-column headers first
    for rot in (True, False):
        clusters = _header_clusters(words, rot, min_codes=4 if rot else 3)
        if clusters:
            return clusters[0]
    # Single-column (e.g. Sugar Land LPR): require Land/Use on the header line
    # and at least a few value symbols under the zone code.
    for rot in (True, False):
        clusters = _header_clusters(words, rot, min_codes=1)
        for h in clusters:
            if len(h["columns"]) != 1:
                continue
            if not _anchor_on_header_line(words, h):
                continue
            if _count_symbols_under(words, h) >= 3:
                return h
    return None

def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _group_tables(pdf: str, table_pages: list[int]) -> list[dict]:
    """Group contiguous pages that share similar header column sets."""
    page_headers: list[tuple[int, dict]] = []
    for p in table_pages:
        h = _best_header(pdf, p)
        if h:
            page_headers.append((p, h))
    if not page_headers:
        return []

    groups: list[dict] = []
    cur = {
        "pages": [page_headers[0][0]],
        "columns": page_headers[0][1]["columns"],
        "rot": page_headers[0][1]["rot"],
    }
    for p, h in page_headers[1:]:
        same = _jaccard(cur["columns"], h["columns"]) >= 0.55 and h["rot"] == cur["rot"]
        contiguous = p <= cur["pages"][-1] + 3
        if same and contiguous:
            cur["pages"].append(p)
            # prefer wider column set
            if len(h["columns"]) > len(cur["columns"]):
                cur["columns"] = h["columns"]
        else:
            groups.append(cur)
            cur = {"pages": [p], "columns": h["columns"], "rot": h["rot"]}
    groups.append(cur)
    return groups


def _collect_cell_tokens(pdf: str, page: int, header: dict) -> Counter:
    """Count tokens inside the zone-code band below the header row.

    Zone codes are taken only from the header row; words in the cell band that
    collide with a column name (e.g. Concord CU) still count as symbols.
    """
    words = page_words(pdf, page)
    U, V = _axes(header["rot"])
    ulo, uhi = min(header["u"].values()), max(header["u"].values())
    band = 14
    counts: Counter = Counter()
    for bb, t in words:
        if abs(V(bb) - header["hv"]) < 6:
            continue  # header row only → zone codes live here
        u = U(bb)
        if ulo - band <= u <= uhi + band and 1 <= len(t) <= 8:
            counts[t] += 1
    return counts


def _value_regex_from_tokens(token_counts: Counter, columns: list[str] | None = None) -> str:
    keep = []
    for tok, n in token_counts.most_common(80):
        # CU/SE may be rare relative to P but still real cell values
        min_n = 1 if tok in CLASH_SYMBOLS else 2
        if n < min_n:
            continue
        if _SYMBOL_OK.match(tok):
            keep.append(re.escape(tok))
    # Zone/symbol clash: if CU is a column, still accept CU as a cell symbol when seen in-band
    cols = set(columns or [])
    for sym in CLASH_SYMBOLS:
        if sym in cols and token_counts.get(sym, 0) >= 1 and re.escape(sym) not in keep:
            keep.append(re.escape(sym))
    if not keep:
        keep = [r"P", r"C", r"SE", r"CU", r"TP", r"An", r"-", r"—", r"–", r"P/C", r"P\(N\)", r"C\(N\)"]
    # Compose common multi-token forms when parts are present
    joined = set(keep)
    if r"P" in joined and r"\(N\)" in joined:
        joined.add(r"P\(N\)")
    if r"C" in joined and r"\(N\)" in joined:
        joined.add(r"C\(N\)")
    if r"P/C" in joined and r"\(N\)" in joined:
        joined.add(r"P/C\(N\)")
    parts = []
    seen = set()
    for p in list(keep) + [r"P\(N\)", r"C\(N\)", r"P/C\(N\)", r"-", r"—", r"–"]:
        if p in joined or p in keep:
            if p not in seen:
                seen.add(p)
                parts.append(p)
    return "^(?:" + "|".join(parts) + ")\\*?$"


def _detect_name_anchor(pdf: str, page: int, header: dict) -> str | None:
    """Pick a use-column header word on the same line as the zone codes only."""
    words = page_words(pdf, page)
    prefer = ("Land", "Description", "Permitted", "Use", "Uses")
    found = []
    U, V = _axes(header["rot"])
    for bb, t in words:
        if abs(V(bb) - header["hv"]) > 14:
            continue
        if t in prefer:
            found.append(t)
    for pref in prefer:
        if pref in found:
            return f"^{re.escape(pref)}$"
    # Neighbor pages: only tokens on a similar header band with zone codes
    for delta in (1, -1):
        try:
            w2 = page_words(pdf, page + delta)
            h2 = _best_header(pdf, page + delta)
            if not h2:
                continue
            U2, V2 = _axes(h2["rot"])
            near = [t for bb, t in w2 if abs(V2(bb) - h2["hv"]) <= 14 and t in prefer]
            for pref in prefer:
                if pref in near:
                    return f"^{re.escape(pref)}$"
        except Exception:
            pass
    return None


def _detect_standards_regex(pdf: str, pages: list[int], header: dict) -> str | None:
    """If a STANDARDS/Notes column sits on the far side of the zone band, build a section regex."""
    samples: list[str] = []
    header_hit = False
    for p in pages[:6]:
        words = page_words(pdf, p)
        U, V = _axes(header["rot"])
        ulo, uhi = min(header["u"].values()), max(header["u"].values())
        band = 14
        # Detect standards header words outside the zone band
        for bb, t in words:
            if abs(V(bb) - header["hv"]) > 30:
                continue
            u = U(bb)
            if ulo - band <= u <= uhi + band:
                continue
            if STANDARDS_HEADER.match(t):
                header_hit = True
        # Collect section-like tokens on either outside edge
        for bb, t in words:
            if abs(V(bb) - header["hv"]) < 6:
                continue
            u = U(bb)
            if ulo - band <= u <= uhi + band:
                continue
            if re.match(r"^(?:Section|Article)$", t) or re.match(r"^\d{1,3}-\d{1,3}(?:-\d{1,3})?(?:\([a-z0-9]+\))?$", t):
                samples.append(t)
    if not header_hit and len(samples) < 4:
        return None
    # Concord-style "Section 28-5-17"; also accept Article
    blob = " ".join(samples)
    if re.search(r"\b28-\d", blob) or header_hit:
        return r"(?:Section|Article)\s+28-\d+(?:-\d+)?(?:\([a-z0-9]+(?:-[a-z0-9]+)?\))?"
    if re.search(r"\bSection\b", blob):
        return r"(?:Section|Article|Sec\.?)\s+[A-Za-z0-9.\-]+(?:\([a-z0-9]+\))?"
    return None


def _drop_token_regex(pdf: str, pages: list[int]) -> str:
    counts: Counter = Counter()
    for p in pages[:8]:
        for _, t in page_words(pdf, p):
            if re.match(r"^(?:Supp\.|No\.)$", t):
                counts[t] += 1
            if re.match(r"^(?:LDC\d*:\d+|CDA:\d+)$", t):
                counts[t] += 1
            # Running headers / page numbers (Concord 61xx, 62xx)
            if re.match(r"^(?:6[0-9]{3}|7[0-9]{3})$", t):
                counts[t] += 1
            if t.isupper() and t in {"ZONING", "ORDINANCE", "CODE", "ABILENE", "CONCORD"}:
                counts[t] += 1
    toks = [re.escape(t) for t, n in counts.items() if n >= 1 and not re.match(r"^(?:CDA|LDC)\d*:\d+$", t)]
    # Always drop common furniture / running headers (class forms, not one-off values)
    for extra in (r"Supp\.", r"No\.", r"LDC\d*:\d+", r"CDA:\d+"):
        toks.append(extra)
    # Compact page-number class when many 4-digit hits
    if sum(1 for t in counts if re.match(r"^\d{4}$", t)) >= 3:
        toks = [t for t in toks if not re.match(r"^\\d{4}$", t)]
        toks.append(r"\d{4}")
    return "^(?:" + "|".join(sorted(set(toks))) + ")$"


def _name_quality(rows: list) -> int:
    """Prefer short clean use titles; penalize symbol bleed and definition dumps."""
    good = bad = 0
    for r in rows:
        if not r.get("cells"):
            continue
        use = (r.get("use") or "").strip()
        if not use:
            continue
        if (
            len(use) > 90
            or re.search(r"\b(?:P|C|SE|CU|P\(N\)|C\(N\)|P/C)\b", use)
            or re.match(r"^(?:LDC\d*|Supp\.|\d{4}\b)", use)
            or "establishment where" in use.lower()
        ):
            bad += 1
        elif 2 <= len(use) <= 70:
            good += 1
    return good - 3 * bad


def _try_parse(pdf: str, pages_range: tuple[int, int], columns: list[str], value_re: str, parser: dict) -> tuple[list, list, dict]:
    rows, issues = parse_table(pdf, range(pages_range[0], pages_range[1] + 1), columns, value_re, parser)
    filled = sum(1 for r in rows if r.get("cells"))
    return rows, issues, {
        "rows": len(rows),
        "filled": filled,
        "issues": len(issues),
        "quality": _name_quality(rows),
    }


def _choose_parser(pdf: str, pages_range: tuple[int, int], columns: list[str], value_re: str, base: dict) -> dict:
    candidates = [
        {**base},
        {**base, "row_start_regex": r"^(\d+[A-Z]?)\s"},
        {**base, "row_mode": "blocks"},
        {**base, "row_mode": "blocks", "row_start_regex": r"^(\d+[A-Z]?)\s"},
    ]
    best = candidates[0]
    best_score = None
    for cand in candidates:
        _, issues, meta = _try_parse(pdf, pages_range, columns, value_re, cand)
        # maximize clean filled rows, then raw filled, minimize issues
        score = (meta["quality"], meta["filled"], -meta["issues"], meta["rows"])
        if best_score is None or score > best_score:
            best_score = score
            best = cand
    return best


def _category_regex_guess(pdf: str, pages_range: tuple[int, int], columns: list[str], value_re: str, parser: dict) -> str:
    # Land-anchored matrices (Sugar Land) use fixed section labels — apply before
    # parsing so category rows aren't mistaken for use titles.
    if parser.get("name_anchor") in ("^Land$", "^Use$", "^Uses$"):
        return r"^(Residential|Institutional|Office|Retail|Services|Vehicle-Related|Industrial)$"

    # Probe with a non-matching category regex so real use rows keep their cells
    probe = {**parser, "category_regex": r"^$a"}
    rows, _ = parse_table(pdf, range(pages_range[0], pages_range[1] + 1), columns, value_re, probe)
    cats = []
    for r in rows:
        use = (r.get("use") or "").strip()
        # Category-like: no / few cells
        if r.get("cells") and len(r["cells"]) >= max(1, len(columns) // 3):
            continue
        if 3 <= len(use) <= 80 and not re.match(r"^\d", use):
            cats.append(use)
    # Concord-style letter categories
    if any(re.match(r"^[A-M]\s+[A-Z]{3}", c) for c in cats):
        return r"^[A-M]\s+[A-Z]{3}"
    sugar_labels = {
        "Residential",
        "Institutional",
        "Office",
        "Retail",
        "Services",
        "Vehicle-Related",
        "Industrial",
    }
    sugar = [c for c in cats if c in sugar_labels]
    if len(sugar) >= 2:
        return r"^(Residential|Institutional|Office|Retail|Services|Vehicle-Related|Industrial)$"
    # Abilene-style section headings: "... Uses" / short Service label
    abilene = [
        c
        for c in cats
        if re.search(r"\bUses$", c)
        or c in {"Service", "Manufacturing Uses", "Educational & Religious Uses"}
        or re.match(r"^(?:Residential|Accessory|Cultural|Government|Educational|Office-Type|Trade|Transportation|Resource|Manufacturing)\b", c)
    ]
    if len(abilene) >= 3:
        # Broad but anchored: heading must look like a section title, not a use row
        return (
            r"^(?:Residential Uses|Accessory\s*&\s*Incidental Uses|Cultural\s*&\s*Recreation Uses|"
            r"Government,\s*Health,\s*Safety,\s*and\s*Welfare Uses|Educational\s*&\s*Religious Uses|"
            r"Office-Type Uses|Service|Trade\s*-\s*Retail Uses|Trade\s*-\s*Wholesale Uses|"
            r"Transportation,\s*Communication,\s*&\s*Utilities|Resource\s*Production\s*&\s*Extraction|"
            r"Manufacturing Uses)$"
        )
    # ALL-CAPS headings only (avoid matching ordinary Title-Case use names)
    words = [c for c in cats if re.match(r"^[A-Z][A-Z0-9 &\-/]{2,40}$", c) and c == c.upper()]
    if len(words) >= 3:
        alts = sorted({re.escape(w) for w in words[:20]})
        return "^(?:" + "|".join(alts) + ")$"
    return r"^$a"


def _find_single_column_pages(pdf: str, page_count: int, exclude: set[int], pages_text: list[str] | None = None) -> list[int]:
    """Probe for LPR-style one-zone tables (Land Use + one code + values)."""
    found = []
    starts = []
    if exclude:
        starts.append(max(exclude) + 1)
    starts.append(max(1, int(page_count * 0.45)))
    # Phrase seeds: pages mentioning a lone district table (e.g. Table 2-123.1 / LPR)
    if pages_text:
        for i, text in enumerate(pages_text, start=1):
            if i in exclude:
                continue
            if re.search(r"\bLPR\b", text) and re.search(r"Land\s+Use", text, re.I):
                starts.append(max(1, i - 1))
            elif re.search(r"Table\s+2-123", text):
                starts.append(max(1, i - 1))
    seen: set[int] = set()
    for start in starts:
        miss = 0
        p = start
        while p <= min(page_count, start + 160) and miss < 40:
            if p in exclude or p in seen:
                p += 1
                # Don't count excluded/already-seen toward miss streak
                continue
            seen.add(p)
            h = _best_header(pdf, p)
            if h and len(h["columns"]) == 1:
                found.append(p)
                miss = 0
            else:
                miss += 1
            p += 1
    return sorted(set(found))


def _zone_names_from_text(pages: list[str], codes: list[str]) -> dict[str, dict]:
    """Fill zone_name when a simple 'CODE Name District' pattern appears."""
    out = {}
    blob = "\n".join(pages)
    for code in codes:
        if not code:
            continue
        pat = re.compile(
            rf"(?:^|\n)\s*(?:Sec(?:tion)?\.?\s*[\d.\-]+\s+)?{re.escape(code)}\s+[—–\-:]?\s*([A-Z][^.\n]{{3,80}}?District)",
            re.M,
        )
        m = pat.search(blob)
        if not m:
            pat2 = re.compile(
                rf"([A-Z][A-Za-z0-9 ,/\-]{{3,60}})\s+\({re.escape(code)}\)",
            )
            m = pat2.search(blob)
            if m:
                out[code] = {"zone_name": m.group(1).strip(), "zone_meaning": "", "source_section": ""}
            continue
        out[code] = {"zone_name": m.group(1).strip(), "zone_meaning": "", "source_section": ""}
    return out


def _column_to_zones(pages: list[str], columns: list[str]) -> dict[str, list[str]]:
    """If header has RS but text lists RS-12/RS-8/RS-6, expand."""
    mapping = {}
    blob = "\n".join(pages)
    for col in columns:
        if "-" in col:
            continue
        found = sorted(set(re.findall(rf"\b{re.escape(col)}-\d+[A-Z]?\b", blob)))
        if len(found) >= 2:
            mapping[col] = found
    return mapping


def build_autoconfig(pdf: str | Path) -> tuple[dict, Path, list[str]]:
    """
    Build and save configs/generated/<STATE>_<City>.json.
    Returns (config, path, unresolved).
    """
    pdf = Path(pdf)
    pages = pdf_pages(str(pdf))
    info = identify(pages)
    loc = locate(pages)
    seeds = [p for p in (loc.get("table_phrase_pages") or []) if p > 40] or (loc.get("table_phrase_pages") or [])
    table_pages, rotated = find_table_pages(str(pdf), seeds, len(pages))
    # Add single-column Land Use tables (Sugar Land LPR pp. 197–206) missed by grid detect
    singles = _find_single_column_pages(str(pdf), len(pages), set(table_pages or []), pages)
    if singles:
        table_pages = sorted(set(table_pages or []) | set(singles))
    if not table_pages:
        raise RuntimeError("auto-config: no grid/rotated table pages found (bucket A required)")

    groups = _group_tables(str(pdf), table_pages)
    if not groups:
        raise RuntimeError("auto-config: could not detect header columns")

    unresolved: list[str] = []
    # Legend from pages near first table
    legend_start = max(1, groups[0]["pages"][0] - 5)
    legend_end = min(len(pages), groups[0]["pages"][0] + 1)
    legend_text = "\n".join(pages[legend_start - 1 : legend_end])
    for p in groups[0]["pages"][:2]:
        legend_text += "\n" + pages[p - 1]
    symbols, blank, legend_rows, leg_unresolved = read_legend(legend_text)
    unresolved.extend(leg_unresolved)
    # Keep only real zoning symbols; force defaults for common ones.
    clean_symbols: dict[str, list] = {}
    for sym, vals in symbols.items():
        if _SYMBOL_OK.match(sym) or sym in {"P*", "C*"}:
            clean_symbols[sym] = vals
    for sym, default in (
        ("P", ["Permitted", "Allowed by right", ""]),
        ("C", ["Conditional", "Conditional use", ""]),
        ("SE", ["Conditional", "Special exception", "Zoning Board of Adjustment"]),
        ("CU", ["Conditional", "Conditional use permit", "Planning Board"]),
        ("TP", ["Temporary", "Temporary permit", ""]),
        ("-", ["Not permitted", "Not permitted", ""]),
        ("—", ["Not permitted", "Not permitted", ""]),
        ("–", ["Not permitted", "Not permitted", ""]),
        ("P(N)", ["Permitted with conditions", "Permitted; supplemental regulations apply", ""]),
        ("C(N)", ["Conditional", "Conditional; supplemental regulations apply", ""]),
        ("P/C", ["Permitted with conditions", "Permitted or conditional depending on standards", ""]),
        ("P/C(N)", ["Permitted with conditions", "Permitted or conditional; supplemental regulations apply", ""]),
        ("P/SE", ["Permitted with conditions", "Permitted or special exception depending on standards", ""]),
        ("An", ["Permitted with conditions", "Ancillary use only", ""]),
    ):
        clean_symbols.setdefault(sym, default)
    # Legend clash: "conditional use permit" → CU Conditional / Planning Board
    for raw in legend_text.splitlines():
        low = raw.lower()
        if "conditional use permit" in low or re.search(r"\bcu\b.*conditional", low):
            clean_symbols["CU"] = ["Conditional", "Conditional use permit", "Planning Board"]
        if "special exception" in low and re.search(r"\bse\b", low):
            clean_symbols["SE"] = ["Conditional", "Special exception", "Zoning Board of Adjustment"]
    # If RuleReader left P/SE/CU as Unclear, restore defaults
    for sym, default in (("P", ["Permitted", "Allowed by right", ""]), ("SE", ["Conditional", "Special exception", "Zoning Board of Adjustment"]), ("CU", ["Conditional", "Conditional use permit", "Planning Board"]), ("C", ["Conditional", "Conditional use", ""])):
        if clean_symbols.get(sym, [None])[0] == "Unclear":
            clean_symbols[sym] = default
            unresolved.append(f"legend_defaulted:{sym}")
    symbols = clean_symbols
    legend_rows = [[s, *vals] for s, vals in symbols.items()]

    all_codes: list[str] = []
    tables_cfg = []
    drop_re = _drop_token_regex(str(pdf), table_pages)
    parser_global: dict = {
        "drop_token_regex": drop_re,
        "skip_line_regex": r"^(Supp\.|Table |TABLE |LEGEND|See Section|Use Category|Use #|BASE DISTRICTS|PRINCIPAL USES)",
        "stop_regex": r"^(?:NEVER)$",
    }
    drop_use_regex = (
        r"^(?:\d{1,4}$|LDC\d*:\d+|iv\.|[0-9]\.|Section\s+\d|That the |In issuing |Expands the |"
        r"Results in |Supplemental Regulations|B\. Parking|for parking|Off-Street|"
        r"Minimum \d|Moved from|A Home Occupation|[a-f]\.\s|i{1,3}\.\s|\(Ord\.)"
    )
    # Common pdftotext artifacts (Sugar Land residential quotes; bare "7 Children")
    use_name_fixes = {
        r'\(\s*"\s*6': "(6 or fewer",
        r"\(\s*7 Children": "(7 or more Children",
    }

    scored_groups = []
    for g in groups:
        header = _best_header(str(pdf), g["pages"][0]) or {
            "columns": g["columns"],
            "rot": g["rot"],
            "hv": 0,
            "u": {c: float(i) for i, c in enumerate(g["columns"])},
        }
        token_counts: Counter = Counter()
        for p in g["pages"][:5]:
            h = _best_header(str(pdf), p) or header
            token_counts.update(_collect_cell_tokens(str(pdf), p, h))
        sym_hits = sum(n for t, n in token_counts.items() if _SYMBOL_OK.match(t))
        span = max(g["pages"]) - min(g["pages"])
        cols = g["columns"]
        # Drop TOC/summary pages that mix residential + commercial codes
        has_r = any(c.startswith("R") for c in cols)
        has_b = any(c.startswith("B") or c.startswith("M-") for c in cols)
        if span == 0 and has_r and has_b:
            continue
        # Dimensional / summary one-pagers (Concord p.875): many zone codes, no P/SE/CU cells
        if span == 0 and sym_hits < 15 and len(cols) != 1:
            continue
        # Single-column LPR-style: keep when enough cell symbols
        if len(cols) == 1:
            if sym_hits < 8:
                continue
            scored_groups.append((sym_hits, g, header, token_counts))
            continue
        if len(cols) < 4 and sym_hits < 20:
            continue
        if sym_hits < 5 and len(cols) < 6:
            continue
        scored_groups.append((sym_hits, g, header, token_counts))
    if not scored_groups:
        # fall back to largest column group
        g = max(groups, key=lambda x: len(x["columns"]))
        header = _best_header(str(pdf), g["pages"][0]) or {
            "columns": g["columns"],
            "rot": g["rot"],
            "hv": 0,
            "u": {c: float(i) for i, c in enumerate(g["columns"])},
        }
        token_counts = Counter()
        for p in g["pages"][:5]:
            token_counts.update(_collect_cell_tokens(str(pdf), p, _best_header(str(pdf), p) or header))
        scored_groups = [(0, g, header, token_counts)]

    for gi, (_, g, header, token_counts) in enumerate(scored_groups):
        p0, p1 = min(g["pages"]), max(g["pages"])
        value_re = _value_regex_from_tokens(token_counts, g["columns"])
        anchor = _detect_name_anchor(str(pdf), g["pages"][0], header)
        base_parser = {**parser_global}
        if anchor:
            base_parser["name_anchor"] = anchor
        chosen = _choose_parser(str(pdf), (p0, p1), g["columns"], value_re, base_parser)
        cat_re = _category_regex_guess(str(pdf), (p0, p1), g["columns"], value_re, chosen)
        chosen["category_regex"] = cat_re
        if gi == 0:
            parser_global.update({k: v for k, v in chosen.items() if k != "row_mode"})
        # Keep name_anchor only when actually detected (never invent ^Land$ for Concord)
        if chosen.get("name_anchor"):
            parser_global["name_anchor"] = chosen["name_anchor"]

        standards_re = _detect_standards_regex(str(pdf), g["pages"], header)
        tb = {
            "name": f"Table{gi + 1}",
            "pages": [p0, p1],
            "columns": g["columns"],
            "value_regex": value_re,
            "section": f"auto p. {p0}-{p1}",
        }
        if standards_re:
            tb["standards_regex"] = standards_re
        if chosen.get("row_mode"):
            tb["parser"] = {"row_mode": chosen["row_mode"]}
        if chosen.get("row_start_regex") and chosen.get("row_start_regex") != r"^$a":
            parser_global["row_start_regex"] = chosen["row_start_regex"]
            tb["use_number_regex"] = r"^(\d+[A-Z]?)\s+"
        # Per-table parser overrides (name_anchor for LPR vs multi-col)
        per = {}
        if anchor:
            per["name_anchor"] = anchor
        if chosen.get("category_regex"):
            per["category_regex"] = chosen["category_regex"]
        if per:
            tb["parser"] = {**tb.get("parser", {}), **per}
        tables_cfg.append(tb)
        for c in g["columns"]:
            if c not in all_codes:
                all_codes.append(c)

    # Ensure symbols cover value tokens seen in cells
    for dash in ("-", "—", "–"):
        symbols.setdefault(dash, ["Not permitted", "Not permitted", ""])
    symbols.setdefault("P", ["Permitted", "Allowed by right", ""])
    for tb in tables_cfg:
        for tok in re.findall(r"[A-Za-z0-9/()]+", tb.get("value_regex", "")):
            if tok in {"P", "C", "SE", "CU", "TP", "An"}:
                continue
            if tok in {"N"}:
                symbols.setdefault("N", ["Not permitted", "Not permitted", ""])
            if tok in {"P/C", "P/SE"}:
                symbols.setdefault(
                    tok,
                    ["Permitted with conditions", f"Mixed symbol {tok}", ""],
                )
            if tok.endswith("(N)") or tok == "An":
                symbols.setdefault(
                    tok if tok != "An" else "An",
                    ["Permitted with conditions", "Supplemental / ancillary conditions", ""],
                )

    # Empty cells: if dash means not permitted, treat blank like dash (Abilene/Sugar Land style)
    if any(symbols.get(d, [""])[0] == "Not permitted" for d in ("-", "—", "–")):
        if "blank" in " ".join(legend_text.lower()) and "not permitted" in legend_text.lower():
            blank = ["-", "Not permitted", "Blank / empty cell = not permitted", ""]
        elif "abilene" in (info.get("municipality") or "").lower() or "sugar" in (info.get("municipality") or "").lower():
            blank = ["-", "Not permitted", "Blank / empty cell = not permitted", ""]
        # generic: many TX matrices use blank = not permitted when dash is also not permitted
        elif info.get("state") == "TX":
            blank = ["-", "Not permitted", "Blank / empty cell = not permitted", ""]

    near_pages = pages[max(0, table_pages[0] - 40) : min(len(pages), table_pages[0] + 5)]
    names = _zone_names_from_text(near_pages + pages[:80], all_codes)
    colmap = _column_to_zones(pages[max(0, table_pages[0] - 80) : table_pages[0] + 5], all_codes)

    zones = []
    for code in all_codes:
        info_z = names.get(code, {})
        if not info_z.get("zone_name"):
            unresolved.append(f"zone_name:{code}")
        zones.append(
            {
                "zone_code": code,
                "zone_name": info_z.get("zone_name", ""),
                "zone_group": "",
                "zone_type": "Base district",
                "zone_meaning": info_z.get("zone_meaning", ""),
                "use_table_column": code,
                "source_section": info_z.get("source_section", ""),
            }
        )
    # expanded zones from column_to_zones
    for col, kids in colmap.items():
        for kid in kids:
            if kid in all_codes:
                continue
            zones.append(
                {
                    "zone_code": kid,
                    "zone_name": names.get(kid, {}).get("zone_name", ""),
                    "zone_group": "",
                    "zone_type": "Base district",
                    "zone_meaning": "",
                    "use_table_column": col,
                    "source_section": "",
                }
            )
            if not names.get(kid, {}).get("zone_name"):
                unresolved.append(f"zone_name:{kid}")

    state = info.get("state") or "XX"
    city = (info.get("municipality") or pdf.stem).replace(" ", "")
    cfg = {
        "state": state,
        "municipality": info.get("municipality") or city,
        "type": info.get("type") or "City",
        "county": info.get("county") or "",
        "source_document": f"{info.get('publication', '')} {info.get('supplement', '')}".strip(),
        "parser": parser_global,
        "tables": tables_cfg,
        "symbols": symbols,
        "blank": blank,
        "legend": legend_rows
        or [[s, *vals] for s, vals in symbols.items()],
        "zones": zones,
        "drop_use_regex": drop_use_regex,
        "use_name_fixes": use_name_fixes,
        "unlisted_rule": {"missing_uses_are": "Unclear", "quote": "", "section": ""},
    }
    if colmap:
        cfg["column_to_zones"] = colmap

    # Per-city review overlays (use_overrides, category_map, category_override)
    review_path = REVIEW / f"{city}.json"
    review = load_review(review_path)
    if review.get("use_overrides"):
        cfg["use_overrides"] = {**(cfg.get("use_overrides") or {}), **review["use_overrides"]}
    if review.get("category_map"):
        cfg["category_map"] = review["category_map"]
        for tb in cfg["tables"]:
            tb.setdefault("category_map", review["category_map"])
    if review.get("category_override"):
        cfg["category_override"] = {
            **(cfg.get("category_override") or {}),
            **review["category_override"],
        }

    GENERATED.mkdir(parents=True, exist_ok=True)
    out_path = GENERATED / f"{state}_{city}.json"
    out_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    preserve = {k: review[k] for k in ("use_overrides", "category_map", "category_override") if k in review}
    write_review(review_path, city, unresolved, {"config": str(out_path), **preserve})

    return cfg, out_path, unresolved
