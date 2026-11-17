# Requirements: Zoning PDF → Structured Output Framework

**Audience:** Cursor (AI coding agent) and the developers working with it.
**Owner:** Adithya (Location IQ / Cortex, Step 2).
**Constraint:** runs locally. No API keys and no paid/cloud AI services. Internet access is allowed (pip installs, downloading a local model, downloading linked zoning documents).
**Status:** Baseline code exists (`zoning_pdf_to_excel.py`) and reproduces 3 golden outputs exactly. This document defines the full framework to build on top of it.

---

## 0. How Cursor should use this document

1. Read the whole document before writing code.
2. Start from the baseline script `zoning_pdf_to_excel.py` (and `configs/*.json`). Do not rewrite working parts without a reason.
3. Build in the order of Section 13 (Milestones).
4. After every change, run the regression tests (Section 11). **A change is only done when all golden tests pass.**
5. If a golden test fails, fix the code. Never edit the golden files to make a test pass.
6. When something in a PDF is ambiguous, output `Unclear` and log it. Never guess.
7. Do not add any cloud AI API or API key. Processing runs locally; plain internet downloads are allowed (Section 9a).

---

## 1. Goal

Turn each municipal code PDF (about 19,000 files) into one **standard structured output per municipality** with:

1. Every zoning district: code, name, and what it means.
2. For every zone × every use listed in the code: whether the use is **Permitted / Permitted with conditions / Conditional / Temporary / Not permitted / Unclear**, plus how it is approved, by whom, and the exact law section.

This output feeds:
- the **Law Information Table** (Cortex knowledge base), and
- the **Zone Code Table** (matched against ArcGIS zone labels using Census GeoID + zone code).

---

## 1a. Architecture overview (framework)

The framework is built once. Only a small JSON config changes per city.

```
         ┌──────────── FRAMEWORK (built once) ─────────────┐
PDF ───► │ read text → gate check → find zones/legend/table │ ───► 4-sheet Excel
         │ → table parser / list reader → normalize → checks │      + run log
         └────────────────────▲─────────────────────────────┘
                              │
                   City config (small JSON per city)
                   made by: rule reader → optional local
                   model (Ollama) → review queue
```

| Part | Built once or per city? | Section |
|---|---|---|
| Text extraction, gate check, page finding | Once | 5 (S0–S3) |
| Table parser (normal + sideways) | Once | 5 (S6) |
| District-list reader | Once | 5 (S6) |
| Rule reader, optional local model, review queue | Once | 9 |
| Normalization, checks, writers, batch runner | Once | 5 (S7–S9), 10 |
| City config (pages, codes, symbols, special cases) | Per city, auto-generated where possible | 8 |

Adding a new city must never require new code, only a config.

## 2. Scope

**In scope**
- Text-based PDFs from Municode, eCode360, American Legal and city websites.
- Use tables in any layout: normal grid, sideways (rotated) grid, matrix with blank = prohibited.
- Use rules written as lists per district ("Permitted uses: …", "Special exceptions: …").
- Detecting PDFs that do not contain the zoning (they point to a separate document).
- Validation, logging, batch processing of 19k files, resumable runs.

**Out of scope (for now)**
- Downloading PDFs (Step 1, already done).
- ArcGIS layers and the GeoID mapping (Steps 5–7, separate work).
- Dimensional rules (setbacks, height, lot size). Capture section references only.
- Planned Development (PD/PDD) ordinances. Flag these zones; don't extract their rules.

---

## 3. Inputs

| Input | Description |
|---|---|
| PDF folder | e.g. `pdfs/<STATE>/<file>.pdf` |
| File manifest (CSV, optional) | `file, state, municipality, type, county, census_geoid` when known |
| City config (JSON, optional) | Per-city overrides (Section 8). Generated automatically where possible |

Municipality `type` values: `City`, `Town`, `Village`, `Township`, `Borough`, `County`.

---

## 4. Outputs (exact contract; do not change names or order)

### 4.1 One Excel per municipality
File name: `<STATE>_<MunicipalityNoSpaces>_<Type>_Zoning.xlsx`
Examples: `NH_Concord_City_Zoning.xlsx`, `TX_SugarLand_City_Zoning.xlsx`, `NH_Meredith_Town_Zoning.xlsx`

