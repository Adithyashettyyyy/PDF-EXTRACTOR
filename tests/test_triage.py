"""Automated triage expectations for the 5 kit PDFs (M2)."""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zoning.triage import run_triage, triage_one

PDFS = ROOT / "tests" / "pdfs"
OUT = ROOT / "output" / "triage_test.csv"


class TriageFivePdfs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.unlink(missing_ok=True)
        cls.summary = run_triage(PDFS, OUT, workers=2, timeout=300, force=True)
        cls.rows = cls.summary["rows"]

    def _row(self, name: str) -> dict:
        self.assertIn(name, self.rows, f"missing triage row for {name}")
        return self.rows[name]

    def test_concord_bucket_a_rotated(self):
        r = self._row("Code_of_Ordinances_bc6eb4.pdf")
        self.assertEqual(r["bucket"], "A")
        self.assertEqual(r["rotated"], "yes")
        pages = {int(p) for p in r["table_pages"].split(",") if p}
        for p in range(829, 838):
            self.assertIn(p, pages, f"Concord table_pages missing {p}: {r['table_pages']}")
        self.assertEqual(r["status"], "OK")

    def test_sugar_land_bucket_a_rotated(self):
        r = self._row("Sugar_Land__TX_Land_Development_Code.pdf")
        self.assertEqual(r["bucket"], "A")
        self.assertEqual(r["rotated"], "yes")
        self.assertTrue(r["table_pages"])
        self.assertEqual(r["status"], "OK")

    def test_abilene_bucket_a_rotated(self):
        r = self._row("Abilene__TX_Code_of_Ordinances__1_.pdf")
        self.assertEqual(r["bucket"], "A")
        self.assertEqual(r["rotated"], "yes")
        self.assertTrue(r["table_pages"])
        self.assertEqual(r["status"], "OK")

    def test_keene_bucket_c_pointer(self):
        r = self._row("Code_of_Ordinances.pdf")
        self.assertEqual(r["bucket"], "C")
        self.assertEqual(r["pointer_found"], "yes")
        self.assertIn("799", r["pointer_link"])
        self.assertTrue(r["pointer_link"])
        self.assertEqual(r["status"], "ZONING_NOT_IN_PDF")

    def test_meredith_bucket_b(self):
        r = self._row("Code_of_Ordinances_1.pdf")
        self.assertEqual(r["bucket"], "B")
        self.assertEqual(r["format"], "DISTRICT_LISTS")
        self.assertEqual(r["status"], "OK")


if __name__ == "__main__":
    unittest.main()
