"""Read PDFs from the input folder and write results to the output folder."""

from __future__ import annotations

import argparse
from pathlib import Path

from zoning.pipeline import analyze

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read code PDFs from the input folder and write zoning workbooks to the output folder."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="Optional path to one PDF. If omitted, every PDF in the input folder is read.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=OUTPUT_DIR,
        help="Folder for the workbook and run_log.csv",
    )
    parser.add_argument("--state", default="")
    parser.add_argument("--municipality", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--county", default="")
    args = parser.parse_args()

    if args.pdf is not None:
        if not args.pdf.exists():
            raise SystemExit(f"PDF not found: {args.pdf}")
        pdfs = [args.pdf]
        overrides = {
            "state": args.state,
            "municipality": args.municipality,
            "type": args.type,
            "county": args.county,
        }
    else:
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(path for path in INPUT_DIR.iterdir() if path.suffix.lower() == ".pdf")
        if not pdfs:
            raise SystemExit(f"No PDF in {INPUT_DIR}. Put a code PDF in that folder and run again.")
        overrides = {"state": "", "municipality": "", "type": "", "county": ""}

    worst = 0
    for pdf in pdfs:
        worst = max(worst, analyze(pdf, args.outdir, overrides))
    raise SystemExit(worst)