Optionally also write the same data as CSV / Parquet (`--format csv|parquet|xlsx|all`) for loading into Snowflake. Column names must be identical across formats.

**Sheet 1: `Zones`**

| Column | Description |
|---|---|
| state | 2-letter state |
| municipality | Name |
| type | City / Town / Village / Township / Borough / County |
| county | County name(s) |
| zone_code | Exactly as printed (e.g. `RS-12`, `CMX-2.5`, `B-O`). If the law prints no codes, create a short label and log `zone_codes_invented` |
| zone_name | Full district name |
| zone_group | Residential / Commercial / Industrial / Mixed Use / Downtown / Special / Overlay / Performance / Other |
| zone_type | Base district / Overlay district / Special district / Combining district |
| zone_meaning | One plain sentence from the district's purpose/intent text |
| use_table_column | The use-table column this zone is read from (blank for zones with no table) |
| source_section | Section/table reference |

**Sheet 2: `Use Matrix`**
`use_category, use_name, <one column per zone_code in Zones order>`. Cells hold the city's original symbol. Cell fill by permission:

| permission | colour |
|---|---|
| Permitted | `C6EFCE` |
| Permitted with conditions | `E2F0D9` |
| Conditional | `FFEB9C` |
| Temporary | `DDEBF7` |
| Not permitted | `F2F2F2` |
| Unclear | `F8CBAD` |

**Sheet 3: `Permitted Uses`** (one row per zone × use)

| Column | Description |
|---|---|
| state, municipality, type, county | As above |
| zone_code | Real zone code (after column → zone expansion) |
| use_category | Category heading from the table/list |
| use_name | Use name as printed (line-break hyphens re-joined) |
| symbol | City's original symbol (`P`, `C`, `SE`, `CU`, `P(N)`, `P*`, `-`, `(blank)`) |
| permission | One of the 6 standard values (Section 7) |
| approval_route | One short plain sentence (e.g. "Conditional Use Permit; supplemental regulations apply") |
| approval_body | Who approves (Zoning Board of Adjustment, Planning Board, City Council, Director) or blank |
| source_section | Table/section reference |

**Sheet 4: `Legend`**
`symbol, permission, meaning, approved_by`, then two rows below the table:
`Source document | <publication, supplement, current-through ordinance/date>` and `Municipality | <name, state (type, county)>`.

**Formatting:** Arial 10, bold header, freeze panes (Use Matrix at C2, others at A2), autofilter, codes stored as text.

### 4.2 Run log: `output/run_log.csv` (append, one row per check)
`file, state, municipality, type, county, check, result, message, link_raw, link_guess, pages`
`result` ∈ `PASS | WARN | FAIL | INFO`.

### 4.3 Triage file: `output/triage.csv` (one row per PDF, Milestone 2)
`file, state, municipality, type, county, pages, text_layer, publication, supplement, current_through, zoning_found, pointer_found, pointer_link, format, table_pages, rotated, bucket, status`

---

## 5. Processing pipeline

```
PDF
 ├─ S0  Text extraction (layout text + word positions)
 ├─ S1  Identify document (city, publication, supplement, current-through)
 ├─ S2  Gate check (zoning present? points elsewhere? scanned?)
 ├─ S3  Locate zone list, legend, unlisted-use rule, use table/lists
 ├─ S4  Detect format: GRID / ROTATED_GRID / DISTRICT_LISTS / CUMULATIVE / NONE
 ├─ S5  Build city config (auto; LLM-assisted where needed)
 ├─ S6  Extract rules (position parser OR list reader)
 ├─ S7  Normalize (codes, names, symbols → permissions, column → zone expansion)
 ├─ S8  Validate
 └─ S9  Write outputs + log
```

### S0. Text extraction
- `pdftotext -layout` (full text, split pages on `\f`), and `pdftotext -bbox` / `-bbox-layout` per page for word coordinates (poppler). PyMuPDF may be added as a fallback but **must reproduce the golden outputs** before replacing poppler.
- If the average text per page is under ~100 characters → `SCANNED_PDF`, bucket D, stop (OCR is a later milestone).

