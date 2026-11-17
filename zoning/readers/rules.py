"""RuleReader: legend / blank / unlisted from nearby page text (no LLM)."""

from __future__ import annotations

import re
from pathlib import Path

LEGEND_LINE = re.compile(
    r"(?:^|[\s(])(?P<sym>(?:blank|Blank|—|–|-|−|\*|P\*?|C\*?|SE|CU|SUP|CUP|TP|An|P/C|P\(N\)|C\(N\)|P/C\(N\)))"
    r"\s*(?:=|:|means|indicates)\s*(?P<mean>[^.;\n]{3,120})",
    re.I,
)
DENOTED = re.compile(
    r"(?:denoted by|indicated by|shown as)\s+(?P<sym>[A-Z*—–\-]{1,6})",
    re.I,
)
BODY_PHRASES = [
    ("Zoning Board of Adjustment", "Zoning Board of Adjustment"),
    ("Board of Adjustment", "Board of Adjustment"),
    ("Planning and Zoning Commission", "Planning and Zoning Commission"),
    ("Planning Board", "Planning Board"),
    ("Planning Commission", "Planning Commission"),
    ("City Council", "City Council"),
    ("Building Official", "Building Official"),
]


def permission_from_meaning(meaning: str) -> str:
    text = meaning.lower()
    if any(w in text for w in ("not permitted", "prohibited", "not allowed", "not permitted")):
        return "Not permitted"
    if "temporary" in text:
        return "Temporary"
    if any(
        w in text
        for w in (
            "conditional use",
            "special use",
            "specific use",
            "special exception",
            "cup",
            "sup",
            "conditional",
        )
    ):
        return "Conditional"
    if any(w in text for w in ("subject to", "supplemental", "standards", "with conditions", "ancillary")):
        return "Permitted with conditions"
    if any(w in text for w in ("permitted", "by right", "allowed by right", "allowed")):
        return "Permitted"
    return "Unclear"


def approval_body(text: str) -> str:
    for needle, label in BODY_PHRASES:
        if needle.lower() in text.lower():
            return label
    return ""


def read_legend(pages_text: str) -> tuple[dict, list, list[dict], list[str]]:
    """
    Returns (symbols_map, blank_tuple, legend_rows, unresolved).
    symbols_map: symbol -> [permission, route, body]
    blank_tuple: [symbol, permission, meaning, body]
    """
    symbols: dict[str, list] = {}
    legend_rows: list[list] = []
    unresolved: list[str] = []
    blank = ["(blank)", "Unclear", "Blank cell in the table", ""]

    for raw in pages_text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 5:
            continue
        for m in LEGEND_LINE.finditer(line):
            sym = m.group("sym").strip()
            if sym.lower() == "blank":
                sym_key = "(blank)"
            else:
                sym_key = sym
            mean = m.group("mean").strip()
            perm = permission_from_meaning(mean)
            body = approval_body(line) or approval_body(mean)
            if perm == "Unclear":
                unresolved.append(f"legend:{sym_key}:{mean}")
            if sym_key.lower() in {"blank", "(blank)"} or "blank" in mean.lower() and sym in {"-", "—", "–"}:
                if "not permitted" in mean.lower() or "prohibited" in mean.lower():
                    blank = ["-", "Not permitted", mean, body]
                elif "blank" in sym.lower() or sym_key == "(blank)":
                    blank = ["(blank)", perm if perm != "Unclear" else "Unclear", mean, body]
            if sym_key == "(blank)":
                continue
            if sym_key not in symbols:
                route = mean[:80]
                symbols[sym_key] = [perm, route, body]
                legend_rows.append([sym_key, perm, mean, body])

    # Common dash defaults if seen in tables but not legend
    for dash in ("-", "—", "–"):
        if dash not in symbols:
            symbols[dash] = ["Not permitted", "Not permitted", ""]
            legend_rows.append([dash, "Not permitted", "Dashed / hyphen = not permitted", ""])

    if "P" not in symbols:
        unresolved.append("legend:P:not found")
    return symbols, blank, legend_rows, unresolved


def write_review(path: Path, city: str, unresolved: list[str], extras: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    # Preserve hand-authored fields (e.g. use_overrides) when regenerating unresolved notes
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    payload = {"city": city, "unresolved": unresolved}
    for keep in ("use_overrides", "category_map", "category_override", "notes", "page"):
        if keep in existing and keep not in (extras or {}):
            payload[keep] = existing[keep]
    if extras:
        payload.update(extras)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_review_overrides(path: Path) -> dict:
    """Load use_overrides from review/<City>.json (empty dict if missing)."""
    data = load_review(path)
    ov = data.get("use_overrides") or {}
    return ov if isinstance(ov, dict) else {}


def load_review(path: Path) -> dict:
    """Load full review/<City>.json payload (empty dict if missing)."""
    import json

    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
