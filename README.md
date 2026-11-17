# PDF extraction

One city code PDF goes in. The script reads only that file. It writes `run_log.csv` every time. It writes the four-sheet zoning workbook only when that PDF actually states the uses.

Nothing from a previous city is reused: zone codes, use names, symbols, and meanings all come from the PDF being read.

## Layout

```
extract_zoning.py     command you run
zoning/
  pipeline.py         runs the steps in order
  reader.py           PDF text, word positions, city name
  gate.py             ordinance version and the four checks
  zones.py            district list
  legend.py           symbols and the unlisted-use rule
  tables.py           grid and rotated use tables
  lists.py            per-district use lists
  claude.py           optional Claude pass when ANTHROPIC_API_KEY is set
  normalize.py        duplicate use names inside one city
  validate.py         the checks
  workbook.py         Excel and run_log.csv
  schema.py           sheet names and columns
input/                put the code PDF here
output/               workbook and run_log.csv
```

## Run

Put the code PDF in `input`, then from this folder:

```powershell
python extract_zoning.py
```

Every `.pdf` in `input` is read. A passing PDF writes `output\<STATE>_<Name>_<Type>_Zoning.xlsx`. Every run appends checks to `output\run_log.csv`. If zoning is not in the PDF, no workbook is written.

Optional labels, when you pass one PDF and the cover page does not state them:

```powershell
python extract_zoning.py "C:\path\to\city.pdf" --state NH --municipality Keene --type City --county Cheshire
```

Exit code 2 means the city was flagged. The use table was not in that PDF, so no workbook was written. Open `output\run_log.csv`.

## Workbook sheets

Written only after a pass:

| Sheet | One row is |
| --- | --- |
| Zones | one district |
| Use Matrix | one use, with a column per zone |
| Permitted Uses | one use in one zone |
| Legend | one symbol from that city |
