"""S6: position parser for GRID / ROTATED_GRID (from baseline)."""

from __future__ import annotations

import re

from zoning.extract_text import page_blocks, page_words


def _axes(rot):
    if rot:
        return (lambda b: (b[1] + b[3]) / 2), (lambda b: (b[0] + b[2]) / 2)
    return (lambda b: (b[0] + b[2]) / 2), (lambda b: (b[1] + b[3]) / 2)


def find_headers(W, columns, min_share=0.8):
    need = max(1, int(len(columns) * min_share)) if len(columns) > 1 else 1
    found = []
    for rot in (False, True):
        U, V = _axes(rot)
        groups = {}
        for bb, t in W:
            c = t.rstrip("*")
            if c in columns:
                groups.setdefault(round(V(bb) / 4), []).append((c, U(bb), V(bb)))
        for _, items in groups.items():
            cols = {}
            for c, u, v in items:
                cols.setdefault(c, (u, v))
            if len(cols) >= need and (len(columns) > 1 or rot == _single_rot(W)):
                hv = sum(v for _, v in cols.values()) / len(cols)
                found.append((rot, hv, {c: u for c, (u, v) in cols.items()}))
    found.sort(key=lambda h: h[1])
    return found


def _single_rot(W):
    words = [bb for bb, t in W if len(t) > 3]
    tall = sum(1 for b in words if (b[3] - b[1]) > (b[2] - b[0]))
    return tall > len(words) / 2


def parse_table(pdf, pages, columns, value_re, cfg):
    VAL = re.compile(value_re)
    row_start = re.compile(cfg.get("row_start_regex", r"^$a"))
    cat_re = re.compile(cfg.get("category_regex", r"^$a"))
    skip_re = re.compile(cfg.get("skip_line_regex", r"^(Supp\.|Table |TABLE |LEGEND|See Section)"))
    drop_tok = re.compile(cfg.get("drop_token_regex", r"^(Supp\.|No\.)$"))
    stop_re = re.compile(cfg.get("stop_regex", r"^\d+\.\s"))
    gap = cfg.get("row_gap", 13)
    rows, cat, issues, stopped = [], None, [], False
    for p in pages:
        if stopped:
            break
        W = page_words(pdf, p)
        heads = find_headers(W, columns)
        if not heads:
            issues.append((p, "no header"))
            continue
        for hi, (rot, hv, hdr) in enumerate(heads):
            U, V = _axes(rot)
            vend = heads[hi + 1][1] - 6 if hi + 1 < len(heads) else 1e9
            ulo, uhi = min(hdr.values()), max(hdr.values())
            band = cfg.get("band_pad", 12)
            words = [(bb, t) for bb, t in W if hv + 4 < V(bb) < vend and not drop_tok.match(t)]
            hi_side = sum(len(t) for bb, t in words if U(bb) > uhi + band and not VAL.match(t))
            lo_side = sum(len(t) for bb, t in words if U(bb) < ulo - band and not VAL.match(t))
            side = cfg.get("name_side") or (1 if hi_side >= lo_side else -1)
            if cfg.get("name_anchor"):
                anc = [U(bb) for bb, t in W if re.match(cfg["name_anchor"], t) and abs(V(bb) - hv) < 8]
                if anc:
                    side = 1 if anc[0] > uhi else -1
            inname = (lambda u: u > uhi + band) if side == 1 else (lambda u: u < ulo - band)
            inside_txt = (lambda u: u < ulo - band) if side == 1 else (lambda u: u > uhi + band)
            order = (lambda w: -U(w[0])) if (rot and side == 1) else (lambda w: U(w[0]))
            nw = sorted([w for w in words if inname(U(w[0]))], key=lambda w: V(w[0]))
            lines = []
            for bb, t in nw:
                if lines and abs(V(bb) - lines[-1]["v"]) < 3:
                    lines[-1]["w"].append((bb, t))
                else:
                    lines.append({"v": V(bb), "w": [(bb, t)]})
            rws = []
            if cfg.get("row_mode") == "blocks":
                lines = []
                for ws in page_blocks(pdf, p):
                    ws = [w for w in ws if hv + 4 < V(w[0]) < vend and not drop_tok.match(w[1])]
                    if not any(inname(U(w[0])) for w in ws) or all(VAL.match(w[1]) for w in ws):
                        continue
                    vs = [V(w[0]) for w in ws]
                    lines.append({"v": min(vs), "v1": max(vs), "w": ws, "block": True})
                lines.sort(key=lambda l: l["v"])
            for ln in lines:
                if not ln.get("block"):
                    ln["w"].sort(key=order)
                txt = " ".join(t for _, t in ln["w"]).strip()
                if not txt or skip_re.match(txt):
                    continue
                if stop_re.match(txt):
                    stopped = True
                    break
                is_cat = bool(cat_re.match(txt))
                new = is_cat or bool(row_start.match(txt))
                if ln.get("block"):
                    rws.append(
                        {"t": txt, "v0": ln["v"], "v1": ln["v1"], "cat": is_cat, "cells": {}, "side": []}
                    )
                    continue
                if (
                    rws
                    and not new
                    and not rws[-1]["cat"]
                    and ln["v"] - rws[-1]["v1"] < (40 if cfg.get("row_start_regex") else gap)
                ):
                    rws[-1]["t"] += " " + txt
                    rws[-1]["v1"] = ln["v"]
                else:
                    rws.append({"t": txt, "v0": ln["v"], "v1": ln["v"], "cat": is_cat, "cells": {}, "side": []})
            real = [r for r in rws if not r["cat"]]

            def owner(v):
                c = [r for r in real if r["v0"] - 8 <= v <= r["v1"] + 8]
                if c:
                    return min(c, key=lambda r: abs(v - r["v0"]))
                return min(real, key=lambda r: min(abs(v - r["v0"]), abs(v - r["v1"]))) if real else None

            for bb, t in words:
                if ulo - band <= U(bb) <= uhi + band and VAL.match(t):
                    r = owner(V(bb))
                    col = min(hdr, key=lambda k: abs(hdr[k] - U(bb)))
                    if r is None or abs(hdr[col] - U(bb)) > cfg.get("col_tol", 14):
                        issues.append((p, t, "unassigned"))
                        continue
                    r["cells"].setdefault(col, []).append((U(bb), t))
                elif inside_txt(U(bb)):
                    r = owner(V(bb))
                    if r:
                        r["side"].append((V(bb), order((bb, t)), t))
            for r in rws:
                if r["cat"]:
                    cat = r["t"]
                    continue
                txt = re.sub(r"(\w)- ([a-z])", r"\1\2", r["t"])
                txt = re.sub(r"(\w)- ([A-Z])", r"\1-\2", txt).replace("/ ", "/")
                cells = {}
                for c, toks in r["cells"].items():
                    toks = [t for _, t in sorted(toks, key=lambda x: x[0], reverse=(side == 1 and rot))]
                    toks.sort(key=lambda t: t.startswith("("))
                    cells[c] = "".join(toks)
                side_txt = " ".join(t for *_, t in sorted(r["side"]))
                rows.append(
                    {"page": p, "category": cat, "use": txt.strip(), "cells": cells, "side_text": side_txt}
                )
            if stopped:
                break
    return rows, issues


