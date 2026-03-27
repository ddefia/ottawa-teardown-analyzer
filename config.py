"""
Ottawa Tear-Down Analyzer — Configuration & Constants
"""
import os
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
OBSIDIAN_VAULT = "/Users/anthonybassi/Downloads/home/Companies/JBPA/Real Estate"
OUTPUT_JSON = os.path.join(os.path.dirname(__file__), "results.json")

# ── API Endpoints ──────────────────────────────────────────────────────────
REALTOR_CA_SEARCH = "https://api2.realtor.ca/Listing.svc/PropertySearch_Post"
REALTOR_CA_DETAILS = "https://api2.realtor.ca/Listing.svc/PropertyDetails"

ZONING_QUERY_URL = (
    "https://maps.ottawa.ca/arcgis/rest/services/Zoning/MapServer/3/query"
)
GEOCODER_URL = (
    "https://maps.ottawa.ca/arcgis/rest/services/"
    "addressLocator/GeocodeServer/findAddressCandidates"
)

# ── Ottawa Bounding Box (WGS-84) ──────────────────────────────────────────
OTTAWA_BOUNDS = {
    "lat_min": 45.2000,
    "lat_max": 45.5600,
    "lon_min": -76.0500,
    "lon_max": -75.3500,
}

# ── Scraper Settings ──────────────────────────────────────────────────────
RECORDS_PER_PAGE = 200
REQUEST_DELAY_S = 1.5          # seconds between paginated requests
MAX_PAGES = 25                 # safety cap
MIN_LOT_SQFT = 3000

# Keywords that signal exclusion
CONDO_KEYWORDS = [
    "condo", "condominium", "strata", "apartment unit", "penthouse",
    "unit #", "suite #", "apt.", "apt ",
]
PROTECTED_KEYWORDS = [
    "greenbelt", "ncc ", "national capital commission",
    "conservation area", "environmental protection",
]

# ── Ottawa LRT Stations (lat, lon) ────────────────────────────────────────
# Confederation Line + Trillium Line stations
LRT_STATIONS = [
    (45.3546, -75.7321),  # Tunney's Pasture
    (45.3576, -75.7221),  # Bayview
    (45.3607, -75.7138),  # Pimisi
    (45.3650, -75.7068),  # Lyon
    (45.3716, -75.6964),  # Parliament
    (45.3766, -75.6880),  # Rideau
    (45.3834, -75.6808),  # uOttawa
    (45.3903, -75.6706),  # Lees
    (45.3965, -75.6619),  # Hurdman
    (45.4060, -75.6463),  # Tremblay
    (45.4156, -75.6357),  # St-Laurent
    (45.4213, -75.6175),  # Cyrville
    (45.4286, -75.5976),  # Blair
    (45.4383, -75.5768),  # Trim (future)
    (45.3471, -75.7429),  # Dominion
    (45.3421, -75.7541),  # Westboro
    (45.3358, -75.7676),  # Cleary
    (45.3310, -75.7804),  # New Orchard
    (45.3264, -75.7898),  # Queensview
    (45.3208, -75.8042),  # Iris
    (45.3147, -75.8185),  # Pinecrest
    (45.3109, -75.8320),  # Bayshore
    (45.3064, -75.8465),  # Baseline (ext)
    (45.3966, -75.6264),  # Confederation (Trillium)
    (45.3858, -75.6260),  # Carleton
    (45.3715, -75.6255),  # Carling
    (45.3560, -75.6246),  # Mooney's Bay
    (45.3430, -75.6239),  # Greenboro
    (45.3306, -75.6233),  # South Keys
    (45.3200, -75.6228),  # Leitrim
    (45.4526, -75.5140),  # Moodie
    (45.3980, -75.6620),  # Hurdman (Trillium transfer)
]

# ── Major Arterials (simplified bounding corridors) ───────────────────────
# Each entry: (name, lat_min, lat_max, lon_min, lon_max)
ARTERIAL_CORRIDORS = [
    ("Bank St", 45.34, 45.42, -75.695, -75.685),
    ("Rideau St", 45.425, 45.435, -75.700, -75.670),
    ("Montreal Rd", 45.435, 45.455, -75.670, -75.590),
    ("Carling Ave", 45.370, 45.385, -75.770, -75.660),
    ("Bronson Ave", 45.370, 45.415, -75.700, -75.690),
    ("Merivale Rd", 45.310, 45.370, -75.735, -75.720),
    ("St Laurent Blvd", 45.380, 45.450, -75.645, -75.630),
    ("Baseline Rd", 45.345, 45.360, -75.800, -75.680),
    ("Innes Rd", 45.430, 45.465, -75.600, -75.470),
    ("Walkley Rd", 45.370, 45.385, -75.690, -75.600),
    ("Somerset St", 45.413, 45.420, -75.720, -75.685),
    ("Gladstone Ave", 45.408, 45.415, -75.720, -75.685),
    ("Scott St", 45.390, 45.400, -75.740, -75.700),
    ("Richmond Rd", 45.385, 45.395, -75.770, -75.740),
]

