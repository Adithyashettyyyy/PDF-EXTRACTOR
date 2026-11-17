"""Optional Claude pass for district lists, legends, and zones.

Used only when ANTHROPIC_API_KEY is set. Grid cells stay with the positional reader.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

from zoning.model import LegendEntry, UnlistedRule, UseRow, Zone
from zoning.reader import PdfDocument
from zoning.schema import PERMISSIONS
from zoning.zones import group_for, type_for

PROMPT = """You are extracting zoning rules from a US municipal code. Read ONLY the text provided.
Return ONLY valid JSON matching the schema below. No commentary.

Municipality: {municipality}, {state} ({type}, {county} County)
Source: {source_document}
Pages provided: {page_numbers}

TASKS
1. ZONES: list every zoning district. Copy zone_code exactly as printed. Give zone_name,
   zone_group, zone_type (Base district / Overlay district / Special district / Combining district),
   a one-sentence plain-language zone_meaning based on the district's purpose or intent text,
   and source_section. If the code gives only names and no codes, set "codes_printed": false.
2. LEGEND: every symbol used for uses (e.g. P, C, S, SE, CUP, TP, -, blank, *, (N), P1)
   with its meaning as written, who approves it, and the standard permission:
   Permitted | Permitted with conditions | Conditional | Temporary | Not permitted | Unclear.
3. UNLISTED_RULE: quote the sentence on uses not listed and say whether missing uses are
   "Not permitted" or "Unclear".
4. USES: for per-district lists, list every use per district with the symbol category
   (permitted / special exception / conditional / etc.), any condition in one short
   plain sentence, and the section and page.
5. EXTERNAL_POINTER: if the text says zoning is published elsewhere, give the quote,
   the page, and any URL exactly as printed.

RULES
- Never invent a zone, use or permission. If unsure, use "Unclear" and explain in "note".
- Copy codes and use names exactly; only re-join words broken by line-end hyphens.
- Blank cells are "Not permitted" ONLY if the legend says so.
- A symbol's meaning comes from THIS document's legend, never from other cities.
- Every item must carry section and page.

SCHEMA
{{
  "document": {{"publication": "", "supplement": "", "current_through": ""}},
  "external_pointer": {{"found": false, "quote": "", "page": null, "url_raw": ""}},
  "codes_printed": true,
  "zones": [{{"zone_code": "", "zone_name": "", "zone_group": "", "zone_type": "",
             "zone_meaning": "", "source_section": "", "page": null}}],
  "legend": [{{"symbol": "", "meaning": "", "approved_by": "", "permission": ""}}],
  "unlisted_rule": {{"quote": "", "page": null, "missing_uses_are": "Not permitted"}},
  "uses": [{{"zone_code": "", "use_category": "", "use_name": "", "symbol": "",
            "condition": "", "source_section": "", "page": null, "note": ""}}]
}}
"""


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def ask(doc: PdfDocument, place: dict, source: str, page_numbers: list[int]) -> dict | None:
    key = api_key()
    if not key or not page_numbers:
        return None
    chunks = []
    for number in page_numbers[:30]:
        if 1 <= number <= len(doc.pages):
            chunks.append(f"\n\n--- PAGE {number} ---\n{doc.pages[number - 1]}")
    provided = "".join(chunks)[:120000]
    prompt = PROMPT.format(
        municipality=place.get("municipality") or "Unknown",
        state=place.get("state") or "Unknown",
        type=place.get("type") or "Place",
        county=place.get("county") or "Unknown",
        source_document=source or "the attached pages",
        page_numbers=", ".join(str(number) for number in page_numbers[:30]),
    )
    prompt = f"{prompt}\n\nTEXT\n{provided}"
    body = json.dumps(
        {
            "model": os.environ.get("ZONING_CLAUDE_MODEL", "claude-sonnet-4-5"),
            "max_tokens": 16000,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
    return _json_object(text)


def merge(zones, legend, rule, rows, remote, kind):
    if not remote:
        return zones, legend, rule, rows, "Claude returned nothing that could be read."
    if len(zones) < 2 and remote.get("zones"):
        zones = _zones(remote["zones"]) or zones
    if len(legend) < 2 and remote.get("legend"):
        legend = _legend(remote["legend"]) or legend
    remote_rule = remote.get("unlisted_rule") or {}
    if remote_rule.get("quote") and not rule.quote:
        missing = remote_rule.get("missing_uses_are") or "Unclear"
        if missing not in ("Not permitted", "Unclear"):
            missing = "Unclear"
        rule = UnlistedRule(remote_rule.get("quote", ""), remote_rule.get("page"), missing, rule.blank_is_prohibited)
    remote_rows = _uses(remote.get("uses") or [])
    if remote_rows and (kind in {"lists", "none", "mixed"} or len(rows) < 5):
        if len(rows) < 5:
            rows = remote_rows
        else:
            covered = {row.zone_code for row in rows}
            rows = rows + [row for row in remote_rows if row.zone_code not in covered]
    return zones, legend, rule, rows, f"Claude returned {len(remote.get('zones') or [])} zones and {len(remote.get('uses') or [])} uses."


def _zones(items: list[dict]) -> list[Zone]:
    zones = []
    for item in items:
        code = str(item.get("zone_code") or "").strip()
        name = str(item.get("zone_name") or "").strip()
        if not code or not name:
            continue
        zone_type = item.get("zone_type") or type_for(name, code)
        if zone_type not in ("Base district", "Overlay district", "Special district", "Combining district"):
            zone_type = type_for(name, code)
        zones.append(
            Zone(
                zone_code=code,
                zone_name=name,
                zone_group=item.get("zone_group") or group_for(name),
                zone_type=zone_type,
                zone_meaning=str(item.get("zone_meaning") or "")[:240],
                source_section=str(item.get("source_section") or ""),
                page=item.get("page") if isinstance(item.get("page"), int) else None,
            )
        )
    return zones


def _legend(items: list[dict]) -> list[LegendEntry]:
    entries = []
    for item in items:
        symbol = str(item.get("symbol") or "").strip()
        meaning = str(item.get("meaning") or "").strip()
        if not symbol or not meaning:
            continue
        permission = item.get("permission") or "Unclear"
        if permission not in PERMISSIONS:
            permission = "Unclear"
        entries.append(LegendEntry(symbol, permission, meaning, str(item.get("approved_by") or "")))
    return entries


def _uses(items: list[dict]) -> list[UseRow]:
    rows = []
    for item in items:
        name = str(item.get("use_name") or "").strip()
        code = str(item.get("zone_code") or "").strip()
        if not name or not code:
            continue
        rows.append(
            UseRow(
                zone_code=code,
                use_category=str(item.get("use_category") or ""),
                use_name=name,
                symbol=str(item.get("symbol") or ""),
                permission="",
                approval_route=str(item.get("condition") or item.get("note") or "")[:180],
                source_section=str(item.get("source_section") or ""),
                page=item.get("page") if isinstance(item.get("page"), int) else None,
            )
        )
    return rows


def _json_object(text: str) -> dict | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