def _override_specs(raw) -> list[dict]:
    """Normalize use_overrides entry → list of {values, zones?, page?} dicts.

    Accepted forms:
      ["-", "Not permitted", "route", ""]
      {"values": [...], "zones": [...], "page": 124}
      {"symbol": "-", "permission": "...", "approval_route": "...", "approval_body": "", "zones": [...], "page": 124}
      [ {..spec..}, {..spec..} ]
    """
    if raw is None:
        return []
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        return [{"values": list(raw)}]
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _spec_values(spec: dict) -> list | None:
    if "values" in spec and isinstance(spec["values"], (list, tuple)) and len(spec["values"]) >= 4:
        return list(spec["values"][:4])
    if all(k in spec for k in ("symbol", "permission", "approval_route")):
        return [
            spec["symbol"],
            spec["permission"],
            spec["approval_route"],
            spec.get("approval_body", ""),
        ]
    return None


def resolve_use_override(name: str, zone: str, page: int | None, cfg: dict) -> list | None:
    """Return [sym, perm, route, body] if a matching override applies, else None."""
    entry = (cfg.get("use_overrides") or {}).get(name)
    if entry is None:
        return None
    for spec in _override_specs(entry):
        zones = spec.get("zones")
        if zones is not None and zone not in zones:
            continue
        page_ref = spec.get("page")
        if page_ref is not None and page is not None:
            pages = page_ref if isinstance(page_ref, (list, tuple)) else [page_ref]
            if page not in pages:
                continue
        vals = _spec_values(spec)
        if vals is not None:
            return vals
        # Legacy bare 4-list already handled by _override_specs
    return None


def to_rows(rows, tb, cfg):
    out = []
    smap = cfg["symbols"]
    for r in rows:
        name = re.sub(r"\s+", " ", r["use"]).strip()
        for pat, rep in cfg.get("use_name_fixes", {}).items():
            name = re.sub(pat, rep, name)
        no = ""
        if tb.get("use_number_regex"):
            m = re.match(tb["use_number_regex"], name)
            if m:
                no, name = m.group(1), name[m.end() :].strip()
        if re.match(cfg.get("drop_use_regex", r"^$a"), name):
            continue
        star = name.endswith("*")
        name = name.rstrip("*").strip()
        cat_raw = r["category"] or ""
        cat_map = tb.get("category_map") or cfg.get("category_map") or {}
        by_letter = tb.get("category_map_by_letter") or cfg.get("category_map_by_letter")
        cat = cat_map.get(cat_raw[:1] if by_letter else cat_raw, cat_raw)
        if cfg.get("category_override", {}).get(name):
            cat = cfg["category_override"][name]
        std = ""
        if tb.get("standards_regex"):
            std = "; ".join(dict.fromkeys(re.findall(tb["standards_regex"], r["side_text"])))
        for col in tb["columns"]:
            for zone in cfg.get("column_to_zones", {}).get(col, [col]):
                s = r["cells"].get(col, "")
                ov = resolve_use_override(name, zone, r.get("page"), cfg)
                if ov is not None:
                    sym, perm, route, body = ov
                elif s == "":
                    sym, perm, route, body = cfg["blank"]
                elif s in smap:
                    sym = s + ("*" if star and s in ("P", "C") else "")
                    perm, route, body = smap[s]
                    if perm == "Permitted" and (star or std):
                        perm = "Permitted with conditions"
                        route = "Allowed by right; " + (
                            f"standards apply ({std})"
                            if std
                            else cfg.get("star_text", "use-specific conditions apply")
                        )
                    elif std:
                        route += f"; standards apply ({std})"
                    elif star:
                        route += "; " + cfg.get("star_text", "use-specific conditions apply")
                else:
                    sym, perm, route, body = s, "Unclear", "Unrecognized symbol", ""
                if sym not in ("-", "(blank)") and col in cfg.get("extra_route_columns", {}):
                    route += "; " + cfg["extra_route_columns"][col]
                out.append(
                    dict(
                        zone_code=zone,
                        use_category=cat,
                        use_name=name,
                        symbol=sym,
                        permission=perm,
                        approval_route=route,
                        approval_body=body,
                        source_section=tb["section"] + (f", use {r['category'][:1]}{no}" if no else ""),
                    )
                )
    return out
