"""Compare auto extract vs golden on zone_code+use_category+use_name → symbol/permission."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook


def _pu_rows(path: Path) -> list[dict]:
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb["Permitted Uses"]
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        d = {headers[i]: ("" if row[i] is None else str(row[i]).strip()) for i in range(len(headers))}
        if d.get("zone_code") and d.get("use_name"):
            rows.append(d)
    wb.close()
    return rows


def _row_key(r: dict) -> tuple[str, str, str]:
    return (r.get("zone_code") or "", r.get("use_category") or "", r.get("use_name") or "")


def _index_rows(rows: list[dict]) -> dict[tuple, list[dict]]:
    """Map full key → list of rows (preserves duplicates / total-row accounting)."""
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        idx[_row_key(r)].append(r)
    return idx


def match_report(got_path: str | Path, golden_path: str | Path, city: str = "") -> dict:
    got = _pu_rows(Path(got_path))
    gold = _pu_rows(Path(golden_path))
    gmap = _index_rows(gold)
    amap = _index_rows(got)

    g_keys = set(gmap)
    a_keys = set(amap)
    paired_keys = g_keys & a_keys

    # Pair by key using min(count) so duplicate names in different categories
    # and repeated keys still contribute to total-row stats.
    paired_n = sym_ok = perm_ok = 0
    sym_miss: list[str] = []
    perm_miss: list[str] = []
    unclear_symbols: set[str] = set()

    for key in paired_keys:
        g_list, a_list = gmap[key], amap[key]
        n = min(len(g_list), len(a_list))
        paired_n += n
        for i in range(n):
            g, a = g_list[i], a_list[i]
            z, cat, use = key
            label = f"{z} | {cat[:24] + ' / ' if cat else ''}{use[:40]}"
            if a.get("symbol") == g.get("symbol"):
                sym_ok += 1
            else:
                if len(sym_miss) < 20:
                    sym_miss.append(f"{label}: got={a.get('symbol')!r} gold={g.get('symbol')!r}")
            if a.get("permission") == g.get("permission"):
                perm_ok += 1
            else:
                if len(perm_miss) < 20:
                    perm_miss.append(
                        f"{label}: got={a.get('permission')!r} gold={g.get('permission')!r} "
                        f"sym={a.get('symbol')!r}"
                    )
                if a.get("permission") == "Unclear":
                    unclear_symbols.add(a.get("symbol") or "")

    # Unpaired = leftover rows after pairing (total-row based)
    only_gold_n = only_auto_n = 0
    only_gold_keys: list[str] = []
    only_auto_keys: list[str] = []
    for key in sorted(g_keys | a_keys):
        z, cat, use = key
        label = f"{z} | {(cat + ' / ') if cat else ''}{use[:60]}"
        gc = len(gmap.get(key, []))
        ac = len(amap.get(key, []))
        if gc > ac:
            only_gold_n += gc - ac
            if len(only_gold_keys) < 30:
                only_gold_keys.append(label + (f" x{gc - ac}" if gc - ac > 1 else ""))
        if ac > gc:
            only_auto_n += ac - gc
            if len(only_auto_keys) < 30:
                only_auto_keys.append(label + (f" x{ac - gc}" if ac - gc > 1 else ""))

    n = max(1, paired_n)
    gold_n = max(1, len(gold))
    report = {
        "city": city,
        "got_rows": len(got),
        "golden_rows": len(gold),
        "paired_keys": paired_n,
        "paired_pct_of_golden": round(100.0 * paired_n / gold_n, 2),
        "only_auto": only_auto_n,
        "only_golden": only_gold_n,
        "only_auto_keys": only_auto_keys,
        "only_golden_keys": only_gold_keys,
        "symbol_match_pct": round(100.0 * sym_ok / n, 2),
        "permission_match_pct": round(100.0 * perm_ok / n, 2),
        "symbol_mismatches": sym_miss,
        "permission_mismatches": perm_miss,
        "unclear_symbols": sorted(s for s in unclear_symbols if s),
    }
    return report


def format_match_report(r: dict, show_unpaired: bool = True) -> str:
    lines = [
        f"=== AUTO MATCH: {r['city']} ===",
        f"rows auto={r['got_rows']} golden={r['golden_rows']} paired={r['paired_keys']} "
        f"({r.get('paired_pct_of_golden', 0)}% of golden) "
        f"only_auto={r['only_auto']} only_golden={r['only_golden']}",
        f"symbol match:     {r['symbol_match_pct']}%",
        f"permission match: {r['permission_match_pct']}%",
    ]
    if r["unclear_symbols"]:
        lines.append(f"unclear symbols (legend review): {', '.join(r['unclear_symbols'])}")
    if r["symbol_mismatches"]:
        lines.append("symbol mismatches (max 20):")
        lines.extend(f"  - {m}" for m in r["symbol_mismatches"])
    if r["permission_mismatches"]:
        lines.append("permission mismatches (max 20):")
        lines.extend(f"  - {m}" for m in r["permission_mismatches"])
    if show_unpaired:
        if r.get("only_golden_keys"):
            lines.append("only_golden keys (max 30):")
            lines.extend(f"  - {k}" for k in r["only_golden_keys"])
        if r.get("only_auto_keys"):
            lines.append("only_auto keys (max 30):")
            lines.extend(f"  - {k}" for k in r["only_auto_keys"])
    return "\n".join(lines)