### S1. Identify document
Search the first ~30 pages for:
- Supplement: `Supplement No\.\s*\d+`
- Current through: `through Ordinance No\. …`, `enacted …`, dates
- Publication: Code of Ordinances / Land Development Code / Unified Development Code / Development Code / Zoning Ordinance
- Municipality and state: from the manifest if given, else from the title page.

### S2. Gate check (log each)
| Check | Detect with | PASS when |
|---|---|---|
| `text_layer` | Characters per page | Above threshold |
| `zoning_chapter_found` | Headings: `ZONING`, `LAND DEVELOPMENT CODE`, `UNIFIED DEVELOPMENT`, `DEVELOPMENT CODE`, `ZONING REGULATIONS`, `ZONING AND LAND USE` | Found |
| `zone_list_found` | `districts established`, `zoning districts`, `districts and map codes`, `district listing`, `classification of districts`, `Table 2-1` | Found |
| `use_list_found` | `permitted uses`, `use table`, `table of uses`, `land use matrix`, `schedule of uses`, `schedule of principal uses`, `use chart`, `table of principal uses`, `special exceptions` | Found |
| `external_pointer` | Inside a short zoning chapter: `published separately`, `available at`, `can be found`, `found here`, `repealed`, `replaced`, `is on file`, plus a URL | Not found |

Status rules:
- Zoning chapter is a short placeholder **and** points outside → `ZONING_NOT_IN_PDF`; log `link_raw` (exactly as printed) and `link_guess` (spaces → `-`, trailing punctuation removed); **no Excel**.
- Zoning found but no zone list or no use rules → `NO_USE_TABLE`; no Excel.
- No zoning words at all → `NO_ZONING_FOUND`; no Excel.

### S3. Locate the pieces
- **Zone list:** district-establishment section, district table, district section headings; fall back to use-table headers.
- **Legend:** text near the table: `P =`, `C =`, `denoted by`, `Blank`, `— =`, `not permitted`, `special exception`, `conditional use`.
- **Unlisted-use rule:** `not listed`, `not specified`, `similar use`, `uses not expressly`.
- **Use table pages:** pages where most known zone codes appear on one line (same y on normal pages, same x on rotated pages).

### S4. Format detection
| Format | Signal | Examples |
|---|---|---|
| GRID | Header row of zone codes on a line with constant y | Austin, Philadelphia |
| ROTATED_GRID | Header codes share a constant x; text runs vertically | Abilene, Sugar Land, Concord |
| DISTRICT_LISTS | District sections contain "Permitted uses" / "Special exceptions" lists; no code header row | Meredith, Keene (non-downtown) |
| CUMULATIVE | "All uses permitted in X, plus …" | Older codes |
| NONE | Nothing found | → flag |

A city may mix formats (Keene: grid for downtown, lists elsewhere).

### S5. City config
Every city is processed through a JSON config (schema in Section 8). Config sources, in order:
1. Existing file in `configs/` (manual or approved).
2. **Auto-generated:** Python fills everything it can detect (pages, header codes, rotation, symbol set seen in cells, category headings).
3. **Local readers** (Section 9: rules first, optional local model, then human review) for what needs reading comprehension: symbol meanings, blank-cell rule, unlisted-use rule, zone names/meanings, column → zone mapping, approval bodies.

Save every generated config to `configs/generated/` so results are repeatable and reviewable.

### S6. Extraction
**Position parser (GRID / ROTATED_GRID)** (behaviour already implemented in the baseline):
1. Words with coordinates per page.
2. Find header row(s): zone codes sharing one coordinate (≥80% of expected codes). Several header rows per page are allowed (a page can end one table and start the next).
3. Choose axes: if the codes share x → rotated (zones along y, rows along x).
4. Name side = side of the zone band holding the `name_anchor` word (`Land`, `Description`, `Permitted`, `Use`); fall back to the side with more letters.
5. Build rows from use-name lines:
   - `row_start_regex` when uses are numbered (Concord `^(\d+[A-Z]?)\s`),
   - else a line-gap threshold (default 13 pt),
   - or `row_mode: "blocks"` (poppler text blocks) when names wrap tightly (Abilene).
