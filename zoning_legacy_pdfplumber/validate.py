"""Step 8: check the rows before they are written."""

from __future__ import annotations

import random

from zoning.legend import symbol_known
from zoning.model import Check, LegendEntry, UseRow, Zone


def validate(zones: list[Zone], rows: list[UseRow], legend: list[LegendEntry]) -> list[Check]:
    checks = []
    in_rules = {row.zone_code for row in rows}
    in_list = {zone.zone_code for zone in zones}
    extra = sorted(in_rules - in_list)
    missing = sorted(
        zone.zone_code
        for zone in zones
        if zone.zone_code not in in_rules and zone.zone_type not in ("Overlay district", "Special district")
    )
    if extra or missing:
        detail = []
        if extra:
            detail.append("in the use rules only: " + ", ".join(extra))
        if missing:
            detail.append("in the zone list only: " + ", ".join(missing))
        checks.append(Check("zone_match", "WARN", "; ".join(detail)))
    else:
        checks.append(Check("zone_match", "PASS", "Every use-rule zone is in the zone list, and the reverse."))

    uses = list(dict.fromkeys(row.use_name for row in rows))
    zones_with_rules = [zone for zone in zones if zone.zone_code in in_rules]
    expected = len(uses) * len(zones_with_rules)
    got = len({(row.zone_code, row.use_name) for row in rows})
    if not rows:
        checks.append(Check("grid_complete", "FAIL", "No use rows were read."))
    elif got != expected:
        checks.append(Check("grid_complete", "FAIL", f"{got} zone-use rows; {len(uses)} uses × {len(zones_with_rules)} zones would be {expected}."))
    else:
        checks.append(Check("grid_complete", "PASS", f"{got} rows = {len(uses)} uses × {len(zones_with_rules)} zones."))

    unknown = sorted({row.symbol for row in rows if row.symbol and not symbol_known(row.symbol, legend)})
    if unknown:
        checks.append(Check("legend_coverage", "FAIL", "Symbols with no legend entry: " + ", ".join(unknown)))
    elif rows:
        checks.append(Check("legend_coverage", "PASS", "Every symbol is in this city's legend."))
    else:
        checks.append(Check("legend_coverage", "FAIL", "No symbols were read."))

    empty = sum(1 for row in rows if not row.permission)
    if empty:
        checks.append(Check("no_empty_permission", "FAIL", f"{empty} rows have no permission."))
    elif rows:
        checks.append(Check("no_empty_permission", "PASS", "Every row has a permission."))
    else:
        checks.append(Check("no_empty_permission", "FAIL", "No rows."))

    if rows:
        unclear = sum(1 for row in rows if row.permission == "Unclear")
        rate = unclear / len(rows)
        if rate > 0.05:
            checks.append(Check("unclear_rate", "WARN", f"{unclear} of {len(rows)} rows are Unclear ({rate:.0%})."))
        else:
            checks.append(Check("unclear_rate", "PASS", f"{unclear} of {len(rows)} rows are Unclear."))
    shown = _spot(rows)
    checks.append(Check("spot_check", "INFO", f"{shown} rows printed for a manual compare."))
    return checks


def _spot(rows: list[UseRow]) -> int:
    if not rows:
        return 0
    sample = rows if len(rows) <= 10 else random.Random(0).sample(rows, 10)
    print("Spot check (compare these rows to the PDF):")
    for row in sample:
        print(f"  p.{row.page or '?'}  {row.zone_code} | {row.use_name} | {row.symbol or '-'} | {row.permission}")
    return len(sample)
