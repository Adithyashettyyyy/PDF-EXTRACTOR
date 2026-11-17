"""Small text helpers used while reading a code PDF."""

from __future__ import annotations

import re

from zoning.phrases import STATE_ABBR


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def title_place(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def state_abbr(name: str) -> str:
    key = name.strip().lower()
    if key in STATE_ABBR:
        return STATE_ABBR[key]
    if re.fullmatch(r"[A-Za-z]{2}", name.strip()):
        return name.strip().upper()
    return name.strip()


def snippet(text: str, needle: str, width: int = 420) -> str:
    low = text.lower()
    at = low.find(needle.lower())
    if at < 0:
        return clean(text)[:width]
    start = max(0, at - 80)
    return clean(text[start : start + width])


def rejoin_hyphens(text: str) -> str:
    """Join a word split at a line ending. Keep a hyphen before a capital."""

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        if right[:1].isupper():
            return f"{left}-{right}"
        return left + right

    return re.sub(r"([A-Za-z]{2,})-\s+([A-Za-z]{2,})", repl, text or "")


def iter_lines(pages: list[str], keep_blank: bool = False):
    for number, text in enumerate(pages, start=1):
        for raw in (text or "").splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if line or keep_blank:
                yield number, line


def page_list(numbers: list[int], limit: int = 40) -> str:
    ordered = list(dict.fromkeys(numbers))
    shown = ", ".join(str(number) for number in ordered[:limit])
    extra = len(ordered) - limit
    if extra > 0:
        return f"{shown} (+{extra} more)"
    return shown


def one_sentence(text: str) -> str:
    text = clean(text)
    match = re.search(r"([A-Z][^.]{12,240}\.)", text)
    if match:
        return match.group(1)
    return text[:240]