6. Category rows match `category_regex` and have no values.
7. Assign each symbol word to the nearest column (tolerance ~14 pt) and to the row whose position covers it (nearest first line).
8. Join multi-token cells (`P` + `(N)` → `P(N)`; `P/` + `C` → `P/C`).
9. Capture text on the far side of the band (standards/notes column) as `side_text`.
10. Drop page furniture with `drop_token_regex` (`Supp.`, page labels like `CDA:150`, `LDC2:46`, `6183`).
11. Stop at `stop_regex` (e.g. a footnote list starting `1. `).
12. Re-join hyphenated breaks: `Sin- gle` → `Single`; keep `Self- Serve` → `Self-Serve`.

**List reader (DISTRICT_LISTS / CUMULATIVE)** (to build):
1. Split the zoning text into district sections using the zone list.
2. Within each section find list headings (Permitted Uses / Special Exceptions / Conditional Uses / Uses by Right / Accessory Uses) and their numbered or lettered items.
3. Item text → `use_name`; parenthetical conditions → `approval_route`; footnote markers (`*`, `**`) → link to their explanation.
4. Build the city's use list = union across districts. For each zone × use: the listed category, or the unlisted-use rule.
5. CUMULATIVE: copy the referenced district's uses first, then apply additions and removals.
6. Sections the RuleReader can't parse go to the LocalLLMReader (if enabled) or the ReviewQueue; output follows the same JSON schema (Section 9).

### S7. Normalization
- Zone codes: trim, collapse spaces (`R- 4` → `R-4`), keep case and hyphens as printed.
- Expand table columns that cover several zones via `column_to_zones` (Abilene `RS` → `RS-12, RS-8, RS-6`; `RR` → `RR-1, RR-5`).
- Use names: whitespace collapse, configured fixes (`use_name_fixes`), strip `*` (it becomes a condition flag), strip use numbers into the section reference.
- Symbols → permission using **this city's legend only** (Section 7).
- Merge obvious duplicate use names within a city only (log the merges).

### S8. Validation (log every check)
| Check | Rule | Result if broken |
|---|---|---|
| `zone_match` | Every zone in the rules is in the zone list | WARN (list them) |
| `zone_coverage` | Every base zone with a table column has rules | WARN |
| `grid_complete` | rows = uses × zones-with-rules | FAIL |
| `legend_coverage` | Every symbol found is mapped | FAIL (list unknown symbols) |
| `no_empty_permission` | No empty permission | FAIL |
| `unclear_rate` | Unclear ≤ 5% of rows | WARN |
| `parser_issues` | Unassigned values / duplicate cells | WARN (list ≤ 20) |
| `spot_check` | 10 random rows with page numbers | INFO |

FAIL → write the Excel only if `--write-on-fail` is set, and mark it `_CHECK` in the file name.

### S9. Write outputs
Exactly as Section 4. Re-running the same PDF + config must produce byte-for-byte identical data (deterministic ordering: zones in zone-list order, uses in table order).

---

## 6. Things we learned from real PDFs (must be handled)

