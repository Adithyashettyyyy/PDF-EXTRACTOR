"""Words the scanner looks for. They are search hints, not a city template."""

USE_PHRASES = (
    "permitted use",
    "permitted uses",
    "use table",
    "table of uses",
    "table of permitted",
    "principal permitted",
    "principal uses",
    "uses permitted",
    "schedule of uses",
    "allowed uses",
)

ZONING_PHRASES = (
    "zoning",
    "land development code",
    "zoning ordinance",
    "zoning district",
    "zoning code",
)

ZONING_CONTEXT = (
    "zoning",
    "land development",
    "zoning district",
    "zone district",
    "special exception",
    "conditional use",
)

EXTERNAL_PHRASES = (
    "can be found here",
    "can be found at",
    "user's attention is directed",
    "replaced it with",
)

CHAPTER_PHRASES = (
    "zoning",
    "land development code",
    "unified development",
    "development code",
    "zoning regulations",
    "zoning and land use",
)

ZONE_LIST_PHRASES = (
    "districts established",
    "zoning districts",
    "districts and map codes",
    "district listing",
    "classification of districts",
    "table 2-1",
)

USE_LIST_PHRASES = USE_PHRASES + (
    "land use matrix",
    "schedule of principal uses",
    "use chart",
    "special exceptions",
    "special exception",
)

POINTER_PHRASES = (
    "published separately",
    "adopted separately",
    "available at",
    "can be found",
    "found here",
    "is on file",
    "see the city website",
    "city website",
    "user's attention is directed",
)

PUBLICATION_NAMES = (
    "Land Development Code",
    "Unified Development Code",
    "Unified Development Ordinance",
    "Zoning Ordinance",
    "Code of Ordinances",
)

APPROVAL_BODIES = (
    "Zoning Board of Adjustment",
    "Board of Zoning Appeals",
    "Board of Adjustment",
    "Planning Commission",
    "Planning Board",
    "City Council",
    "Zoning Administrator",
    "Director",
)

STATE_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}
