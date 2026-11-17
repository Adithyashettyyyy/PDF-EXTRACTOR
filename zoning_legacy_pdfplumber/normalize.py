"""Step 7: merge obvious duplicate use names inside one city."""

from __future__ import annotations

import re

from zoning.model import UseRow
from zoning.textutil import rejoin_hyphens

EXPLICIT = (
    (re.compile(r"private ambulance services?\.?", re.I), "Ambulance Service"),
    (re.compile(r"ambulance services?\.?", re.I), "Ambulance Service"),
    (re.compile(r"dwellings?,?\s*two[\s-]*family(?:\s*/\s*duplex)?\.?", re.I), "Two-Family Dwelling"),
    (re.compile(r"two[\s-]*family\s+dwellings?(?:\s*/\s*duplex)?\.?", re.I), "Two-Family Dwelling"),
    (re.compile(r"dwellings?,?\s*single[\s-]*family\.?", re.I), "Single-Family Dwelling"),
    (re.compile(r"single[\s-]*family\s+dwellings?\.?", re.I), "Single-Family Dwelling"),
)
SKIP_TOKENS = {"a", "the", "of", "and"}


def normalize(rows: list[UseRow]) -> tuple[list[UseRow], list[tuple[str, str]]]:
    merges: list[tuple[str, str]] = []
    for row in rows:
        original = row.use_name
        name = rejoin_hyphens(original).strip(" ;,")
        for pattern, replacement in EXPLICIT:
            if pattern.fullmatch(name):
                name = replacement
                break
        if name != original:
            merges.append((original, name))
            row.use_name = name
    canon: dict[tuple[str, ...], str] = {}
    for row in rows:
        key = _token_key(row.use_name)
        if len(key) < 2:
            continue
        canon.setdefault(key, row.use_name)
    for row in rows:
        key = _token_key(row.use_name)
        chosen = canon.get(key)
        if chosen and chosen != row.use_name:
            merges.append((row.use_name, chosen))
            row.use_name = chosen
    unique = list(dict.fromkeys(merges))
    return rows, unique


def _token_key(name: str) -> tuple[str, ...]:
    text = name.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    tokens = [token for token in text.split() if token not in SKIP_TOKENS]
    return tuple(sorted(tokens))
