"""One PDF in. A run log always. A four-sheet workbook when the uses are in that PDF.

Steps follow the zoning spec:
  0 read the PDF
  1 name the ordinance
  2 gate: is zoning in this file
  3 zone list
  4 format
  5 legend
  6 use table or per-district lists
  7 duplicate use names
  8 validation
  9 run log
  10 workbook
"""

from __future__ import annotations

import re
from pathlib import Path

from zoning import claude
from zoning.gate import run_gate
from zoning.legend import find_legend, lookup, permission_for
from zoning.lists import parse_lists
from zoning.model import Check, UseRow, Zone
from zoning.normalize import normalize
from zoning.reader import PdfDocument, file_stem, identify_place
from zoning.tables import parse_tables
from zoning.textutil import page_list
from zoning.validate import validate
from zoning.workbook import append_log, write_city
from zoning.zones import find_zones


def analyze(pdf_path: Path, outdir: Path, overrides: dict) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    place = {key: overrides.get(key, "") for key in ("state", "municipality", "type", "county")}
    log_path = outdir / "run_log.csv"
    try:
        with PdfDocument(pdf_path) as doc:
            print(f"Reading  {pdf_path.name} ({doc.page_count} pages)")
            doc.read_text()
            place = identify_place(doc.pages, overrides)
            gate = run_gate(doc)
            checks = list(gate.checks)
            if gate.stop:
                _status(checks, gate.status)
                append_log(log_path, pdf_path.name, place, checks)
                _print_flag(place, pdf_path, gate.status, log_path)
                return 1 if gate.status == "SCANNED_PDF" else 2

            zones, invented = find_zones(doc)
            if invented:
                labels = ", ".join(zone.zone_code for zone in zones) or "none"
                checks.append(
                    Check(
                        "zone_codes_invented",
                        "WARN",
                        f"District names had no printed codes. Short labels were assigned: {labels}",
                    )
                )
            legend, rule = find_legend(doc, gate.use_pages or gate.zoning_pages)
            checks.append(
                Check(
                    "legend_found",
                    "PASS" if legend else "WARN",
                    f"{len(legend)} symbols were read from this PDF."
                    if legend
                    else "No legend was found. Unknown symbols stay Unclear.",
                )
            )

            table_rows, meta = parse_tables(doc, zones, gate.use_pages)
            list_rows, saw_except = parse_lists(doc, zones)
            rows, kind = _choose(table_rows, list_rows)
            checks.append(Check("use_format", "INFO", _format_message(kind, meta.pages, meta.rotated)))
            if saw_except:
                checks.append(
                    Check(
                        "cumulative_exceptions",
                        "WARN",
                        "A district inherits uses and also says except. Inherited uses were copied; exceptions were not removed.",
                    )
                )
            zones = _add_discovered(zones, meta)
            if claude.api_key() and (kind in {"lists", "mixed", "none"} or len(zones) < 2):
                rows, zones, legend, rule, checks = _ask_claude(
                    doc, place, gate, checks, zones, legend, rule, rows, kind
                )

            if zones:
                _replace(
                    checks,
                    "zone_list_found",
                    "PASS",
                    f"{len(zones)} districts were read from this PDF.",
                    page_list([zone.page for zone in zones if zone.page]),
                )
            if not rows:
                _replace(
                    checks,
                    "use_list_found",
                    "FAIL",
                    "Zoning text is in this PDF, but no use table or district use list could be read.",
                )
                _status(checks, "NO_USE_TABLE")
                _remove_workbook(outdir, place)
                append_log(log_path, pdf_path.name, place, checks)
                _print_flag(place, pdf_path, "NO_USE_TABLE", log_path)
                return 2

            rows, merges = normalize(rows)
            if merges:
                shown = "; ".join(f"{old} -> {new}" for old, new in merges[:12])
                checks.append(Check("use_names_merged", "INFO", shown))
            rows = _permissions(rows, legend, rule)
            rows = _dedupe(rows)
            rows = _fill(rows, zones, rule)
            checks.extend(validate(zones, rows, legend))
            _replace(
                checks,
                "use_list_found",
                "PASS",
                f"{len({row.use_name for row in rows})} uses across {len({row.zone_code for row in rows})} zones.",
                page_list(meta.pages),
            )
            _status(checks, "OK")
            workbook = outdir / f"{file_stem(place)}.xlsx"
            write_city(workbook, place, zones, rows, legend, gate.source.line())
            append_log(log_path, pdf_path.name, place, checks)
            _print_ok(place, pdf_path, zones, rows, workbook, log_path, checks)
            return 0
    except Exception as exc:
        checks = [Check("reader", "FAIL", str(exc)), Check("document_status", "INFO", "ERROR")]
        try:
            append_log(log_path, pdf_path.name, place, checks)
        except Exception:
            pass
        print(f"ERROR    {pdf_path.name}: {exc}")
        print(f"Log      {log_path}")
        return 1


def _choose(table_rows: list[UseRow], list_rows: list[UseRow]) -> tuple[list[UseRow], str]:
    table_zones = {row.zone_code for row in table_rows}
    extra = [row for row in list_rows if row.zone_code not in table_zones]
    if table_rows and extra:
        return table_rows + extra, "mixed"
    if table_rows:
        return table_rows, "grid"
    if list_rows:
        return list_rows, "lists"
    return [], "none"


def _format_message(kind: str, pages: list[int], rotated: bool) -> str:
    where = page_list(pages) or "none"
    if kind == "grid" and rotated:
        return f"Rotated use matrix on pages {where}."
    if kind == "grid":
        return f"Use grid on pages {where}."
    if kind == "mixed":
        return f"A use grid plus per-district lists. Table pages: {where}."
    if kind == "lists":
        return "Per-district permitted and conditional lists."
    return "No use grid or district list could be read."


