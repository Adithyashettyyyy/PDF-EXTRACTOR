"""Step 10: write one city workbook and append the run log."""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from zoning.model import Check, LegendEntry, UseRow, Zone
from zoning.schema import (
    LEGEND_HEADERS,
    MATRIX_LEAD,
    PERMISSION_COLORS,
    PERMITTED_HEADERS,
    RUN_LOG_HEADERS,
    SHEET_WIDTHS,
    ZONE_HEADERS,
)

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
BODY_FONT = Font(name="Arial", size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Border(
    left=Side(style="thin", color="D0D7DE"),
    right=Side(style="thin", color="D0D7DE"),
    top=Side(style="thin", color="D0D7DE"),
    bottom=Side(style="thin", color="D0D7DE"),
)


def write_city(
    path: Path,
    place: dict,
    zones: list[Zone],
    rows: list[UseRow],
    legend: list[LegendEntry],
    source_line: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    zone_sheet = workbook.active
    zone_sheet.title = "Zones"
    _write_zones(zone_sheet, place, zones)
    matrix = workbook.create_sheet("Use Matrix")
    _write_matrix(matrix, zones, rows)
    permitted = workbook.create_sheet("Permitted Uses")
    _write_permitted(permitted, place, rows)
    legend_sheet = workbook.create_sheet("Legend")
    _write_legend(legend_sheet, legend, source_line, _municipality_line(place))
    workbook.save(path)


def append_log(path: Path, file_name: str, place: dict, checks: list[Check]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            existing = [row for row in csv.DictReader(handle) if row.get("file") != file_name]
    for check in checks:
        existing.append(
            {
                "file": file_name,
                "state": place.get("state", ""),
                "municipality": place.get("municipality", ""),
                "type": place.get("type", ""),
                "county": place.get("county", ""),
                "check": check.check,
                "result": check.result,
                "message": check.message,
                "link_raw": check.link_raw,
                "link_guess": check.link_guess,
                "pages": check.pages,
            }
        )
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)


def _write_zones(sheet, place: dict, zones: list[Zone]) -> None:
    sheet.append(ZONE_HEADERS)
    for zone in zones:
        sheet.append(
            [
                place.get("state", ""),
                place.get("municipality", ""),
                place.get("type", ""),
                place.get("county", ""),
                zone.zone_code,
                zone.zone_name,
                zone.zone_group,
                zone.zone_type,
                zone.zone_meaning,
                zone.use_table_column,
                zone.source_section,
            ]
        )
    _style(sheet, SHEET_WIDTHS["Zones"], sheet.max_row)
    for row in sheet.iter_rows(min_row=2, min_col=5, max_col=5):
        row[0].number_format = "@"


def _write_matrix(sheet, zones: list[Zone], rows: list[UseRow]) -> None:
    codes = [zone.zone_code for zone in zones if any(row.zone_code == zone.zone_code for row in rows)]
    extra = [code for code in dict.fromkeys(row.zone_code for row in rows) if code not in codes]
    codes.extend(extra)
    sheet.append(MATRIX_LEAD + codes)
    order: list[str] = []
    categories: dict[str, str] = {}
    grid: dict[tuple[str, str], UseRow] = {}
    for row in rows:
        if row.use_name not in categories:
            categories[row.use_name] = row.use_category
            order.append(row.use_name)
        grid[(row.use_name, row.zone_code)] = row
    for name in order:
        values = [categories[name], name]
        for code in codes:
            item = grid.get((name, code))
            values.append(item.symbol if item else "")
        sheet.append(values)
    widths = [22, 42] + [max(8, len(code) + 2) for code in codes]
    _style(sheet, widths, sheet.max_row)
    sheet.freeze_panes = "C2"
    for cell in sheet[1][2:]:
        cell.number_format = "@"
    for row in sheet.iter_rows(min_row=2, min_col=3, max_col=2 + len(codes)):
        for cell in row:
            item = grid.get((sheet.cell(cell.row, 2).value, codes[cell.column - 3]))
            if item is None:
                continue
            cell.number_format = "@"
            color = PERMISSION_COLORS.get(item.permission)
            if color:
                cell.fill = PatternFill("solid", fgColor=color)


def _write_permitted(sheet, place: dict, rows: list[UseRow]) -> None:
    sheet.append(PERMITTED_HEADERS)
    ordered = sorted(rows, key=lambda row: (row.zone_code, row.use_category, row.use_name))
    for row in ordered:
        sheet.append(
            [
                place.get("state", ""),
                place.get("municipality", ""),
                place.get("type", ""),
                place.get("county", ""),
                row.zone_code,
                row.use_category,
                row.use_name,
                row.symbol,
                row.permission,
                row.approval_route,
                row.approval_body,
                row.source_section,
            ]
        )
    _style(sheet, SHEET_WIDTHS["Permitted Uses"], sheet.max_row)
    for row in sheet.iter_rows(min_row=2, min_col=5, max_col=5):
        row[0].number_format = "@"
    for row in sheet.iter_rows(min_row=2, min_col=8, max_col=8):
        row[0].number_format = "@"


def _write_legend(sheet, legend: list[LegendEntry], source_line: str, municipality: str) -> None:
    sheet.append(LEGEND_HEADERS)
    for entry in legend:
        sheet.append([entry.symbol, entry.permission, entry.meaning, entry.approved_by])
    last = max(sheet.max_row, 1)
    _style(sheet, SHEET_WIDTHS["Legend"], last)
    for row in sheet.iter_rows(min_row=2, max_row=last, min_col=1, max_col=1):
        row[0].number_format = "@"
    sheet.append([])
    sheet.append(["Source document", source_line])
    sheet.append(["Municipality", municipality])
    for row_number in (sheet.max_row - 1, sheet.max_row):
        for cell in sheet[row_number]:
            cell.font = Font(name="Arial", size=10, italic=True)


def _style(sheet, widths: list[int], last_row: int) -> None:
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    if last_row >= 2:
        for row in sheet.iter_rows(min_row=2, max_row=last_row):
            for cell in row:
                cell.font = BODY_FONT
                cell.alignment = WRAP
                cell.border = THIN
                if isinstance(cell.value, str) and cell.value.startswith(("=", "+", "@")):
                    cell.value = "'" + cell.value
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    last_column = get_column_letter(max(1, sheet.max_column))
    sheet.auto_filter.ref = f"A1:{last_column}{max(last_row, 1)}"
    sheet.freeze_panes = "A2"
    sheet.row_dimensions[1].height = 22
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.auto_filter.ref = f"A1:{last_column}{max(last_row, 1)}"
    sheet.sheet_view.showGridLines = False


def _municipality_line(place: dict) -> str:
    county = place.get("county") or ""
    if county and not county.lower().endswith("county"):
        county = f"{county} County"
    left = ", ".join(part for part in (place.get("municipality", ""), place.get("state", "")) if part)
    right = ", ".join(part for part in (place.get("type", ""), county) if part)
    if left and right:
        return f"{left} ({right})"
    return left or right
