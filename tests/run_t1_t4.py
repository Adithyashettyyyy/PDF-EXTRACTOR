"""Run golden tests T1–T4 (M1). Exit 0 only if all pass."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zoning.pipeline import run_one

PDFS = ROOT / "tests" / "pdfs"
GOLD = ROOT / "tests" / "golden"
CFG = ROOT / "configs"
OUT = ROOT / "output" / "m1_tests"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []

    # T1 Concord
    print("=== T1 Concord ===")
    r1 = run_one(
        PDFS / "Code_of_Ordinances_bc6eb4.pdf",
        CFG / "NH_Concord.json",
        OUT,
        GOLD / "NH_Concord_City_Zoning.xlsx",
    )
    t1 = r1["status"] == "OK" and r1["golden"] and r1["golden"]["ok"]
    results.append(("T1 Concord", t1, r1))

    # T2 Sugar Land
    print("=== T2 Sugar Land ===")
    r2 = run_one(
        PDFS / "Sugar_Land__TX_Land_Development_Code.pdf",
        CFG / "TX_SugarLand.json",
        OUT,
        GOLD / "TX_SugarLand_City_Zoning.xlsx",
    )
    t2 = r2["status"] == "OK" and r2["golden"] and r2["golden"]["ok"]
    results.append(("T2 Sugar Land", t2, r2))

    # T3 Abilene
    print("=== T3 Abilene ===")
    r3 = run_one(
        PDFS / "Abilene__TX_Code_of_Ordinances__1_.pdf",
        CFG / "TX_Abilene.json",
        OUT,
        GOLD / "TX_Abilene_City_Zoning.xlsx",
    )
    t3 = r3["status"] == "OK" and r3["golden"] and r3["golden"]["ok"]
    results.append(("T3 Abilene", t3, r3))

    # T4 Keene gate (no config / no tables)
    print("=== T4 Keene gate ===")
    r4 = run_one(PDFS / "Code_of_Ordinances.pdf", None, OUT, None)
    ptr_pages = [x for x in r4["log"] if x[0] == "external_pointer"]
    t4 = r4["status"] == "ZONING_NOT_IN_PDF" and r4["workbook"] is None and bool(ptr_pages)
    # Prefer page 799 if present
    pages = ",".join(x[5] for x in ptr_pages)
    print(f"T4 status={r4['status']} pointer_pages={pages} workbook={r4['workbook']}")
    results.append(("T4 Keene", t4, r4))

    print("\n=== SUMMARY ===")
    all_ok = True
    for name, ok, r in results:
        mark = "PASS" if ok else "FAIL"
        extra = ""
        if r.get("golden"):
            extra = f" zones={r['golden']['zones_got']}/{r['golden']['zones_golden']} pu={r['golden']['pu_got']}/{r['golden']['pu_golden']}"
        elif name.startswith("T4"):
            extra = f" status={r['status']}"
        print(f"{mark}  {name}{extra}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