| # | Situation | City | Required behaviour |
|---|---|---|---|
| 1 | Zoning is a separate document; the code only has a placeholder chapter with a link | Keene NH (Code of Ordinances, p. 799) | `ZONING_NOT_IN_PDF`, log link_raw + link_guess, no Excel |
| 2 | URL broken by a space in the PDF | Keene: `…/land-development code` | link_guess = `…/land-development-code` |
| 3 | Sideways tables; plain text loses columns | Abilene, Sugar Land, Concord | Position parser with axis swap |
| 4 | Blank cell = not permitted | Abilene, Sugar Land | `blank` rule from config |
| 5 | Blank cell has no legend meaning | Concord (ADU, Mortuary) | `(blank)` → Unclear |
| 6 | Zone code equals a symbol | Concord zone `CU` vs symbol `CU` | Only header-row words count as zone codes |
| 7 | Table column covers several map zones | Abilene `RS`, `RR` | `column_to_zones` |
| 8 | No zone codes in the law | Meredith NH | Invent labels, log WARN |
| 9 | Symbols with notes | Sugar Land `P(N)`, `C(N)`, `P/C(N)`, `An` | Combine tokens; map each |
| 10 | `*` on the use name = conditions apply | Abilene `Fuel Sales*` | `P` → Permitted with conditions |
| 11 | `*` on the zone header = extra approval in that zone | Sugar Land `B-O*` | `extra_route_columns` text |
| 12 | Standards column lists sections | Concord "Section 28-5-17" | `P` → Permitted with conditions; cite sections |
| 13 | Mixed symbols | Abilene `P/C`, `P/SE` | Permitted with conditions + route |
| 14 | Use allowed only in an overlay | Sugar Land Bar → AB-OP | `use_overrides` |
| 15 | Use is a container, not a use | Sugar Land Shopping Center | `use_overrides` → Unclear |
| 16 | Use excluded city-wide | Abilene Feedlot | `use_overrides` → Not permitted |
| 17 | Category heading missing in the table | Abilene Manufacturing rows | `category_override` |
| 18 | Page numbers / headers inside names | Concord `6184`, Sugar Land `LDC2:46` | `drop_token_regex` |
| 19 | Footnote list under the table | Sugar Land `1. Dwelling, Live/Work …` | `stop_regex` |
| 20 | Two tables on one page | Concord p. 836 (principal ends, accessory starts) | Multiple header rows per page |
| 21 | Unlisted uses decided by an official | Abilene, Concord, Sugar Land | Missing uses → Unclear |
| 22 | Unlisted uses prohibited | Philadelphia, Meredith, Keene | Missing uses → Not permitted |
| 23 | Same letter, different meaning by city | `S`, `X` | Always map from this city's legend |
| 24 | Old cross-references in brackets | Abilene "Article 5 [Article 4]" | Cite the bracketed (current) number |
| 25 | PDF is old | Meredith (June 2022) | Log the supplement date; WARN if older than 2 years |

---

## 7. Permission vocabulary (fixed)

| permission | Use for |
|---|---|
| Permitted | By right, no conditions |
| Permitted with conditions | By right with footnote / `*` / `(N)` / standards section / `P1`; also mixed `P/C`, `P/SE`, ancillary-only `An` |
| Conditional | CUP, SUP, Special Exception, Conditional Use, Specific Use; any board approval |
| Temporary | Temporary permit only (`TP`) |
| Not permitted | `—`, `-`, `N`, blank (only if the legend says so), unlisted (only if the code says unlisted = prohibited) |
| Unclear | Anything not resolvable from the text. Never guess |

---

## 8. City config schema (JSON)

```json
{
  "state": "NH", "municipality": "Concord", "type": "City", "county": "Merrimack",
  "source_document": "Supplement No. 61 (May 2026), through Ord. No. 3193",
  "parser": {
    "name_anchor": "^Description$",
    "row_mode": "lines | blocks",
    "row_start_regex": "^(\\d+[A-Z]?)\\s",
    "category_regex": "^[A-M]\\s+[A-Z]{3}",
    "drop_token_regex": "^(6[12]\\d\\d|Supp\\.|No\\.)$",
    "skip_line_regex": "^(TABLE OF|Use #)",
    "stop_regex": "^\\d+\\.\\s",
    "row_gap": 13, "col_tol": 14, "band_pad": 12
  },
  "tables": [{
    "name": "Principal and Accessory",
    "pages": [829, 837],
    "columns": ["RO", "RM", "..."],
    "value_regex": "^(P|SE|CU|-)$",
    "section": "Concord Code § 28-2-4(j)-(k)",
    "use_number_regex": "^(\\d+[A-Z]?)\\s+",
    "category_map": {"A RESIDENTIAL": "Principal: Residential"},
    "standards_regex": "(?:Section|Article)\\s+28-\\d+(?:-\\d+)?"
  }],
  "symbols": {"P": ["Permitted", "Allowed by right", ""],
              "SE": ["Conditional", "Special exception", "Zoning Board of Adjustment"]},
  "blank": ["(blank)", "Unclear", "Cell is blank in the table", ""],
  "column_to_zones": {"RS": ["RS-12", "RS-8", "RS-6"]},
  "extra_route_columns": {"B-O": "a CUP is also required if the site abuts a single-family lot"},
  "use_overrides": {"Bar": ["-", "Not permitted", "Allowed only in the AB-OP overlay", ""]},
  "use_name_fixes": {"\\(\\s*\"\\s*6": "(6 or fewer"},
  "category_override": {"Liquor": "Manufacturing Uses"},
  "drop_use_regex": "^\\(Ord",
  "star_text": "use-specific conditions apply",
  "unlisted_rule": {"missing_uses_are": "Unclear", "quote": "...", "section": "..."},
  "zones": [{"zone_code": "RO", "zone_name": "...", "zone_group": "...", "zone_type": "Base district",
             "zone_meaning": "...", "use_table_column": "RO", "source_section": "..."}],
  "legend": [["P", "Permitted", "Permitted by right", ""]]
}
```
Validate configs against a JSON Schema (`schema/config.schema.json`) before use.

