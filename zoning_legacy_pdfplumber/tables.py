"""Step 6A: read a use grid from ruled cells or from word positions."""

from __future__ import annotations

import re

from zoning.model import ParseMeta, UseRow, Zone
from zoning.reader import PdfDocument
from zoning.textutil import rejoin_hyphens

ZONE_TOKEN = re.compile(r"^(?:[A-Z]{1,4}(?:-[A-Z0-9]{1,4})+|[A-Z]{1,3}\d{1,2}[A-Z]?)$")
SYMBOL_TOKEN = re.compile(
    r"^(?:[A-Z]{1,3}\*?|[A-Z]/[A-Z]{1,3}|[A-Z]\([A-Za-z0-9]{1,4}\)|[—–\-−]|\([A-Za-z0-9]{1,3}\))$"
)
FOOTNOTE = re.compile(r"^\d+\.\s")
LEGEND_STOP = re.compile(r"^[A-Z*—–\-−]\s*=\s+\S")
USE_NOUN = re.compile(r"dwelling|store|shop|office|station|facility|service|parking|sign", re.I)


def parse_tables(doc: PdfDocument, zones: list[Zone], pages: list[int]) -> tuple[list[UseRow], ParseMeta]:
    known = {zone.zone_code for zone in zones}
    meta = ParseMeta()
    rows: list[UseRow] = []
    chosen = _candidate_pages(doc, pages, known)
    category = ""
    previous = 0
    for number in chosen:
        if previous and number - previous > 1:
            category = ""
        ruled, ruled_meta, category = _ruled_page(doc, number, known, category)
        word_rows, rotated, word_meta, word_category = _word_page(doc, number, known, category)
        if len(ruled) >= 3 and len({row.zone_code for row in ruled}) >= 2 and len(ruled) >= len(word_rows):
            picked, picked_meta, category = ruled, ruled_meta, category
            page_rotated = False
        elif word_rows:
            picked, picked_meta, category = word_rows, word_meta, word_category
            page_rotated = rotated
        else:
            picked, picked_meta, category = _text_page(doc.pages[number - 1], number, known, category)
            page_rotated = False
        if picked:
            rows.extend(picked)
            meta.pages.append(number)
            meta.rotated = meta.rotated or page_rotated
            meta.columns.update(picked_meta.columns)
            meta.discovered.extend(picked_meta.discovered)
        previous = number
    return rows, meta


def _candidate_pages(doc: PdfDocument, use_pages: list[int], known: set[str]) -> list[int]:
    pool = use_pages or list(range(1, doc.page_count + 1))
    scored = []
    for number in pool:
        text = doc.pages[number - 1]
        score = sum(1 for code in list(known)[:50] if code in text)
        if score or number in use_pages:
            scored.append((score, number))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return sorted(number for _, number in scored[:40])


def _ruled_page(doc, number, known, category):
    meta = ParseMeta()
    rows: list[UseRow] = []
    for table in doc.ruled_tables(number):
        parsed, meta_part, category = _one_ruled_table(table, number, set(known), category)
        rows.extend(parsed)
        meta.columns.update(meta_part.columns)
        meta.discovered.extend(meta_part.discovered)
        known.update(code for code, _, _ in meta_part.discovered)
    return rows, meta, category


