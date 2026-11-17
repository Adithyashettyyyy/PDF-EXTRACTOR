"""M2: triage a folder of PDFs → triage.csv (buckets A–E)."""

from __future__ import annotations

import csv
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from pathlib import Path

from zoning.detect import detect_format
from zoning.extract_text import pdf_pages
from zoning.identify import identify
from zoning.locate import locate

TRIAGE_HEADERS = [
    "file",
    "state",
    "municipality",
    "type",
    "county",
    "pages",
    "text_layer",
    "publication",
    "supplement",
    "current_through",
    "zoning_found",
    "pointer_found",
    "pointer_link",
    "format",
    "table_pages",
    "rotated",
    "bucket",
    "status",
]


def triage_one(pdf: str | Path) -> dict:
    """Analyze one PDF and return a triage row dict."""
    pdf = Path(pdf)
    row = {h: "" for h in TRIAGE_HEADERS}
    row["file"] = pdf.name
    try:
        pages = pdf_pages(str(pdf))
    except Exception as exc:
        row["status"] = "FAILED"
        row["bucket"] = "E"
        row["text_layer"] = "no"
        row["pages"] = "0"
        row["supplement"] = str(exc)[:80]
        return row

    row["pages"] = str(len(pages))
    info = identify(pages)
    for k in ("state", "municipality", "type", "county", "publication", "supplement", "current_through"):
        row[k] = info.get(k, "")

    loc = locate(pages)
    row["zoning_found"] = loc["zoning_found"]
    row["pointer_found"] = loc["pointer_found"]
    # pointer_link includes page for tests: store link; page is recoverable from locate
    if loc["pointer_found"] == "yes":
        row["pointer_link"] = loc["pointer_link"]
        if loc["pointer_page"]:
            # keep page in pointer_link field as "url | p.N" only if needed; prefer separate via format
            row["pointer_link"] = f"{loc['pointer_link']} (p.{loc['pointer_page']})"

    det = detect_format(str(pdf), pages, loc)
    row["text_layer"] = det["text_layer"]
    row["format"] = det["format"]
    row["table_pages"] = det["table_pages"]
    row["rotated"] = det["rotated"]
    row["bucket"] = det["bucket"]
    row["status"] = det["status"]
    return row


def _worker(pdf: str) -> dict:
    return triage_one(pdf)


def _read_existing(path: Path) -> dict[str, dict]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("file"):
                out[row["file"]] = row
    return out


def _write_all(path: Path, rows_by_file: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRIAGE_HEADERS)
        w.writeheader()
        for name in sorted(rows_by_file):
            row = {h: rows_by_file[name].get(h, "") for h in TRIAGE_HEADERS}
            w.writerow(row)


def _progress(done: int, total: int, label: str = "") -> None:
    width = 28
    filled = int(width * done / total) if total else width
    bar = "#" * filled + "-" * (width - filled)
    msg = f"\r[{bar}] {done}/{total} {label[:40]}"
    print(msg, end="", flush=True)
    if done >= total:
        print()


def run_triage(
    pdf_dir: str | Path,
    out_csv: str | Path,
    workers: int = 4,
    timeout: int = 300,
    force: bool = False,
) -> dict:
    """Triage every PDF in pdf_dir. Returns summary dict with counts and rows."""
    pdf_dir = Path(pdf_dir)
    out_csv = Path(out_csv)
    pdfs = sorted(p for p in pdf_dir.glob("*.pdf") if p.is_file())
    existing = {} if force else _read_existing(out_csv)
    todo = [p for p in pdfs if force or p.name not in existing]

    rows_by_file = dict(existing)
    print(f"Triage {len(pdfs)} PDFs ({len(todo)} to process, {len(pdfs) - len(todo)} skipped)")

    if todo:
        workers = max(1, min(workers, len(todo)))
        done = 0
        # ProcessPool on Windows needs guard; caller should be under __main__
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker, str(p)): p for p in todo}
            for fut in as_completed(futures):
                pdf = futures[fut]
                done += 1
                try:
                    row = fut.result(timeout=timeout)
                except FuturesTimeout:
                    row = {h: "" for h in TRIAGE_HEADERS}
                    row["file"] = pdf.name
                    row["status"] = "FAILED"
                    row["bucket"] = "E"
                    row["supplement"] = f"timeout after {timeout}s"
                except Exception as exc:
                    row = {h: "" for h in TRIAGE_HEADERS}
                    row["file"] = pdf.name
                    row["status"] = "FAILED"
                    row["bucket"] = "E"
                    row["supplement"] = str(exc)[:80]
                rows_by_file[row["file"]] = row
                _progress(done, len(todo), pdf.name)
                _write_all(out_csv, rows_by_file)  # resumable checkpoint

    # ensure all pdfs present even if skipped
    for p in pdfs:
        if p.name not in rows_by_file:
            rows_by_file[p.name] = triage_one(p)
    _write_all(out_csv, rows_by_file)

    counts: dict[str, int] = {}
    for row in rows_by_file.values():
        b = row.get("bucket") or "?"
        counts[b] = counts.get(b, 0) + 1

    print("Bucket summary:")
    for b in ("A", "B", "C", "D", "E"):
        if b in counts:
            print(f"  {b}: {counts[b]}")
    for b, n in sorted(counts.items()):
        if b not in {"A", "B", "C", "D", "E"}:
            print(f"  {b}: {n}")

    return {"rows": rows_by_file, "counts": counts, "out": str(out_csv)}