---

## 9. Reader interface: local (no API keys)

**Constraint: all reading/AI runs on the local machine. No API keys and no cloud AI services. Internet may be used for downloads only.**

Python cannot always decide what a city's symbols mean or how its lists are worded. Those steps go through one interface with **local-only** implementations:

```python
class Reader(Protocol):
    def read_legend(self, pages_text: str) -> dict: ...      # symbols, blank rule, unlisted rule
    def read_zones(self, pages_text: str) -> list[dict]: ... # zone list with names and meanings
    def read_district_lists(self, section_text: str) -> list[dict]: ...
    def fix_config(self, config: dict, run_log: list, samples: list) -> dict: ...
```

Implementations, tried in this order:
1. `ManualReader`: loads approved configs from `configs/`. Used by the golden tests.
2. `RuleReader` (pure Python, build first): handles the common, regular cases with patterns and dictionaries:
   - **Legend:** regexes for `X = meaning`, `X - meaning`, `X: meaning`, "denoted by X", "Blank = …", "— = …". Map the meaning text to a permission with a phrase dictionary, e.g. `permitted|by right|allowed` → Permitted; `conditional use|special use|specific use|special exception|SUP|CUP` → Conditional; `temporary` → Temporary; `not permitted|prohibited|not allowed` → Not permitted; `subject to|with conditions|supplemental|standards` → Permitted with conditions. Approval body from phrases such as "Zoning Board of Adjustment", "Board of Adjustment", "Planning Board", "Planning Commission", "City Council".
   - **Unlisted rule:** sentences containing `not listed|not specified|not expressly` combined with `prohibited|not permitted` → Not permitted; with `determine|similar|interpret|classify` → Unclear.
   - **Zone list:** patterns such as `name ..... CODE`, `CODE  Name`, `(n) name (CODE)`, `"CODE" name District`, and section headings `Sec. x CODE Name District`.
   - **Zone meaning:** first sentence after `Purpose`, `Intent` or `is established` in each district section.
   - **District lists:** headings `Permitted Uses`, `Uses Permitted by Right`, `Special Exceptions`, `Conditional Uses`, `Accessory Uses`, followed by numbered/lettered items.
   - Anything it can't match confidently → leave empty and pass to the next reader.
3. `LocalLLMReader` (optional fallback): an open model running on the same machine through **Ollama** (`http://localhost:11434`; the model is downloaded once from the internet, then runs locally). Same prompt and JSON schema as below, temperature 0, JSON output mode. The model name is a setting (e.g. a Qwen or Llama instruct model). Hardware guide: about 16 GB RAM for ~7–8B models; 32 GB+ or a GPU for larger, more accurate models. Larger models read legends and lists more accurately but run slower.
4. `ReviewQueue`: anything still unresolved is written to `review/<city>.json` with the relevant page text. A person fills in the missing fields; the file becomes the city's approved config. Nothing is guessed.

Rules for every reader:
- Read only the located pages (zone list, legend, rule text, district sections), never the whole PDF.
- Output must validate against the JSON schema; on failure try the next reader.
- Never invent zones, uses or permissions; use `Unclear` with a note.
- Copy codes and names exactly; symbol meanings come from this document's legend only.
- Log which reader produced each field (`source_reader` = manual / rule / local_llm / review).