def _add_discovered(zones: list[Zone], meta) -> list[Zone]:
    existing = {zone.zone_code for zone in zones}
    for code, page, column in meta.discovered:
        if code in existing:
            continue
        zones.append(
            Zone(
                zone_code=code,
                zone_name=code,
                zone_type="Base district",
                use_table_column=column,
                source_section=f"use table p. {page}",
                page=page,
            )
        )
        existing.add(code)
    for zone in zones:
        column = meta.columns.get(zone.zone_code, "")
        if column:
            zone.use_table_column = column
        if not zone.zone_meaning and zone.zone_name and zone.zone_name != zone.zone_code:
            zone.zone_meaning = zone.zone_name.rstrip(".") + "."
    return zones


def _ask_claude(doc, place, gate, checks, zones, legend, rule, rows, kind):
    pages = gate.use_pages or gate.zoning_pages or list(range(1, min(doc.page_count, 20) + 1))
    try:
        remote = claude.ask(doc, place, gate.source.line(), pages)
        zones, legend, rule, rows, note = claude.merge(zones, legend, rule, rows, remote, kind)
        checks.append(Check("claude", "PASS" if remote else "WARN", note))
    except Exception as exc:
        checks.append(Check("claude", "WARN", f"Claude was not used: {exc}"))
    return rows, zones, legend, rule, checks


def _permissions(rows: list[UseRow], legend, rule) -> list[UseRow]:
    for row in rows:
        permission, stored = permission_for(row.symbol, legend, rule)
        if permission == "Unclear" and row.permission and row.permission != "Unclear":
            permission = row.permission
        else:
            row.symbol = stored or row.symbol
        row.permission = permission
        entry = lookup(row.symbol, legend)
        if entry and not row.approval_body:
            row.approval_body = entry.approved_by
        if not row.approval_route and entry and permission == "Conditional":
            row.approval_route = entry.meaning[:180]
        if _has_marker(row.symbol) and "supplemental" not in row.approval_route.lower():
            note = re.search(r"\(([A-Za-z0-9]+)\)", row.symbol)
            extra = f"supplemental regulations apply (note {note.group(1)})" if note else "supplemental regulations apply"
            row.approval_route = "; ".join(part for part in (row.approval_route, extra) if part)[:180]
        if not row.source_section and row.page:
            row.source_section = f"p. {row.page}"
    return rows


def _dedupe(rows: list[UseRow]) -> list[UseRow]:
    kept: dict[tuple[str, str], UseRow] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row.zone_code, row.use_name)
        if key not in kept:
            kept[key] = row
            order.append(key)
            continue
        current = kept[key]
        if not current.use_category and row.use_category:
            current.use_category = row.use_category
        if current.symbol and row.symbol and current.symbol != row.symbol:
            current.permission = "Unclear"
            current.approval_route = f"Conflicting symbols {current.symbol} and {row.symbol}."
    return [kept[key] for key in order]


def _fill(rows: list[UseRow], zones: list[Zone], rule) -> list[UseRow]:
    categories: dict[str, str] = {}
    present = set()
    for row in rows:
        categories.setdefault(row.use_name, row.use_category)
        present.add((row.zone_code, row.use_name))
    have = {row.zone_code for row in rows}
    order = [zone.zone_code for zone in zones if zone.zone_code in have]
    for code in have:
        if code not in order:
            order.append(code)
    missing = "Not permitted" if rule.blank_is_prohibited or rule.missing_uses_are == "Not permitted" else (rule.missing_uses_are or "Unclear")
    symbol = "-" if missing == "Not permitted" else ""
    route = "Not listed for this district." if missing == "Not permitted" else ""
    filled = list(rows)
    names = list(categories)
    if len(names) > 2500:
        names = names[:2500]
    for name in names:
        sample = next(row for row in rows if row.use_name == name)
        for code in order:
            if (code, name) in present:
                continue
            filled.append(
                UseRow(
                    zone_code=code,
                    use_category=categories[name],
                    use_name=name,
                    symbol=symbol,
                    permission=missing,
                    approval_route=route,
                    source_section=sample.source_section,
                    page=sample.page,
                    column_header=code,
                )
            )
    return filled


def _has_marker(symbol: str) -> bool:
    return bool(re.search(r"\*|\([A-Za-z0-9]+\)", symbol or ""))


def _replace(checks: list[Check], name: str, result: str, message: str, pages: str = "") -> None:
    for check in checks:
        if check.check == name:
            check.result = result
            check.message = message
            if pages:
                check.pages = pages
            return
    checks.append(Check(name, result, message, pages=pages))


def _status(checks: list[Check], status: str) -> None:
    for check in checks:
        if check.check == "document_status":
            check.message = status
            return
    checks.append(Check("document_status", "INFO", status))


def _remove_workbook(outdir: Path, place: dict) -> None:
    path = outdir / f"{file_stem(place)}.xlsx"
    if path.exists():
        path.unlink()


def _city(place: dict, pdf_path: Path) -> str:
    name = place.get("municipality") or pdf_path.name
    state = place.get("state") or ""
    return f"{name}, {state}".strip(", ")


def _print_flag(place, pdf_path, status, log_path) -> None:
    print(f"FLAGGED  {_city(place, pdf_path)}")
    print(f"Status   {status}")
    print(f"Log      {log_path}")


def _print_ok(place, pdf_path, zones, rows, workbook, log_path, checks) -> None:
    failed = [check.check for check in checks if check.result == "FAIL"]
    print(f"OK       {_city(place, pdf_path)}")
    print(f"Zones    {len(zones)}")
    print(f"Rows     {len(rows)}")
    print(f"Workbook {workbook}")
    print(f"Log      {log_path}")
    if failed:
        print("Failed   " + ", ".join(failed))
