"""Step 6B: read permitted, conditional, and special-exception lists under each district."""

from __future__ import annotations

import re

from zoning.model import UseRow, Zone
from zoning.reader import PdfDocument
from zoning.textutil import iter_lines, rejoin_hyphens

HEADINGS = (
    (re.compile(r"^(?:principal\s+)?permitted uses(?:\s+by right)?\s*:?$", re.I), "Permitted", "P"),
    (re.compile(r"^uses permitted(?:\s+by right)?\s*:?$", re.I), "Permitted", "P"),
    (re.compile(r"^permitted by right\s*:?$", re.I), "Permitted", "P"),
    (re.compile(r"^conditional uses?\s*:?$", re.I), "Conditional", "C"),
    (re.compile(r"^special exceptions?(?:\s+uses)?\s*:?$", re.I), "Conditional", "SE"),
    (re.compile(r"^specific uses?\s*:?$", re.I), "Conditional", "S"),
    (re.compile(r"^special uses?\s*:?$", re.I), "Conditional", "S"),
    (re.compile(r"^temporary uses?\s*:?$", re.I), "Temporary", "TP"),
    (re.compile(r"^accessory uses?\s*:?$", re.I), "Permitted with conditions", "A"),
    (re.compile(r"^prohibited uses?\s*:?$", re.I), "Not permitted", "-"),
)
BULLET = re.compile(r"^(?:[-*•]|\([a-z0-9]{1,3}\)|\d{1,2}[.)])\s+(.+)$", re.I)
ZONE_START = re.compile(r"^(?:(?:Sec(?:tion)?\.?|§)\s*[0-9A-Za-z.\-]+\s+)?([A-Z]{1,4}(?:-[A-Z0-9]{1,4})+|[A-Z]{2,4})\b")
INHERIT = re.compile(r"all uses permitted in (?:the\s+)?([A-Z0-9-]{2,12})(?:\s+district)?", re.I)
SECTION_BREAK = re.compile(r"^(section|sec\.|article|dimensional|parking|signs|height|yard)\b", re.I)


def parse_lists(doc: PdfDocument, zones: list[Zone]) -> tuple[list[UseRow], bool]:
    known = {zone.zone_code: zone for zone in zones}
    rows: list[UseRow] = []
    current = ""
    mode = ""
    symbol = ""
    permission = ""
    category = ""
    inherit: dict[str, str] = {}
    saw_except = False
    for page, line in iter_lines(doc.pages, keep_blank=True):
        if not line:
            mode = ""
            continue
        zone_code = _zone_on_line(line, known)
        if zone_code and _looks_like_heading(line, zone_code):
            current = zone_code
            mode = ""
            category = ""
            continue
        if current and INHERIT.search(line):
            parent = INHERIT.search(line).group(1)
            if parent in known and parent != current:
                inherit[current] = parent
            if re.search(r"\bexcept\b", line, re.I):
                saw_except = True
        heading = _heading(line)
        if heading:
            permission, symbol = heading
            mode = permission
            continue
        if SECTION_BREAK.match(line):
            mode = ""
            continue
        if not mode or not current:
            continue
        if re.search(r"\buses$", line, re.I) and not BULLET.match(line):
            category = line
            continue
        name = _item(line)
        if not name:
            continue
        rows.append(
            UseRow(
                zone_code=current,
                use_category=category,
                use_name=name,
                symbol=symbol,
                permission=permission,
                source_section=f"p. {page}",
                page=page,
                column_header=current,
            )
        )
    rows.extend(_inherited(rows, inherit))
    return rows, saw_except


def _inherited(rows: list[UseRow], inherit: dict[str, str]) -> list[UseRow]:
    by_zone: dict[str, list[UseRow]] = {}
    for row in rows:
        by_zone.setdefault(row.zone_code, []).append(row)
    added = []
    for zone_code, parent in inherit.items():
        have = {(row.use_name.lower(), row.permission) for row in by_zone.get(zone_code, [])}
        for source in by_zone.get(parent, []):
            key = (source.use_name.lower(), source.permission)
            if key in have:
                continue
            added.append(
                UseRow(
                    zone_code=zone_code,
                    use_category=source.use_category,
                    use_name=source.use_name,
                    symbol=source.symbol,
                    permission=source.permission,
                    approval_route=f"Included because this district allows the uses of {parent}.",
                    approval_body=source.approval_body,
                    source_section=source.source_section,
                    page=source.page,
                    column_header=zone_code,
                )
            )
            have.add(key)
    return added


def _heading(line: str):
    for pattern, permission, symbol in HEADINGS:
        if pattern.match(line):
            return permission, symbol
    return None


def _zone_on_line(line: str, known: dict[str, Zone]) -> str:
    match = ZONE_START.match(line)
    if not match:
        return ""
    code = match.group(1)
    if code in known:
        return code
    return ""


def _looks_like_heading(line: str, code: str) -> bool:
    if line.startswith(code) and len(line) < 120 and "shall" not in line.lower():
        return True
    return False


def _item(line: str) -> str:
    match = BULLET.match(line)
    text = match.group(1) if match else line
    text = rejoin_hyphens(text).strip(" ;,")
    if "=" in text or len(text) < 3 or len(text) > 100:
        return ""
    if len(text.split()) > 14:
        return ""
    if text.endswith(".") and len(text.split()) > 8:
        return ""
    if not match and len(text.split()) > 8:
        return ""
    return text
