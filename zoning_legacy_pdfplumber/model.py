"""Records passed from one step of the pipeline to the next."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Check:
    check: str
    result: str
    message: str
    link_raw: str = ""
    link_guess: str = ""
    pages: str = ""


@dataclass
class SourceInfo:
    publication: str = ""
    supplement: str = ""
    current_through: str = ""

    def line(self) -> str:
        return ", ".join(
            part for part in (self.publication, self.supplement, self.current_through) if part
        )


@dataclass
class Zone:
    zone_code: str
    zone_name: str = ""
    zone_group: str = ""
    zone_type: str = "Base district"
    zone_meaning: str = ""
    use_table_column: str = ""
    source_section: str = ""
    page: int | None = None


@dataclass
class LegendEntry:
    symbol: str
    permission: str
    meaning: str
    approved_by: str = ""


@dataclass
class UnlistedRule:
    quote: str = ""
    page: int | None = None
    missing_uses_are: str = "Unclear"
    blank_is_prohibited: bool = False


@dataclass
class UseRow:
    zone_code: str
    use_category: str
    use_name: str
    symbol: str
    permission: str = ""
    approval_route: str = ""
    approval_body: str = ""
    source_section: str = ""
    page: int | None = None
    column_header: str = ""


@dataclass
class ParseMeta:
    rotated: bool = False
    pages: list[int] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)
    discovered: list[tuple[str, int, str]] = field(default_factory=list)


@dataclass
class GateResult:
    status: str
    stop: bool
    checks: list[Check]
    source: SourceInfo
    zoning_pages: list[int]
    use_pages: list[int]
    pointer_pages: list[int]