# ── Intensification Corridors (Official Plan 2022) ────────────────────────
INTENSIFICATION_CORRIDORS = [
    ("Bank St Corridor", 45.34, 45.42, -75.700, -75.680),
    ("Carling Ave Corridor", 45.370, 45.390, -75.770, -75.660),
    ("Montreal Rd Corridor", 45.435, 45.460, -75.670, -75.590),
    ("St Laurent Blvd Corridor", 45.380, 45.450, -75.650, -75.625),
    ("Rideau-Vanier", 45.425, 45.445, -75.695, -75.665),
    ("Merivale Rd Corridor", 45.310, 45.370, -75.740, -75.715),
    ("Richmond-Westboro", 45.380, 45.400, -75.775, -75.730),
]

# ── Zoning Parameters Lookup ─────────────────────────────────────────────
# Source: Ottawa Bylaw 2008-250 (consolidated)
# Keys: zone prefix → {max_height_m, max_fsi, setback_front_m, setback_rear_m, setback_side_m}
ZONING_TABLE = {
    "R1": {"max_height_m": 11.0, "max_fsi": 0.50, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 1.5, "desc": "Detached residential"},
    "R2": {"max_height_m": 11.0, "max_fsi": 0.50, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 1.2, "desc": "Semi-detached"},
    "R3": {"max_height_m": 11.0, "max_fsi": 0.75, "setback_front_m": 3.0, "setback_rear_m": 7.5, "setback_side_m": 1.5, "desc": "Converted/triplex"},
    "R4": {"max_height_m": 14.5, "max_fsi": 1.50, "setback_front_m": 3.0, "setback_rear_m": 7.5, "setback_side_m": 1.5, "desc": "Low-rise apartment"},
    "R5": {"max_height_m": 20.0, "max_fsi": 2.50, "setback_front_m": 3.0, "setback_rear_m": 7.5, "setback_side_m": 3.0, "desc": "Mid-rise residential"},
    "AM": {"max_height_m": 15.0, "max_fsi": 2.00, "setback_front_m": 0.0, "setback_rear_m": 7.5, "setback_side_m": 0.0, "desc": "Arterial mainstreet"},
    "GM": {"max_height_m": 15.0, "max_fsi": 2.00, "setback_front_m": 0.0, "setback_rear_m": 7.5, "setback_side_m": 0.0, "desc": "General mixed use"},
    "TD": {"max_height_m": 30.0, "max_fsi": 2.50, "setback_front_m": 3.0, "setback_rear_m": 7.5, "setback_side_m": 3.0, "desc": "Transit-oriented development"},
    "TM": {"max_height_m": 15.0, "max_fsi": 2.00, "setback_front_m": 0.0, "setback_rear_m": 7.5, "setback_side_m": 0.0, "desc": "Traditional mainstreet"},
    "MC": {"max_height_m": 30.0, "max_fsi": 3.00, "setback_front_m": 0.0, "setback_rear_m": 7.5, "setback_side_m": 0.0, "desc": "Mixed-use centre"},
    "MD": {"max_height_m": 30.0, "max_fsi": 3.00, "setback_front_m": 0.0, "setback_rear_m": 7.5, "setback_side_m": 0.0, "desc": "Mixed-use downtown"},
    "LC": {"max_height_m": 15.0, "max_fsi": 1.50, "setback_front_m": 3.0, "setback_rear_m": 7.5, "setback_side_m": 1.5, "desc": "Local commercial"},
    "I1": {"max_height_m": 20.0, "max_fsi": 1.00, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 3.0, "desc": "Minor institutional"},
    "I2": {"max_height_m": 30.0, "max_fsi": 2.00, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 3.0, "desc": "Major institutional"},
    "IL": {"max_height_m": 15.0, "max_fsi": 0.50, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 3.0, "desc": "Light industrial"},
    "IG": {"max_height_m": 20.0, "max_fsi": 0.75, "setback_front_m": 6.0, "setback_rear_m": 7.5, "setback_side_m": 6.0, "desc": "General industrial"},
    "IH": {"max_height_m": 20.0, "max_fsi": 0.50, "setback_front_m": 10.0, "setback_rear_m": 10.0, "setback_side_m": 6.0, "desc": "Heavy industrial"},
    "AG": {"max_height_m": 11.0, "max_fsi": 0.20, "setback_front_m": 10.0, "setback_rear_m": 10.0, "setback_side_m": 5.0, "desc": "Agricultural"},
}

# Rezone upgrade path: current zone → likely upgraded zone
REZONE_UPGRADE = {
    "R1": "R4",
    "R2": "R4",
    "R3": "R5",
    "R4": "R5",
    "R5": "AM",
    "AM": "GM",
    "TM": "AM",
    "LC": "AM",
    "IL": "GM",
    "IG": "GM",
}

# ── Scoring Thresholds ────────────────────────────────────────────────────
SCORE_MINIMUM_FOR_OBSIDIAN = 50
VALUE_PER_POTENTIAL_UNIT = 250_000  # conservative Ottawa avg

# ── Run Info ──────────────────────────────────────────────────────────────
RUN_TIMESTAMP = datetime.utcnow().isoformat(timespec="seconds") + "Z"
