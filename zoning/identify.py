"""S1: identify municipality / publication / supplement / current-through."""

from __future__ import annotations

import re

from zoning.phrases_triage import STATE_NAMES

PLACE_OF = re.compile(
    r"(City|Town|Village|Township|Borough)\s+of\s+([A-Za-z][A-Za-z0-9 .'\-]{1,60})",
    re.I,
)
CITY_STATE = re.compile(
    r"\b([A-Z][A-Za-z .'\-]{1,40}),\s*((?:New|North|South|West|Rhode)\s+[A-Z][a-z]+|[A-Z][a-z]+)\b"
)
SUPPLEMENT = re.compile(r"Supplement\s+No\.?\s*(\d+[^\n]{0,40})", re.I)
THROUGH = re.compile(
    r"through\s+(?:Ordinance\s+No\.?\s*)?([^\n.]{5,90}?)(?:\.|\n|$)",
    re.I,
)
PUB_PATTERNS = [
    (re.compile(r"LAND DEVELOPMENT CODE", re.I), "Land Development Code"),
    (re.compile(r"UNIFIED DEVELOPMENT(?:\s+CODE)?", re.I), "Unified Development Code"),
    (re.compile(r"DEVELOPMENT CODE", re.I), "Development Code"),
    (re.compile(r"ZONING ORDINANCE", re.I), "Zoning Ordinance"),
    (re.compile(r"CODE OF ORDINANCES", re.I), "Code of Ordinances"),
    (re.compile(r"MUNICIPAL CODE", re.I), "Municipal Code"),
]


def _clean_place(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,.")
    for state_name in STATE_NAMES:
        if name.upper().endswith(", " + state_name) or name.upper().endswith(" " + state_name):
            name = re.sub(r"[,\s]+" + re.escape(state_name) + r"$", "", name, flags=re.I).strip(" ,.")
    if name.isupper() and len(name) > 2:
        name = name.title()
    return name


def identify(pages: list[str]) -> dict:
    head = "\n".join(pages[:30])
    state, municipality, typ, county = "", "", "", ""

    m = PLACE_OF.search(head)
    if m:
        typ = m.group(1).title()
        municipality = _clean_place(m.group(2))

    cs = CITY_STATE.search(head[:2000])
    if cs:
        if not municipality:
            municipality = _clean_place(cs.group(1))
        state_name = cs.group(2).upper()
        state = STATE_NAMES.get(state_name, state)

    if not state:
        upper = head[:2000].upper()
        for name, abbr in STATE_NAMES.items():
            if name in upper:
                state = abbr
                break

    supplement = ""
    sm = SUPPLEMENT.search(head)
    if sm:
        supplement = "Supplement No. " + re.sub(r"\s+", " ", sm.group(1)).strip()

    current_through = ""
    tm = THROUGH.search(head)
    if tm:
        current_through = re.sub(r"\s+", " ", tm.group(1)).strip(" ,;")

    publication = ""
    for rx, label in PUB_PATTERNS:
        if rx.search(head[:2500]):
            publication = label
            break

    return {
        "state": state,
        "municipality": municipality,
        "type": typ,
        "county": county,
        "publication": publication,
        "supplement": supplement,
        "current_through": current_through,
    }
