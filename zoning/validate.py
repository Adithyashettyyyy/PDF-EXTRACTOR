"""S8: validation checks appended to the run log."""

from __future__ import annotations


def validate(cfg: dict, uses: list[dict], log: list) -> None:
    zl = {z["zone_code"] for z in cfg.get("zones", [])}
    zu = {u["zone_code"] for u in uses}
    miss = zu - zl
    log.append(
        (
            "zone_match",
            "PASS" if not miss else "WARN",
            f"in rules but not zone list: {sorted(miss)}",
            "",
            "",
            "",
        )
    )
    unc = sum(u["permission"] == "Unclear" for u in uses)
    log.append(
        (
            "unclear_rate",
            "PASS" if unc <= 0.05 * max(1, len(uses)) else "WARN",
            f"{unc} of {len(uses)} rows Unclear",
            "",
            "",
            "",
        )
    )
    empty = sum(not u["permission"] for u in uses)
    log.append(
        (
            "no_empty_permission",
            "PASS" if not empty else "FAIL",
            f"{empty} empty",
            "",
            "",
            "",
        )
    )