**Prompt (used by the LocalLLMReader):**
```
You are extracting zoning rules from a US municipal code. Read ONLY the text provided.
Return ONLY valid JSON matching the schema. No commentary.
Municipality: {municipality}, {state} ({type}, {county}). Source: {source_document}. Pages: {pages}

1. ZONES: every district; zone_code exactly as printed; zone_name; zone_group; zone_type;
   one plain sentence zone_meaning from the purpose/intent text; source_section; page.
2. LEGEND: every symbol used for uses, its meaning as written, who approves, and one
   permission: Permitted | Permitted with conditions | Conditional | Temporary | Not permitted | Unclear.
3. BLANK: what an empty cell means, only if the text says so; else "Unclear".
4. UNLISTED_RULE: quote the sentence on uses not listed; say "Not permitted" or "Unclear".
5. USES (only for district lists): each use per district with its list type, any condition
   in one short sentence, section and page.
6. EXTERNAL_POINTER: if zoning is published elsewhere, quote it with page and URL as printed.
Never guess. If unsure, use "Unclear" and explain in "note".
```

---

## 9a. Allowed internet use (no API keys)

| Use | Behaviour |
|---|---|
| Follow external pointers | When the gate check finds `ZONING_NOT_IN_PDF` with a link (e.g. Keene `…/land-development code`), try `link_raw`, then `link_guess`; if the page is HTML, collect PDF links whose text or file name contains zoning / land development / unified development / LDC / UDC; download to `pdfs/linked/<STATE>_<City>/`, log the URL and file hash, and re-run the pipeline on the new PDF |
| Fetch a city's zoning page | Optional: given a city website URL (e.g. the Census roster `WEB_ADDRESS`), look for zoning PDFs the same way |
| Setup | `pip install` packages; download poppler; download the local Ollama model once |

Rules: identify with a clear User-Agent; at most 1 request per second per domain; respect robots.txt; time out after 30 s; retry once; never send PDF content anywhere; never call AI or code-publisher APIs.

## 10. Batch processing (19k PDFs)

- CLI:
  - `python -m zoning run --pdf file.pdf [--config c.json]`
  - `python -m zoning triage --dir pdfs/ --out output/triage.csv`
  - `python -m zoning batch --dir pdfs/ --bucket A --workers 8`
- Parallel workers (`multiprocessing`), one PDF per task, timeout per PDF (e.g. 5 minutes).
- **Resumable:** skip PDFs whose output and log already exist unless `--force`.
- Deterministic file naming; never overwrite approved configs.
- Progress bar and a summary at the end: counts by status and bucket.
- Buckets after triage: `A` grid/rotated, `B` district lists, `C` zoning not in PDF, `D` scanned, `E` no zoning found.

---

## 11. Regression tests (golden outputs)

Put the PDFs in `tests/pdfs/` and the approved Excels in `tests/golden/`. Tests compare the **Permitted Uses** sheet with pandas `DataFrame.equals` after reading both files, plus the Zones sheet row count.

| Test | PDF | Config | Expected |
|---|---|---|---|
| T1 Concord | `Code_of_Ordinances_bc6eb4.pdf` | `NH_Concord.json` | 23 zones; 2,574 rows; identical to golden |
| T2 Sugar Land | `Sugar_Land__TX_Land_Development_Code.pdf` | `TX_SugarLand.json` | 20 zones; 979 rows; identical to golden |
| T3 Abilene | `Abilene__TX_Code_of_Ordinances__1_.pdf` | `TX_Abilene.json` | 28 zones; 2,944 rows; identical to golden |
| T4 Keene gate | `Code_of_Ordinances.pdf` (Keene) | none | Status `ZONING_NOT_IN_PDF`; pointer page 799; no Excel |
| T5 Meredith lists | `Code_of_Ordinances_1.pdf` (Meredith) | to build | 9 zones; 68 uses; 612 rows; matches golden (Milestone 4) |
| T6 Keene LDC | Keene standalone LDC PDF | to build | 29 zones (24 base + 5 overlays); 1,992 rows (Milestone 4) |

