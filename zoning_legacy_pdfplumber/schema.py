"""Column layout shared by every city workbook.

Rows change from city to city. These headers do not.
"""

ZONE_HEADERS = [
    "state",
    "municipality",
    "type",
    "county",
    "zone_code",
    "zone_name",
    "zone_group",
    "zone_type",
    "zone_meaning",
    "use_table_column",
    "source_section",
]

MATRIX_LEAD = ["use_category", "use_name"]

PERMITTED_HEADERS = [
    "state",
    "municipality",
    "type",
    "county",
    "zone_code",
    "use_category",
    "use_name",
    "symbol",
    "permission",
    "approval_route",
    "approval_body",
    "source_section",
]

LEGEND_HEADERS = ["symbol", "permission", "meaning", "approved_by"]

RUN_LOG_HEADERS = [
    "file",
    "state",
    "municipality",
    "type",
    "county",
    "check",
    "result",
    "message",
    "link_raw",
    "link_guess",
    "pages",
]

PERMISSION_COLORS = {
    "Permitted": "C6EFCE",
    "Permitted with conditions": "E2F0D9",
    "Conditional": "FFEB9C",
    "Temporary": "DDEBF7",
    "Not permitted": "F2F2F2",
    "Unclear": "F8CBAD",
}

PERMISSIONS = (
    "Permitted",
    "Permitted with conditions",
    "Conditional",
    "Temporary",
    "Not permitted",
    "Unclear",
)

SHEET_WIDTHS = {
    "Zones": [12, 18, 12, 16, 14, 28, 18, 18, 55, 18, 36],
    "Use Matrix": [22, 42],
    "Permitted Uses": [12, 18, 12, 16, 14, 22, 42, 14, 28, 42, 28, 36],
    "Legend": [18, 28, 70, 32],
    "Review": [36, 10, 18, 12, 16, 28, 12, 88, 28],
    "Pages": [12, 28, 110],
}
