"""M3: run --auto on T1–T3, print match reports; then verify hand-config T1–T4."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zoning.compare_auto import format_match_report, match_report
from zoning.pipeline import run_one

PDFS = ROOT / "tests" / "pdfs"
GOLD = ROOT / "tests" / "golden"
CFG = ROOT / "configs"
OUT = ROOT / "output" / "m3_auto"


CASES = [
    ("Concord", "Code_of_Ordinances_bc6eb4.pdf", "NH_Concord_City_Zoning.xlsx"),
    ("SugarLand", "Sugar_Land__TX_Land_Development_Code.pdf", "TX_SugarLand_City_Zoning.xlsx"),
    ("Abilene", "Abilene__TX_Code_of_Ordinances__1_.pdf", "TX_Abilene_City_Zoning.xlsx"),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for city, pdf_name, gold_name in CASES:
        print(f"\n######## AUTO {city} ########")
        r = run_one(PDFS / pdf_name, None, OUT, None, auto=True)
        print("status", r["status"], "config", r.get("config"), "rows", r["uses"])
        if not r.get("workbook"):
            print("FAIL: no workbook")
            reports.append({"city": city, "symbol_match_pct": 0, "error": "no workbook"})
            continue
        rep = match_report(r["workbook"], GOLD / gold_name, city=city)
        # Always show unpaired keys for Concord / Sugar Land (M3.1 gap analysis)
        show_unpaired = city in ("Concord", "SugarLand")
        print(format_match_report(rep, show_unpaired=show_unpaired))
        if r.get("config") and Path(r["config"]).is_file():
            cfg = json.loads(Path(r["config"]).read_text(encoding="utf-8"))
            print(
                f"generated tables={len(cfg.get('tables', []))} "
                f"zones={len(cfg.get('zones', []))} symbols={list(cfg.get('symbols', {}))[:12]}"
            )
            for tb in cfg.get("tables", []):
                print(f"  table {tb.get('name')} pages={tb.get('pages')} cols={tb.get('columns')}")
        reports.append(rep)

    print("\n######## HAND T1-T4 (must still pass) ########")
    from tests.run_t1_t4 import main as t14

    hand = t14()
    print("hand T1-T4 exit", hand)

    print("\n=== M3.1 SUMMARY ===")
    for r in reports:
        if "error" in r:
            print(f"FAIL {r['city']}: {r['error']}")
        else:
            print(
                f"{r['city']}: symbol {r['symbol_match_pct']}%  "
                f"permission {r['permission_match_pct']}%  "
                f"paired={r['paired_keys']} ({r.get('paired_pct_of_golden', 0)}% of golden)"
            )
    return 0 if hand == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
