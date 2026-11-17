"""Run one PDF through gate → table parse → Excel (M1 behaviour)."""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from zoning.compare import compare_with_golden, format_result
from zoning.config import load_config
from zoning.extract_text import pdf_pages
from zoning.gate import gate, norm_url
from zoning.parse_table import parse_table, to_rows
from zoning.validate import validate
from zoning.write_outputs import build


def run_one(
    pdf: str | Path,
    config: str | Path | None = None,
    outdir: str | Path = "output",
    golden: str | Path | None = None,
    auto: bool = False,
) -> dict:
    pdf = Path(pdf)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    log: list = []
    status = "OK"
    workbook = None
    generated = None
    unresolved: list[str] = []

    pages = pdf_pages(str(pdf))
    if pages and sum(len(p) for p in pages) / max(1, len(pages)) < 100:
        log.append(("text_layer", "FAIL", "SCANNED_PDF: run OCR first", "", "", ""))
        status = "SCANNED_PDF"

    res, ptr = gate(pages)
    for n, r, m, hits in res:
        log.append((n, r, m, "", "", ",".join(map(str, hits))))
    ok = all(r == "PASS" for _, r, _, _ in res) and status != "SCANNED_PDF"

    if auto and ok:
        from zoning.autoconfig import build_autoconfig

        cfg, generated, unresolved = build_autoconfig(pdf)
        log.append(
            (
                "autoconfig",
                "PASS" if not unresolved else "WARN",
                f"Wrote {generated}" + (f"; unresolved={len(unresolved)}" if unresolved else ""),
                "",
                "",
                "",
            )
        )
        print(f"Auto-config {generated}")
    else:
        cfg = load_config(config)

    meta = {k: cfg.get(k, "") for k in ("state", "municipality", "type", "county")}

    # External pointer with no use tables in config → zoning not in this PDF (T4 Keene)
    if ptr and not cfg.get("tables"):
        for pg, txt in ptr[:2]:
            m = re.search(r"https?://[^\s]+(?:\s[a-z][\w-]*)?", txt)
            url = m.group(0) if m else ""
            log.append(
                (
                    "external_pointer",
                    "FAIL",
                    "ZONING_NOT_IN_PDF: " + txt[:200],
                    url,
                    norm_url(url) if url else "",
                    str(pg),
                )
            )
        ok = False
        status = "ZONING_NOT_IN_PDF"

    uses: list[dict] = []
    if ok and cfg.get("tables"):
        for tb in cfg["tables"]:
            rows, issues = parse_table(
                str(pdf),
                range(tb["pages"][0], tb["pages"][1] + 1),
                tb["columns"],
                tb["value_regex"],
                {**cfg.get("parser", {}), **tb.get("parser", {})},
            )
            for i in issues[:20]:
                log.append(("parser_issue", "WARN", str(i), "", "", ""))
            uses += to_rows(rows, tb, cfg)

    if not ok:
        print(f"Gate check failed ({status}); no Excel written. See run_log.csv")
    else:
        muni = (meta.get("municipality") or "Unknown").replace(" ", "")
        typ = (meta.get("type") or "Place").split()[0]
        state = meta.get("state") or "XX"
        name = f"{state}_{muni}_{typ}_Zoning.xlsx"
        workbook = outdir / name
        z, u = build(
            str(workbook),
            meta,
            cfg.get("zones", []),
            uses,
            cfg.get("legend", []),
            cfg.get("source_document", ""),
        )
        validate(cfg, uses, log)
        print(f"Wrote {name}: {z} zones, {u} rows")

    log_path = outdir / "run_log.csv"
    _append_log(log_path, pdf.name, meta, log)

    result = {
        "status": status if not ok else "OK",
        "workbook": str(workbook) if workbook else None,
        "uses": len(uses),
        "zones": len(cfg.get("zones", [])),
        "log": log,
        "golden": None,
        "config": str(generated) if generated else (str(config) if config else None),
        "unresolved": unresolved,
    }
    if golden and workbook:
        cmp = compare_with_golden(workbook, golden)
        result["golden"] = cmp
        print(format_result(cmp))
        if not cmp["ok"] and not auto:
            result["status"] = "GOLDEN_MISMATCH"
    return result


def _append_log(log_path: Path, file_name: str, meta: dict, log: list) -> None:
    exists = log_path.exists() and log_path.stat().st_size > 0
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(
                [
                    "file",
                    "state",
                    "municipality",
                    "type",
                    "county",
                    "check",
                    "result",
                    "message",
                    "link_raw",
                    "link_guess",
                    "pages",
                ]
            )
        for c, r, m, l1, l2, pg in log:
            w.writerow(
                [
                    file_name,
                    meta.get("state", ""),
                    meta.get("municipality", ""),
                    meta.get("type", ""),
                    meta.get("county", ""),
                    c,
                    r,
                    m,
                    l1,
                    l2,
                    pg,
                ]
            )