def _one_ruled_table(table, number, known, category):
    meta = ParseMeta()
    rows: list[UseRow] = []
    if not table or len(table) < 2:
        return rows, meta, category
    header_at = _header_index(table, known)
    if header_at is None:
        return rows, meta, category
    header = [_cell(value) for value in table[header_at]]
    columns, use_at, notes_at = _columns(header, known, meta, number)
    if len(columns) < 2:
        return rows, meta, category
    last_name = ""
    for raw in table[header_at + 1 :]:
        cells = [_cell(value) for value in raw]
        if _repeats_header(cells, columns):
            continue
        name = cells[use_at] if use_at < len(cells) else ""
        notes = cells[notes_at] if notes_at is not None and notes_at < len(cells) else ""
        if not name:
            name = last_name
        name = rejoin_hyphens(name)
        if not name or FOOTNOTE.match(name) or LEGEND_STOP.match(name):
            if rows and FOOTNOTE.match(name or ""):
                break
            continue
        symbols = {}
        for index, codes in columns.items():
            if index >= len(cells):
                continue
            symbol = _as_symbol(cells[index], known)
            if symbol:
                for code in codes:
                    symbols[code] = symbol
        if not symbols and _is_category(name):
            category = name
            continue
        if not symbols:
            continue
        last_name = name
        route = _note_route(notes)
        for code, symbol in symbols.items():
            rows.append(
                UseRow(
                    zone_code=code,
                    use_category=category,
                    use_name=name,
                    symbol=symbol,
                    approval_route=route,
                    source_section=f"p. {number}",
                    page=number,
                    column_header=meta.columns.get(code, code),
                )
            )
    return rows, meta, category


def _word_page(doc, number, known, category):
    words = [_usable(word) for word in doc.words(number)]
    words = [word for word in words if word]
    meta = ParseMeta()
    if len(words) < 8:
        return [], False, meta, category
    code_words = [word for word in words if _is_zone_word(word["text"], known)]
    horizontal = _largest_band(code_words, "top", 3)
    vertical = _largest_band(code_words, "x0", 4)
    if len(vertical) >= 3 and len(vertical) > len(horizontal):
        rows, category = _parse_horizontal(_swap(words), _swap(vertical), number, known, meta, category)
        return rows, True, meta, category
    if len(horizontal) < 2:
        return [], False, meta, category
    rows, category = _parse_horizontal(words, horizontal, number, known, meta, category)
    return rows, False, meta, category


def _parse_horizontal(words, header, number, known, meta, category):
    rows: list[UseRow] = []
    centers = _zone_centers(header, known, meta, number)
    if len(centers) < 2:
        return rows, category
    header_top = min(word["top"] for word in header)
    side = _use_side(words, header_top, centers)
    boundary = min(center for _, center, _ in centers) - 12
    if side == "after":
        boundary = max(center for _, center, _ in centers) + 12
    body = [word for word in words if word["top"] > header_top + 4]
    lines = _group(body, "top", 3.5)
    last_name = ""
    for index, line in enumerate(lines):
        codes_here = [word for word in line if _is_zone_word(word["text"], known)]
        if len(codes_here) >= 2:
            centers = _zone_centers(codes_here, known, meta, number)
            continue
        use_words, sym_words = _split_line(line, boundary, side, known)
        name = rejoin_hyphens(_join(use_words))
        if not name:
            name = last_name
        if not name:
            continue
        if "not listed" in name.lower() or LEGEND_STOP.match(name):
            break
        if rows and FOOTNOTE.match(name):
            break
        assigned = _assign(sym_words, centers)
        following = False
        if index + 1 < len(lines):
            nxt_use, nxt_sym = _split_line(lines[index + 1], boundary, side, known)
            following = bool(nxt_sym) or bool(_join(nxt_use))
        if not assigned and _is_category(name, following):
            category = name
            continue
        if not assigned and not _is_category(name, False):
            continue
        if not assigned:
            continue
        last_name = name
        for code, symbol, header_name in assigned:
            rows.append(
                UseRow(
                    zone_code=code,
                    use_category=category,
                    use_name=name,
                    symbol=symbol,
                    source_section=f"p. {number}",
                    page=number,
                    column_header=header_name,
                )
            )
    return rows, category


def _zone_centers(header, known, meta, number):
    centers = []
    for word in header:
        token = word["text"]
        if not _is_zone_word(token, known):
            continue
        center = (float(word["x0"]) + float(word["x1"])) / 2
        for code, column in _expand(token, known):
            centers.append((code, center, column))
            meta.columns[code] = column
            if code not in known:
                meta.discovered.append((code, number, column))
                known.add(code)
    return centers


def _expand(token: str, known: set[str]) -> list[tuple[str, str]]:
    if token in known or not known:
        return [(token, token)]
    children = [code for code in known if code.startswith(token + "-")]
    if len(children) >= 2:
        return [(code, token) for code in children]
    return [(token, token)]


