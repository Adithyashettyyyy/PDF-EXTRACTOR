"""
zoning_pdf_to_excel.py  -  one-file version
Turns a municipal code PDF into the standard 4-sheet zoning Excel
(Zones, Use Matrix, Permitted Uses, Legend) + run_log.csv.

SETUP (once):
  pip install pandas openpyxl
  Install poppler so `pdftotext` works in the terminal:
    Windows: download "poppler for Windows", unzip, add its Library\bin folder to PATH
    Mac:     brew install poppler
  Check:   pdftotext -v

RUN (Concord, NH - config is built in):
  python zoning_pdf_to_excel.py --pdf "Code_of_Ordinances_bc6eb4.pdf"
  Expected: output/NH_Concord_City_Zoning.xlsx with 23 zones and 2,574 rows.

OTHER CITIES:
  python zoning_pdf_to_excel.py --pdf "city.pdf" --config "configs/TX_SugarLand.json"
"""
import argparse, json, re, csv, os, subprocess, html
from collections import Counter
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

# ===================== TABLE PARSER =====================

def page_words(pdf, p):
    out = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-bbox', pdf, '-'],
                         capture_output=True, text=True).stdout
    return [(list(map(float, a)), html.unescape(t)) for *a, t in re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', out)]

def page_blocks(pdf, p):
    out = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-bbox-layout', pdf, '-'],
                         capture_output=True, text=True).stdout
    blocks = []
    for b in re.findall(r'<block (.*?)</block>', out, re.S):
        ws = [(list(map(float, a)), html.unescape(t)) for *a, t in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', b)]
        if ws: blocks.append(ws)
    return blocks

def _axes(rot):
    if rot:   # sideways page: zones spread along y, rows run along x
        return (lambda b: (b[1]+b[3])/2), (lambda b: (b[0]+b[2])/2)
    return (lambda b: (b[0]+b[2])/2), (lambda b: (b[1]+b[3])/2)

def find_headers(W, columns, min_share=0.8):
    """Return list of (rot, hv, {col: u}) header rows found on the page."""
    need = max(1, int(len(columns) * min_share)) if len(columns) > 1 else 1
    found = []
    for rot in (False, True):
        U, V = _axes(rot)
        groups = {}
        for bb, t in W:
            c = t.rstrip('*')
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
    tall = sum(1 for b in words if (b[3]-b[1]) > (b[2]-b[0]))
    return tall > len(words) / 2

def parse_table(pdf, pages, columns, value_re, cfg):
    """Return rows: dict(page, category, use, cells{col: symbol}, side_text)."""
    VAL = re.compile(value_re)
    row_start = re.compile(cfg.get('row_start_regex', r'^$a'))
    cat_re = re.compile(cfg.get('category_regex', r'^$a'))
    skip_re = re.compile(cfg.get('skip_line_regex', r'^(Supp\.|Table |TABLE |LEGEND|See Section)'))
    drop_tok = re.compile(cfg.get('drop_token_regex', r'^(Supp\.|No\.)$'))
    stop_re = re.compile(cfg.get('stop_regex', r'^\d+\.\s'))
    gap = cfg.get('row_gap', 13)
    rows, cat, issues, stopped = [], None, [], False
    for p in pages:
        if stopped: break
        W = page_words(pdf, p)
        heads = find_headers(W, columns)
        if not heads:
            issues.append((p, 'no header')); continue
        for hi, (rot, hv, hdr) in enumerate(heads):
            U, V = _axes(rot)
            vend = heads[hi+1][1] - 6 if hi + 1 < len(heads) else 1e9
            ulo, uhi = min(hdr.values()), max(hdr.values())
            band = cfg.get('band_pad', 12)
            # name side = side of the band holding more letters
            words = [(bb, t) for bb, t in W if hv + 4 < V(bb) < vend and not drop_tok.match(t)]
            hi_side = sum(len(t) for bb, t in words if U(bb) > uhi + band and not VAL.match(t))
            lo_side = sum(len(t) for bb, t in words if U(bb) < ulo - band and not VAL.match(t))
            side = cfg.get('name_side') or (1 if hi_side >= lo_side else -1)
            if cfg.get('name_anchor'):
                anc = [U(bb) for bb, t in W if re.match(cfg['name_anchor'], t) and abs(V(bb) - hv) < 8]
                if anc: side = 1 if anc[0] > uhi else -1
            inname = (lambda u: u > uhi + band) if side == 1 else (lambda u: u < ulo - band)
            inside_txt = (lambda u: u < ulo - band) if side == 1 else (lambda u: u > uhi + band)
            order = (lambda w: -U(w[0])) if (rot and side == 1) else (lambda w: U(w[0]))
            nw = sorted([w for w in words if inname(U(w[0]))], key=lambda w: V(w[0]))
            lines = []
            for bb, t in nw:
                if lines and abs(V(bb) - lines[-1]['v']) < 3: lines[-1]['w'].append((bb, t))
                else: lines.append({'v': V(bb), 'w': [(bb, t)]})
            rws = []
            if cfg.get('row_mode') == 'blocks':
                lines = []
                for ws in page_blocks(pdf, p):
                    ws = [w for w in ws if hv + 4 < V(w[0]) < vend and not drop_tok.match(w[1])]
                    if not any(inname(U(w[0])) for w in ws) or all(VAL.match(w[1]) for w in ws): continue
                    vs = [V(w[0]) for w in ws]
                    # keep reading order of the block's words
                    lines.append({'v': min(vs), 'v1': max(vs), 'w': ws, 'block': True})
                lines.sort(key=lambda l: l['v'])
            for ln in lines:
                if not ln.get('block'): ln['w'].sort(key=order)
                txt = ' '.join(t for _, t in ln['w']).strip()
                if not txt or skip_re.match(txt): continue
                if stop_re.match(txt):
                    stopped = True; break
                is_cat = bool(cat_re.match(txt))
                new = is_cat or bool(row_start.match(txt))
                if ln.get('block'):
                    rws.append({'t': txt, 'v0': ln['v'], 'v1': ln['v1'], 'cat': is_cat, 'cells': {}, 'side': []}); continue
                if rws and not new and not rws[-1]['cat'] and ln['v'] - rws[-1]['v1'] < (40 if cfg.get('row_start_regex') else gap):
                    rws[-1]['t'] += ' ' + txt; rws[-1]['v1'] = ln['v']
                else:
                    rws.append({'t': txt, 'v0': ln['v'], 'v1': ln['v'], 'cat': is_cat, 'cells': {}, 'side': []})
            real = [r for r in rws if not r['cat']]
            def owner(v):
                c = [r for r in real if r['v0'] - 8 <= v <= r['v1'] + 8]
                if c: return min(c, key=lambda r: abs(v - r['v0']))
                return min(real, key=lambda r: min(abs(v-r['v0']), abs(v-r['v1']))) if real else None
            for bb, t in words:
                if ulo - band <= U(bb) <= uhi + band and VAL.match(t):
                    r = owner(V(bb)); col = min(hdr, key=lambda k: abs(hdr[k] - U(bb)))
                    if r is None or abs(hdr[col] - U(bb)) > cfg.get('col_tol', 14):
                        issues.append((p, t, 'unassigned')); continue
                    r['cells'].setdefault(col, []).append((U(bb), t))
                elif inside_txt(U(bb)):
                    r = owner(V(bb))
                    if r: r['side'].append((V(bb), order((bb, t)), t))
            for r in rws:
                if r['cat']:
                    cat = r['t']; continue
                txt = re.sub(r'(\w)- ([a-z])', r'\1\2', r['t'])
                txt = re.sub(r'(\w)- ([A-Z])', r'\1-\2', txt).replace('/ ', '/')
                cells = {}
                for c, toks in r['cells'].items():
                    toks = [t for _, t in sorted(toks, key=lambda x: x[0], reverse=(side == 1 and rot))]
                    toks.sort(key=lambda t: t.startswith('('))
                    cells[c] = ''.join(toks)
                side_txt = ' '.join(t for *_, t in sorted(r['side']))
                rows.append({'page': p, 'category': cat, 'use': txt.strip(), 'cells': cells, 'side_text': side_txt})
            if stopped: break
    return rows, issues

# ===================== EXCEL WRITER =====================
ZC=['state','municipality','type','county','zone_code','zone_name','zone_group','zone_type','zone_meaning','use_table_column','source_section']
UC=['state','municipality','type','county','zone_code','use_category','use_name','symbol','permission','approval_route','approval_body','source_section']
FILL={'Permitted':'C6EFCE','Permitted with conditions':'E2F0D9','Conditional':'FFEB9C','Not permitted':'F2F2F2','Unclear':'F8CBAD','Temporary':'DDEBF7'}
def build(path,meta,zones,uses,legend,source):
    zd=pd.DataFrame(zones); ud=pd.DataFrame(uses)
    for k,v in meta.items(): zd[k]=v; ud[k]=v
    for c in ZC:
        if c not in zd: zd[c]=''
    zd=zd[ZC]
    if len(ud):
        ud=ud[UC]
        order=[z for z in zd.zone_code if z in set(ud.zone_code)]
        ud['_s']=ud.symbol.astype(str)
        m=ud.pivot_table(index=['use_category','use_name'],columns='zone_code',values='_s',aggfunc='first',sort=False)[order].reset_index()
        pm=ud.pivot_table(index=['use_category','use_name'],columns='zone_code',values='permission',aggfunc='first',sort=False)[order].reset_index()
        ud=ud.drop(columns='_s')
    else:
        ud=pd.DataFrame([{**meta,'use_category':'(not extracted yet)','use_name':'Use table not available in the source provided','permission':'Unclear'}],columns=UC)
        m=pd.DataFrame([['(not extracted yet)','Use table not available in the source provided']],columns=['use_category','use_name']); pm=None
    lg=pd.DataFrame(legend,columns=['symbol','permission','meaning','approved_by'])
    with pd.ExcelWriter(path,engine='openpyxl') as w:
        zd.to_excel(w,sheet_name='Zones',index=False); m.to_excel(w,sheet_name='Use Matrix',index=False)
        ud.to_excel(w,sheet_name='Permitted Uses',index=False); lg.to_excel(w,sheet_name='Legend',index=False)
        pd.DataFrame([['Source document',source],['Municipality',f"{meta['municipality']}, {meta['state']} ({meta['type']}, {meta['county']})"]]).to_excel(w,sheet_name='Legend',index=False,header=False,startrow=len(lg)+2)
    wb=load_workbook(path)
    for ws in wb:
        for r in ws.iter_rows():
            for c in r: c.font=Font(name='Arial',size=10,bold=(c.row==1))
        ws.freeze_panes='C2' if ws.title=='Use Matrix' else 'A2'
        if ws.title!='Legend': ws.auto_filter.ref=ws.dimensions
        for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=min(60,max(len(str(c.value or '')) for c in col)+2)
    ws=wb['Use Matrix']
    if pm is not None:
        for i,r in enumerate(ws.iter_rows(min_row=2,min_col=3)):
            for j,c in enumerate(r):
                p=pm.iat[i,j+2]
                if p in FILL: c.fill=PatternFill('solid',fgColor=FILL[p]); c.alignment=Alignment(horizontal='center')
        for col in list(ws.columns)[2:]: ws.column_dimensions[col[0].column_letter].width=9
    ws=wb['Zones']; ws.column_dimensions['I'].width=80
    for r in ws.iter_rows(min_row=2): r[8].alignment=Alignment(wrap_text=True,vertical='top')
    ws=wb['Legend']; ws.column_dimensions['B'].width=28; ws.column_dimensions['C'].width=70
    wb.save(path)
    return len(zd),len(ud)

# ===================== BUILT-IN CONFIG: CONCORD, NH =====================
CONCORD_CONFIG = json.loads(r"""
{
 "state": "NH",
 "municipality": "Concord",
 "type": "City",
 "county": "Merrimack",
 "source_document": "Concord NH Code of Ordinances (Municode), Supplement No. 61 (May 2026), through Ord. No. 3193 (Mar 9, 2026); Title IV Zoning Ordinance, Art. 28-2",
 "parser": {
  "row_start_regex": "^(\\d+[A-Z]?)\\s",
  "category_regex": "^[A-M]\\s+[A-Z]{3}",
  "drop_token_regex": "^(6[12]\\d\\d|Supp\\.|No\\.|ZONING|ORDINANCE|CONCORD|CODE)$",
  "skip_line_regex": "^(TABLE OF|BASE DISTRICTS|PRINCIPAL USES|ACCESSORY USES|Use Category|Use #|Supp\\.)",
  "stop_regex": "^NEVER$"
 },
 "tables": [
  {
   "value_regex": "^(P|SE|CU|-|—|–)$",
   "columns": [
    "RO",
    "RM",
    "RS",
    "RN",
    "RD",
    "RH",
    "CN",
    "CG",
    "CU",
    "CH",
    "CBP",
    "GWP",
    "OCP",
    "OFP",
    "CVP",
    "IS",
    "IN",
    "UT"
   ],
   "use_number_regex": "^(\\d+[A-Z]?)\\s+",
   "category_map_by_letter": false,
   "standards_regex": "(?:Section|Article)\\s+28-\\d+(?:-\\d+)?(?:\\([a-z0-9]+\\))?",
   "name": "Principal and Accessory",
   "pages": [
    829,
    837
   ],
   "section": "Concord Code § 28-2-4(j)-(k) Tables of Principal and Accessory Uses",
   "category_map": {
    "A RESIDENTIAL": "Principal: Residential",
    "B EDUCATIONAL AND": "Principal: Educational and Institutional",
    "C SERVICES—ENTERTAINMENT": "Principal: Services - Entertainment and Recreation",
    "D SERVICES—PERSONAL": "Principal: Services - Personal and Business",
    "E SERVICES—MEDICAL": "Principal: Services - Medical",
    "F SERVICES—FINANCIAL": "Principal: Services - Financial and Professional",
    "G SERVICES—LODGING": "Principal: Services - Lodging and Meeting Facilities",
    "H RETAIL TRADE (except": "Principal: Retail Trade",
    "I RESTAURANTS, EATING,": "Principal: Restaurants, Eating, and Drinking Places",
    "J MOTOR VEHICLE SALES": "Principal: Motor Vehicle Sales and Service",
    "K TRANSPORTATION,": "Principal: Transportation, Communications, and Utilities",
    "L MANUFACTURING AND": "Principal: Manufacturing and Construction",
    "M AGRICULTURAL": "Principal: Agricultural",
    "A ACCESSORY TO A": "Accessory: Accessory to a Principal Residential Use",
    "B ACCESSORY TO A": "Accessory: Accessory to a Principal Nonresidential Use",
    "C ACCESSORY TO ANY": "Accessory: Accessory to Any Principal Use"
   }
  }
 ],
 "symbols": {
  "P": [
   "Permitted",
   "Allowed by right",
   ""
  ],
  "SE": [
   "Conditional",
   "Special exception",
   "Zoning Board of Adjustment"
  ],
  "CU": [
   "Conditional",
   "Conditional use permit",
   "Planning Board"
  ],
  "-": [
   "Not permitted",
   "Not permitted",
   ""
  ],
  "—": [
   "Not permitted",
   "Not permitted",
   ""
  ],
  "–": [
   "Not permitted",
   "Not permitted",
   ""
  ]
 },
 "blank": [
  "(blank)",
  "Unclear",
  "Cell is blank in the table; verify with the city",
  ""
 ],
 "zones": [
  {
   "zone_code": "RO",
   "zone_name": "Open Space Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Low-density single-family homes in rural, open-space areas.",
   "use_table_column": "RO",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "RM",
   "zone_name": "Medium Density Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Single-family and two-family homes at medium density.",
   "use_table_column": "RM",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "RS",
   "zone_name": "Single-Family Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Established single-family neighborhoods.",
   "use_table_column": "RS",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "RN",
   "zone_name": "Neighborhood Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Mixed housing types in established neighborhoods with city utilities.",
   "use_table_column": "RN",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "RD",
   "zone_name": "Downtown Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Fully developed mixed-residential neighborhoods around the Concord and Penacook downtowns, up to 14 units per acre.",
   "use_table_column": "RD",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "RH",
   "zone_name": "High Density Residential District",
   "zone_group": "Residential",
   "zone_type": "Base district",
   "zone_meaning": "Existing multifamily and mobile home park developments on large parcels, up to 14 units per acre.",
   "use_table_column": "RH",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CN",
   "zone_name": "Neighborhood Commercial District",
   "zone_group": "Commercial",
   "zone_type": "Base district",
   "zone_meaning": "Homes plus small convenience retail and personal services serving a surrounding neighborhood.",
   "use_table_column": "CN",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CG",
   "zone_name": "General Commercial District",
   "zone_group": "Commercial",
   "zone_type": "Base district",
   "zone_meaning": "Retail, restaurants, services and high-density housing serving a city-wide or regional market along arterial streets.",
   "use_table_column": "CG",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CU",
   "zone_name": "Urban Commercial District",
   "zone_group": "Commercial",
   "zone_type": "Base district",
   "zone_meaning": "Mixed office, retail, restaurant, service, lodging and high-density housing next to the Concord and Penacook downtowns.",
   "use_table_column": "CU",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CH",
   "zone_name": "Highway Commercial District",
   "zone_group": "Commercial",
   "zone_type": "Base district",
   "zone_meaning": "Mixed commercial uses along highways, with buffering for nearby neighborhoods.",
   "use_table_column": "CH",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CBP",
   "zone_name": "Central Business Performance District",
   "zone_group": "Performance",
   "zone_type": "Base district",
   "zone_meaning": "Downtown Concord: central retail, office, government and residential core.",
   "use_table_column": "CBP",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "GWP",
   "zone_name": "Gateway Performance District",
   "zone_group": "Performance",
   "zone_type": "Base district",
   "zone_meaning": "Well-designed large-scale commercial development along arterial streets at the city entrances.",
   "use_table_column": "GWP",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "OCP",
   "zone_name": "Opportunity Corridor Performance District",
   "zone_group": "Performance",
   "zone_type": "Base district",
   "zone_meaning": "Redevelopment of under-used urban land between downtown and I-93 and other former brownfields.",
   "use_table_column": "OCP",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "OFP",
   "zone_name": "Office Park Performance District",
   "zone_group": "Performance",
   "zone_type": "Base district",
   "zone_meaning": "Large integrated professional office and research and development parks.",
   "use_table_column": "OFP",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "CVP",
   "zone_name": "Civic Performance District",
   "zone_group": "Performance",
   "zone_type": "Base district",
   "zone_meaning": "Government offices with cultural and high-density residential uses between downtown and the Downtown Residential district.",
   "use_table_column": "CVP",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "IS",
   "zone_name": "Institutional District",
   "zone_group": "Other",
   "zone_type": "Base district",
   "zone_meaning": "Large government, education, healthcare and cultural campuses with offices and high-density housing.",
   "use_table_column": "IS",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "IN",
   "zone_name": "Industrial District",
   "zone_group": "Other",
   "zone_type": "Base district",
   "zone_meaning": "Manufacturing, warehousing and other industrial development.",
   "use_table_column": "IN",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "UT",
   "zone_name": "Urban Transitional District",
   "zone_group": "Other",
   "zone_type": "Base district",
   "zone_meaning": "Areas of mixed use transitioning between residential and nonresidential uses.",
   "use_table_column": "UT",
   "source_section": "Concord Code § 28-2-2"
  },
  {
   "zone_code": "FH",
   "zone_name": "Flood Hazard District",
   "zone_group": "Overlay",
   "zone_type": "Overlay district",
   "zone_meaning": "Floodplain overlay; adds rules on top of the base district.",
   "use_table_column": "",
   "source_section": "Concord Code § 28-2-2; Art. 28-3"
  },
  {
   "zone_code": "SP",
   "zone_name": "Shoreland Protection District",
   "zone_group": "Overlay",
   "zone_type": "Overlay district",
   "zone_meaning": "Shoreland overlay along protected waters.",
   "use_table_column": "",
   "source_section": "Concord Code § 28-2-2; Art. 28-3"
  },
  {
   "zone_code": "HI",
   "zone_name": "Historic District",
   "zone_group": "Overlay",
   "zone_type": "Overlay district",
   "zone_meaning": "Historic district overlay.",
   "use_table_column": "",
   "source_section": "Concord Code § 28-2-2; Art. 28-3"
  },
  {
   "zone_code": "WS",
   "zone_name": "Penacook Lake Watershed Protection District",
   "zone_group": "Overlay",
   "zone_type": "Overlay district",
   "zone_meaning": "Protects the Penacook Lake drinking-water watershed.",
   "use_table_column": "",
   "source_section": "Concord Code § 28-2-2; Art. 28-3"
  },
  {
   "zone_code": "AP",
   "zone_name": "Aquifer Protection District",
   "zone_group": "Overlay",
   "zone_type": "Overlay district",
   "zone_meaning": "Protects aquifer areas.",
   "use_table_column": "",
   "source_section": "Concord Code § 28-2-2; Art. 28-3"
  }
 ],
 "legend": [
  [
   "P",
   "Permitted",
   "Permitted by right (§ 28-2-4(a))",
   ""
  ],
  [
   "P + standards",
   "Permitted with conditions",
   "Permitted by right; development design / supplemental standards listed in the table apply (§ 28-2-4(f))",
   ""
  ],
  [
   "SE",
   "Conditional",
   "Special exception (§ 28-2-4(b))",
   "Zoning Board of Adjustment"
  ],
  [
   "CU",
   "Conditional",
   "Conditional use permit (§ 28-2-4(c))",
   "Planning Board"
  ],
  [
   "-",
   "Not permitted",
   "Dashed line = not permitted (§ 28-2-4(d))",
   ""
  ],
  [
   "(blank)",
   "Unclear",
   "Blank cell in the table",
   ""
  ],
  [
   "(unlisted use)",
   "Unclear",
   "Deputy City Manager for Development classifies the use (§ 28-2-4(e))",
   "Deputy City Manager for Development"
  ]
 ]
}
""")

# ===================== MAIN =====================

GATE = {
    'zoning_chapter_found': r'(ZONING|LAND DEVELOPMENT CODE|UNIFIED DEVELOPMENT|DEVELOPMENT CODE|ZONING REGULATIONS)',
    'zone_list_found': r'(districts established|zoning districts|map codes|district listing|classification of districts)',
    'use_list_found': r'(permitted uses|use table|table of uses|land use matrix|schedule of uses|schedule of principal uses|use chart|table of principal uses|special exceptions)',
}
POINTER = r'(published separately|available at|can be found|found here|is on file|see the city website|repealed|replaced)'

def pdf_pages(pdf):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
    return txt.split('\f')

def gate(pages):
    res = []
    for name, rx in GATE.items():
        hits = [i + 1 for i, p in enumerate(pages) if re.search(rx, p, re.I)]
        res.append((name, 'PASS' if hits else 'FAIL', f'{len(hits)} pages', hits[:5]))
    # external pointer inside a short zoning chapter
    ptr = [(i + 1, re.sub(r'\s+', ' ', p)[:400]) for i, p in enumerate(pages)
           if re.search(r'LAND DEVELOPMENT CODE|ZONING', p) and re.search(POINTER, p, re.I) and re.search(r'https?://\S+', p)]
    return res, ptr

def norm_url(u):
    return re.sub(r'\s+', '-', u.strip()).rstrip('.,;)')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True, help='path to the code PDF')
    ap.add_argument('--config', help='city config JSON (default: built-in Concord, NH config)')
    ap.add_argument('--out', default='output')
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding='utf-8')) if a.config else CONCORD_CONFIG
    os.makedirs(a.out, exist_ok=True)
    meta = {k: cfg[k] for k in ('state', 'municipality', 'type', 'county')}
    log = []
    pages = pdf_pages(a.pdf)
    if sum(len(p) for p in pages) / max(1, len(pages)) < 100:
        log.append(('text_layer', 'FAIL', 'SCANNED_PDF: run OCR first', '', '', ''))
    res, ptr = gate(pages)
    for n, r, m, hits in res:
        log.append((n, r, m, '', '', ','.join(map(str, hits))))
    ok = all(r == 'PASS' for _, r, _, _ in res)
    if ptr and not cfg.get('tables'):
        for pg, txt in ptr[:2]:
            url = (re.search(r'https?://[^\s]+(?:\s[a-z][\w-]*)?', txt) or [''])[0]
            log.append(('external_pointer', 'FAIL', 'ZONING_NOT_IN_PDF: ' + txt[:200], url, norm_url(url), str(pg)))
        ok = False
    uses = []
    if ok and cfg.get('tables'):
        for tb in cfg['tables']:
            rows, issues = parse_table(a.pdf, range(tb['pages'][0], tb['pages'][1] + 1), tb['columns'],
                                       tb['value_regex'], {**cfg.get('parser', {}), **tb.get('parser', {})})
            for i in issues[:20]:
                log.append(('parser_issue', 'WARN', str(i), '', '', ''))
            uses += to_rows(rows, tb, cfg)
    if not ok:
        print('Gate check failed; no Excel written. See run_log.csv')
    else:
        name = f"{cfg['state']}_{cfg['municipality'].replace(' ', '')}_{cfg['type'].split()[0]}_Zoning.xlsx"
        z, u = build(os.path.join(a.out, name), meta, cfg['zones'], uses, cfg['legend'], cfg['source_document'])
        validate(cfg, uses, log)
        print(f'Wrote {name}: {z} zones, {u} rows')
    with open(os.path.join(a.out, 'run_log.csv'), 'a', newline='') as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(['file', 'state', 'municipality', 'type', 'county', 'check', 'result', 'message', 'link_raw', 'link_guess', 'pages'])
        for c, r, m, l1, l2, pg in log:
            w.writerow([os.path.basename(a.pdf), meta['state'], meta['municipality'], meta['type'], meta['county'], c, r, m, l1, l2, pg])

