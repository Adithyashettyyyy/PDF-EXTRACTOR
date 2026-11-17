"""Openpyxl-only golden workbook compare (no pandas)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

PU_HEADERS = [
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


def _norm(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _sheet_rows(path: Path, sheet: str) -> list[tuple]:
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if not any(c is not None and str(c).strip() for c in row):
            continue
        rows.append(tuple(_norm(c) for c in row))
    wb.close()
    return rows


def compare_with_golden(got_path: str | Path, golden_path: str | Path) -> dict:
    """Compare Zones count + Permitted Uses rows. Returns a result dict."""
    got = Path(got_path)
    golden = Path(golden_path)
    result = {
        "ok": True,
        "got": str(got),
        "golden": str(golden),
        "zones_got": 0,
        "zones_golden": 0,
        "pu_got": 0,
        "pu_golden": 0,
        "mismatches": [],
    }
    if not got.is_file():
        result["ok"] = False
        result["mismatches"].append(f"missing output: {got}")
        return result
    if not golden.is_file():
        result["ok"] = False
        result["mismatches"].append(f"missing golden: {golden}")
        return result

    z_got = _sheet_rows(got, "Zones")
    z_gold = _sheet_rows(golden, "Zones")
    result["zones_got"] = len(z_got)
    result["zones_golden"] = len(z_gold)
    if len(z_got) != len(z_gold):
        result["ok"] = False
        result["mismatches"].append(f"Zones count {len(z_got)} != golden {len(z_gold)}")

    pu_got = _sheet_rows(got, "Permitted Uses")
    pu_gold = _sheet_rows(golden, "Permitted Uses")
    # Keep only the 12 contract columns (goldens may have same width)
    def trim(rows):
        return [r[:12] for r in rows]

    pu_got = trim(pu_got)
    pu_gold = trim(pu_gold)
    result["pu_got"] = len(pu_got)
    result["pu_golden"] = len(pu_gold)

    if pu_got != pu_gold:
        result["ok"] = False
        if len(pu_got) != len(pu_gold):
            result["mismatches"].append(f"Permitted Uses count {len(pu_got)} != golden {len(pu_gold)}")
        # show first few cell diffs
        n = min(len(pu_got), len(pu_gold))
        shown = 0
        for i in range(n):
            if pu_got[i] != pu_gold[i]:
                for j, (a, b) in enumerate(zip(pu_got[i], pu_gold[i])):
                    if a != b:
                        col = PU_HEADERS[j] if j < len(PU_HEADERS) else j
                        result["mismatches"].append(f"row {i+2} {col}: got={a!r} golden={b!r}")
                        shown += 1
                        if shown >= 12:
                            break
            if shown >= 12:
                break
        if shown == 0 and len(pu_got) != len(pu_gold):
            pass
    return result


def format_result(result: dict) -> str:
    status = "PASS" if result["ok"] else "FAIL"
    lines = [
        f"{status}  zones {result['zones_got']}/{result['zones_golden']}  "
        f"permitted_uses {result['pu_got']}/{result['pu_golden']}"
    ]
    for m in result["mismatches"][:20]:
        lines.append(f"  - {m}")
    return "\n".join(lines)