**Cell-level spot tests (must pass):**
| City | Use | Zone | Expected symbol → permission |
|---|---|---|---|
| Concord | Retail sale of gasoline | CN | `CU` → Conditional (Planning Board) |
| Concord | Retail sale of gasoline | GWP | `P` → Permitted with conditions (Section 28-5-17) |
| Concord | Retail sale of gasoline | RO | `-` → Not permitted |
| Concord | Accessory Dwelling Unit | CG | `(blank)` → Unclear |
| Sugar Land | Gas Pumps (Accessory) | B-1 | `C(N)` → Conditional |
| Sugar Land | Gas Pumps (Accessory) | M-1 | `P(N)` → Permitted with conditions |
| Sugar Land | Bar | B-2 | `-` → Not permitted (AB-OP overlay only) |
| Abilene | Fuel Sales (Trade - Retail) | GR | `P*` → Permitted with conditions |
| Abilene | Fuel Sales (Trade - Retail) | NR | `C` → Conditional |
| Abilene | Wind Energy Conversion Systems | AO | `P/SE` → Permitted with conditions |
| Abilene | Any use | RS-12 / RS-8 / RS-6 | Same value as table column `RS` |

**Unit tests:** hyphen re-join, URL guess, symbol token joining, axis detection, column → zone expansion, permission mapping.

---

## 12. Code structure

```
zoning/
  __main__.py          CLI (run | triage | batch)
  extract_text.py      pdftotext wrappers (layout, bbox, bbox-layout), caching per page
  identify.py          S1 document info
  gate.py              S2 gate checks + pointer/link handling
  locate.py            S3 zone list / legend / table pages
  detect.py            S4 format detection
  config.py            S5 load/auto-build/validate configs
  parse_table.py       S6 position parser (from baseline table_parser)
  parse_lists.py       S6 district-list reader
  normalize.py         S7
  validate.py          S8
  write_outputs.py     S9 Excel/CSV/Parquet (from baseline excel_writer)
  readers/manual.py, readers/rules.py, readers/local_llm.py (Ollama, optional), readers/review_queue.py
schema/config.schema.json, schema/llm_output.schema.json
configs/  configs/generated/
tests/pdfs/ tests/golden/ tests/test_golden.py tests/test_units.py
output/
```
Python 3.10+, dependencies: `pandas`, `openpyxl`, `jsonschema`, `tqdm`, `pyarrow` (Parquet), `requests` + `beautifulsoup4` (local Ollama server and plain downloads, Section 9a); system: poppler (`pdftotext`); optional: Ollama + one local model. No cloud SDKs. Type hints, docstrings, `logging` instead of print. No hard-coded city logic in code; city specifics live in configs.

---

## 13. Milestones (build in this order)

| # | Milestone | Done when |
|---|---|---|
| M1 | Restructure the baseline into the package; same behaviour | T1–T3 identical, T4 passes |
| M2 | Triage command for the 19k folder | `triage.csv` produced for all PDFs; buckets counted |
| M3 | Auto-config for grid/rotated tables (Python detects pages, header codes, rotation, symbols; reader fills meanings) | Running with **no** config on T1–T3 gives the same rows, or the differences are listed in the log |
| M4 | District-list reader | T5 and T6 pass |
| M5 | RuleReader (legend, unlisted rule, zone list, purposes) + ReviewQueue; then optional LocalLLMReader via Ollama | A new grid-table city runs end to end locally; unresolved fields land in review/ |
| M5b | Pointer follower (Section 9a): Keene Code of Ordinances → downloads the standalone LDC and processes it | T4 downloads the linked document and logs it |
| M6 | Batch runner (parallel, resumable, summary) | Pilot of 50 PDFs completes with a status for each |
| M7 | Pilot report | % passing all checks, time per PDF, top failure reasons |

---

## 14. Acceptance criteria

- All golden and spot tests pass after every change.
- Every PDF ends with a status (OK / ZONING_NOT_IN_PDF / NO_USE_TABLE / NO_ZONING_FOUND / SCANNED_PDF / FAILED).
- Every output row carries a section reference.
- No row has an empty permission; unknown → Unclear.
- Same input + config → identical output.
- The 50-PDF pilot runs unattended and produces the summary report.

---

## 15. Definitions

- **Zone / district:** an area of the municipality with its own rules (e.g. `RS-12`).
- **Zone code:** its short label, as printed in the law and on the map.
- **Use table:** grid of uses × zones with symbols.
- **District lists:** per-district written lists of permitted uses / special exceptions.
- **Overlay / combining district:** extra layer on top of a base zone (e.g. AB-OP, CO, NP).
- **Legend:** the city's key that explains its symbols.
- **Unlisted-use rule:** what the code says about uses not named anywhere.