def _split_line(line, boundary, side, known):
    use_words = []
    sym_words = []
    for word in line:
        center = (float(word["x0"]) + float(word["x1"])) / 2
        on_use_side = center < boundary if side == "before" else center > boundary
        if on_use_side and not _as_symbol(word["text"], known):
            use_words.append(word)
        elif _as_symbol(word["text"], known) and not _is_zone_word(word["text"], known):
            sym_words.append(word)
    return use_words, sym_words


def _assign(sym_words, centers):
    found = []
    for word in sym_words:
        symbol = word["text"]
        center = (float(word["x0"]) + float(word["x1"])) / 2
        nearest = min(centers, key=lambda item: abs(item[1] - center))
        distance = abs(nearest[1] - center)
        limit = _limit(nearest[1], [item[1] for item in centers])
        if distance <= limit:
            found.append((nearest[0], symbol, nearest[2]))
    return found


def _limit(center: float, centers: list[float]) -> float:
    ordered = sorted(set(centers))
    if center not in ordered:
        center = min(ordered, key=lambda item: abs(item - center))
    index = ordered.index(center)
    gaps = []
    if index > 0:
        gaps.append((ordered[index] - ordered[index - 1]) / 2)
    if index + 1 < len(ordered):
        gaps.append((ordered[index + 1] - ordered[index]) / 2)
    if not gaps:
        return 14
    return max(8, min(20, min(gaps) + 1))


def _use_side(words, header_top, centers) -> str:
    band = [word for word in words if abs(word["top"] - header_top) <= 4]
    for word in band:
        if word["text"].lower() in {"use", "uses", "land"}:
            center = (float(word["x0"]) + float(word["x1"])) / 2
            zone_left = min(item[1] for item in centers)
            return "before" if center < zone_left else "after"
    return "before"


def _header_index(table, known) -> int | None:
    best_at = None
    best = 0
    for index, row in enumerate(table[:10]):
        count = 0
        for value in row:
            count += len(_codes_in_text(_cell(value), known))
        if count > best:
            best = count
            best_at = index
    if best >= 2:
        return best_at
    return None


def _columns(header, known, meta, number):
    columns = {}
    use_at = None
    notes_at = None
    for index, cell in enumerate(header):
        codes = _codes_in_text(cell, known)
        if codes:
            flat = []
            for token in codes:
                for code, column in _expand(token, known):
                    flat.append(code)
                    meta.columns[code] = column
                    if code not in known:
                        meta.discovered.append((code, number, column))
                        known.add(code)
            columns[index] = flat
            continue
        low = cell.lower()
        if "note" in low or low in {"parking", "definition"}:
            notes_at = index
        elif use_at is None and ("use" in low or low in {"principal", "land use"}):
            use_at = index
    if use_at is None:
        for index in range(len(header)):
            if index not in columns:
                use_at = index
                break
    if use_at is None:
        use_at = 0
    return columns, use_at, notes_at


def _codes_in_text(text: str, known: set[str]) -> list[str]:
    tokens = re.findall(r"[A-Z]{1,4}(?:-[A-Z0-9]{1,4})+|[A-Z]{1,3}\d{1,2}[A-Z]?", text or "")
    if known:
        preferred = [token for token in tokens if token in known or any(code.startswith(token + "-") for code in known)]
        if preferred:
            return preferred
    return [token for token in tokens if _is_zone_word(token, known)]


def _repeats_header(cells, columns) -> bool:
    hits = 0
    for index in columns:
        if index < len(cells) and cells[index] and _is_zone_word(cells[index].split()[0], set()):
            hits += 1
    return hits >= 2


