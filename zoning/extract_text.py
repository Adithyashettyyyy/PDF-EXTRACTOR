"""S0: pdftotext wrappers (layout + bbox)."""

from __future__ import annotations

import html
import re
import subprocess


def _run_pdftotext(args: list[str]) -> str:
    """Run pdftotext and decode stdout as UTF-8 (Windows defaults to cp1252)."""
    proc = subprocess.run(args, capture_output=True, check=False)
    return proc.stdout.decode("utf-8", errors="replace")


def pdf_pages(pdf: str) -> list[str]:
    txt = _run_pdftotext(["pdftotext", "-layout", pdf, "-"])
    return txt.split("\f")


def page_words(pdf: str, p: int) -> list[tuple[list[float], str]]:
    out = _run_pdftotext(["pdftotext", "-f", str(p), "-l", str(p), "-bbox", pdf, "-"])
    return [
        (list(map(float, a)), html.unescape(t))
        for *a, t in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
            out,
        )
    ]


def page_blocks(pdf: str, p: int) -> list[list[tuple[list[float], str]]]:
    out = _run_pdftotext(["pdftotext", "-f", str(p), "-l", str(p), "-bbox-layout", pdf, "-"])
    blocks = []
    for b in re.findall(r"<block (.*?)</block>", out, re.S):
        ws = [
            (list(map(float, a)), html.unescape(t))
            for *a, t in re.findall(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
                b,
            )
        ]
        if ws:
            blocks.append(ws)
    return blocks
