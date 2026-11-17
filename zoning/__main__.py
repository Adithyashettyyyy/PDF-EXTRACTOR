"""CLI: python -m zoning run|triage ..."""

from __future__ import annotations

import argparse
from pathlib import Path

from zoning.pipeline import run_one
from zoning.triage import run_triage

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zoning", description="Local zoning PDF → Excel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Extract one PDF")
    run_p.add_argument("--pdf", required=True, type=Path)
    run_p.add_argument("--config", type=Path, default=None)
    run_p.add_argument("--auto", action="store_true", help="Build config automatically (bucket A)")
    run_p.add_argument("--out", type=Path, default=ROOT / "output")
    run_p.add_argument("--golden", type=Path, default=None, help="Compare to golden xlsx")

    tri_p = sub.add_parser("triage", help="Classify PDFs into buckets A–E")
    tri_p.add_argument("--dir", required=True, type=Path, help="Folder of PDFs")
    tri_p.add_argument("--out", type=Path, default=ROOT / "output" / "triage.csv")
    tri_p.add_argument("--workers", type=int, default=4)
    tri_p.add_argument("--timeout", type=int, default=300, help="Seconds per PDF")
    tri_p.add_argument("--force", action="store_true", help="Re-triage even if already in CSV")

    args = ap.parse_args(argv)

    if args.cmd == "run":
        if not args.auto and args.config is None:
            print("Provide --config or --auto")
            return 2
        result = run_one(args.pdf, args.config, args.out, args.golden, auto=args.auto)
        if result["status"] == "OK":
            if result.get("golden") and not result["golden"]["ok"] and not args.auto:
                return 1
            return 0
        if result["status"] == "ZONING_NOT_IN_PDF":
            return 0
        return 1

    if args.cmd == "triage":
        if not args.dir.is_dir():
            print(f"Not a directory: {args.dir}")
            return 2
        run_triage(args.dir, args.out, workers=args.workers, timeout=args.timeout, force=args.force)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