def to_rows(rows, tb, cfg):
    out = []
    smap = cfg['symbols']
    for r in rows:
        name = re.sub(r'\s+', ' ', r['use']).strip()
        for pat, rep in cfg.get('use_name_fixes', {}).items():
            name = re.sub(pat, rep, name)
        no = ''
        if tb.get('use_number_regex'):
            m = re.match(tb['use_number_regex'], name)
            if m: no, name = m.group(1), name[m.end():].strip()
        if re.match(cfg.get('drop_use_regex', r'^$a'), name): continue
        star = name.endswith('*'); name = name.rstrip('*').strip()
        cat_raw = r['category'] or ''
        cat = tb.get('category_map', {}).get(cat_raw[:1] if tb.get('category_map_by_letter') else cat_raw, cat_raw)
        if cfg.get('category_override', {}).get(name): cat = cfg['category_override'][name]
        std = ''
        if tb.get('standards_regex'):
            std = '; '.join(dict.fromkeys(re.findall(tb['standards_regex'], r['side_text'])))
        for col in tb['columns']:
            for zone in cfg.get('column_to_zones', {}).get(col, [col]):
                s = r['cells'].get(col, '')
                if name in cfg.get('use_overrides', {}):
                    sym, perm, route, body = cfg['use_overrides'][name]
                elif s == '':
                    sym, perm, route, body = cfg['blank']
                elif s in smap:
                    sym = s + ('*' if star and s in ('P', 'C') else '')
                    perm, route, body = smap[s]
                    if perm == 'Permitted' and (star or std):
                        perm = 'Permitted with conditions'
                        route = 'Allowed by right; ' + (f'standards apply ({std})' if std else cfg.get('star_text', 'use-specific conditions apply'))
                    elif std:
                        route += f'; standards apply ({std})'
                    elif star:
                        route += '; ' + cfg.get('star_text', 'use-specific conditions apply')
                else:
                    sym, perm, route, body = s, 'Unclear', 'Unrecognized symbol', ''
                if sym not in ('-', '(blank)') and col in cfg.get('extra_route_columns', {}):
                    route += '; ' + cfg['extra_route_columns'][col]
                out.append(dict(zone_code=zone, use_category=cat, use_name=name, symbol=sym, permission=perm,
                                approval_route=route, approval_body=body,
                                source_section=tb['section'] + (f', use {r["category"][:1]}{no}' if no else '')))
    return out

def validate(cfg, uses, log):
    zl = {z['zone_code'] for z in cfg['zones']}
    zu = {u['zone_code'] for u in uses}
    miss = zu - zl
    log.append(('zone_match', 'PASS' if not miss else 'WARN', f'in rules but not zone list: {sorted(miss)}', '', '', ''))
    unc = sum(u['permission'] == 'Unclear' for u in uses)
    log.append(('unclear_rate', 'PASS' if unc <= 0.05 * max(1, len(uses)) else 'WARN', f'{unc} of {len(uses)} rows Unclear', '', '', ''))
    empty = sum(not u['permission'] for u in uses)
    log.append(('no_empty_permission', 'PASS' if not empty else 'FAIL', f'{empty} empty', '', '', ''))

if __name__ == '__main__':
    main()