def _cell(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _as_symbol(text: str, known: set[str]) -> str:
    token = (text or "").strip()
    if not token or len(token) > 12 or token in known or ZONE_TOKEN.match(token):
        return ""
    if SYMBOL_TOKEN.match(token):
        return token
    return ""


def _is_zone_word(text: str, known: set[str]) -> bool:
    if text in known:
        return True
    return bool(ZONE_TOKEN.match(text or ""))


def _is_category(name: str, following: bool = False) -> bool:
    low = name.lower().strip()
    if low.endswith(" uses") or low.endswith(" use types"):
        return True
    if following and len(name.split()) <= 4 and not USE_NOUN.search(low):
        words = name.split()
        if words and all(word[:1].isupper() for word in words if word[:1].isalpha()):
            return True
    return False


def _note_route(notes: str) -> str:
    notes = notes.strip()
    if not notes:
        return ""
    if re.fullmatch(r"[0-9]{1,3}(?:\s*,\s*[0-9]{1,3})*", notes):
        return f"supplemental regulations apply (note {notes})"
    return notes[:160]


def _join(words: list[dict]) -> str:
    parts: list[str] = []
    for word in sorted(words, key=lambda item: item["x0"]):
        token = word["text"]
        if parts and parts[-1].endswith("-"):
            if token[:1].islower():
                parts[-1] = parts[-1][:-1] + token
            else:
                parts[-1] = parts[-1] + token
        else:
            parts.append(token)
    return " ".join(parts).strip()


def _group(words: list[dict], key: str, tol: float) -> list[list[dict]]:
    ordered = sorted(words, key=lambda word: (word[key], word["x0"]))
    groups: list[list[dict]] = []
    for word in ordered:
        if groups and abs(float(word[key]) - float(groups[-1][0][key])) <= tol:
            groups[-1].append(word)
        else:
            groups.append([word])
    for group in groups:
        group.sort(key=lambda word: word["x0"])
    return groups


def _largest_band(words: list[dict], key: str, tol: float) -> list[dict]:
    if not words:
        return []
    return max(_group(words, key, tol), key=len)


def _text_page(text: str, number: int, known: set[str], category: str):
    """Last resort when a line still has one symbol per zone. Blank cells are not guessed."""
    meta = ParseMeta()
    rows: list[UseRow] = []
    lines = [re.sub(r"\s+", " ", raw).strip() for raw in (text or "").splitlines()]
    header_at = None
    header_codes: list[str] = []
    for index, line in enumerate(lines):
        codes = [token for token in line.split() if _is_zone_word(token, known)]
        if len(codes) >= 2:
            header_at = index
            header_codes = []
            for token in codes:
                for code, column in _expand(token, known):
                    header_codes.append(code)
                    meta.columns[code] = column
                    if code not in known:
                        meta.discovered.append((code, number, column))
                        known.add(code)
            break
    if header_at is None:
        return rows, meta, category
    for line in lines[header_at + 1 :]:
        if not line or "not listed" in line.lower() or LEGEND_STOP.match(line):
            break
        tokens = line.split()
        symbols: list[str] = []
        while tokens and _as_symbol(tokens[-1], known):
            symbols.append(tokens.pop())
        symbols.reverse()
        name = rejoin_hyphens(" ".join(tokens)).strip()
        if not name:
            continue
        if not symbols and _is_category(name):
            category = name
            continue
        if len(symbols) != len(header_codes):
            continue
        for code, symbol in zip(header_codes, symbols):
            rows.append(
                UseRow(
                    zone_code=code,
                    use_category=category,
                    use_name=name,
                    symbol=symbol,
                    source_section=f"p. {number}",
                    page=number,
                    column_header=meta.columns.get(code, code),
                )
            )
    return rows, meta, category


def _usable(word: dict) -> dict | None:
    text = (word.get("text") or "").strip()
    if not text or text.lower().startswith("http"):
        return None
    if re.search(r"supp\.?\s*no", text, re.I):
        return None
    word = dict(word)
    word["text"] = text
    return word


def _swap(words: list[dict]) -> list[dict]:
    swapped = []
    for word in words:
        copied = dict(word)
        copied["x0"] = word["top"]
        copied["x1"] = word.get("bottom", word["top"])
        copied["top"] = word["x0"]
        copied["bottom"] = word.get("x1", word["x0"])
        swapped.append(copied)
    return swapped
