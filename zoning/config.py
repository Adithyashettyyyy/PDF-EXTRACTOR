"""S5: load city configs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"


def load_config(path: str | Path | None = None) -> dict:
    """Load a city JSON config. None → empty gate-only config (no tables)."""
    if path is None:
        return {
            "state": "",
            "municipality": "",
            "type": "",
            "county": "",
            "source_document": "",
            "parser": {},
            "tables": [],
            "symbols": {},
            "blank": ["(blank)", "Unclear", "Cell is blank in the table", ""],
            "zones": [],
            "legend": [],
        }
    path = Path(path)
    if not path.is_file():
        alt = CONFIG_DIR / path.name
        if alt.is_file():
            path = alt
    with open(path, encoding="utf-8") as f:
        return json.load(f)
