"""S9: write the four-sheet Excel (openpyxl only, no pandas)."""

from __future__ import annotations

import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(v):
    if v is None:
        return ""
    if not isinstance(v, str):
        return v
    return _ILLEGAL.sub("", v)

ZC = [
    "state",
    "municipality",
    "type",
    "county",
    "zone_code",
    "zone_name",
    "zone_group",
    "zone_type",
    "zone_meaning",
    "use_table_column",
    "source_section",
]
UC = [
    "state",
    "municipality",
    "type",
    "county",
    "zone_code",
    "use_category",
    "use_name",
    "symbol",
    "permission",
    "approval_route",
    "approval_body",
    "source_section",
]
FILL = {
    "Permitted": "C6EFCE",
    "Permitted with conditions": "E2F0D9",
    "Conditional": "FFEB9C",
    "Not permitted": "F2F2F2",
    "Unclear": "F8CBAD",
    "Temporary": "DDEBF7",
}


def _write_sheet(ws, headers, rows):
    ws.append(headers)
    for row in rows:
        if isinstance(row, dict):
            ws.append([_clean(row.get(h, "")) for h in headers])
        else:
            ws.append([_clean(v) for v in row])


def _autosize(ws, max_width=60):
    for idx, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value or "")) for c in col), default=0) + 2
        ws.column_dimensions[get_column_letter(idx)].width = min(max_width, width)


def build(path, meta, zones, uses, legend, source):
    zone_rows = []
    for z in zones:
        row = {**z, **meta}
        for c in ZC:
            row.setdefault(c, "")
        zone_rows.append(row)

    use_rows = []
    matrix_keys = []
    symbols = {}
    perms = {}
    if uses:
        for u in uses:
            row = {**u, **meta}
            for c in UC:
                row.setdefault(c, "")
            use_rows.append(row)
            key = (row.get("use_category") or "", row.get("use_name") or "")
            if key not in symbols:
                matrix_keys.append(key)
                symbols[key] = {}
                perms[key] = {}
            symbols[key][row["zone_code"]] = str(row.get("symbol") or "")
            perms[key][row["zone_code"]] = row.get("permission") or ""
        order = [z["zone_code"] for z in zone_rows if z["zone_code"] in {u["zone_code"] for u in use_rows}]
    else:
        use_rows = [
            {
                **meta,
                "use_category": "(not extracted yet)",
                "use_name": "Use table not available in the source provided",
                "permission": "Unclear",
            }
        ]
        for c in UC:
            use_rows[0].setdefault(c, "")
        order = []
        matrix_keys = [("(not extracted yet)", "Use table not available in the source provided")]
        symbols = {matrix_keys[0]: {}}
        perms = None

    wb = Workbook()
    ws_z = wb.active
    ws_z.title = "Zones"
    _write_sheet(ws_z, ZC, zone_rows)

    ws_m = wb.create_sheet("Use Matrix")
    matrix_headers = ["use_category", "use_name"] + order
    ws_m.append(matrix_headers)
    for key in matrix_keys:
        ws_m.append([_clean(key[0]), _clean(key[1])] + [_clean(symbols[key].get(z, "")) for z in order])

    ws_u = wb.create_sheet("Permitted Uses")
    _write_sheet(ws_u, UC, use_rows)

    ws_l = wb.create_sheet("Legend")
    lg_headers = ["symbol", "permission", "meaning", "approved_by"]
    ws_l.append(lg_headers)
    for item in legend:
        if isinstance(item, dict):
            ws_l.append([item.get(h, "") for h in lg_headers])
        else:
            ws_l.append(list(item) + [""] * (4 - len(item)))
    ws_l.append([])
    ws_l.append(["Source document", source])
    ws_l.append(
        [
            "Municipality",
            f"{meta['municipality']}, {meta['state']} ({meta['type']}, {meta['county']})",
        ]
    )

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                cell.font = Font(name="Arial", size=10, bold=(cell.row == 1))
        ws.freeze_panes = "C2" if ws.title == "Use Matrix" else "A2"
        if ws.title != "Legend" and ws.max_row >= 1 and ws.max_column >= 1:
            ws.auto_filter.ref = ws.dimensions
        _autosize(ws)

    if perms is not None and order:
        for i, key in enumerate(matrix_keys):
            for j, zone in enumerate(order):
                cell = ws_m.cell(row=i + 2, column=j + 3)
                p = perms[key].get(zone)
                if p in FILL:
                    cell.fill = PatternFill("solid", fgColor=FILL[p])
                    cell.alignment = Alignment(horizontal="center")
        for j in range(3, 3 + len(order)):
            ws_m.column_dimensions[get_column_letter(j)].width = 9

    ws_z.column_dimensions["I"].width = 80
    for row in ws_z.iter_rows(min_row=2):
        row[8].alignment = Alignment(wrap_text=True, vertical="top")
    ws_l.column_dimensions["B"].width = 28
    ws_l.column_dimensions["C"].width = 70
    wb.save(path)
    return len(zone_rows), len(use_rows)
