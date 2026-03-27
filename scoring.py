"""
Ottawa Tear-Down Analyzer — Scoring Engine (0-100)

Scoring breakdown:
  Zoning    0-30   Current zone quality + rezone likelihood
  Lot       0-20   Lot size, shape, corner bonus
  Location  0-20   LRT proximity, arterials, intensification
  Price     0-15   Price per potential unit
  Market    0-15   Market conditions (simplified for v1)
"""
import math
import logging
from config import LRT_STATIONS, ARTERIAL_CORRIDORS, INTENSIFICATION_CORRIDORS

log = logging.getLogger(__name__)


def score_listing(listing: dict) -> dict:
    """Calculate the composite score (0-100) for a listing.
    Adds score fields directly to the listing dict."""
    s_zoning = _score_zoning(listing)
    s_lot = _score_lot(listing)
    s_location = _score_location(listing)
    s_price = _score_price(listing)
    s_market = _score_market(listing)

    total = s_zoning + s_lot + s_location + s_price + s_market

    listing["score"] = min(100, total)
    listing["score_zoning"] = s_zoning
    listing["score_lot"] = s_lot
    listing["score_location"] = s_location
    listing["score_price"] = s_price
    listing["score_market"] = s_market

    return listing


def _score_zoning(listing: dict) -> int:
    """Zoning score (0-30)."""
    zone = (listing.get("zone_main") or "").upper()
    likelihood = (listing.get("rezone_likelihood") or "").upper()
    score = 0

    # Base score from current zone
    zone_scores = {
        "R5": 20, "AM": 22, "GM": 22, "TD": 25, "MC": 25, "MD": 25,
        "R4": 15, "TM": 18,
        "R3": 10, "LC": 12,
        "R2": 8, "R1": 5,
        "IL": 12, "IG": 10, "IH": 8,  # Industrial with conversion potential
    }
    score = zone_scores.get(zone, 5)

    # Rezone likelihood bonus
    if likelihood == "HIGH":
        score += 8
    elif likelihood == "MEDIUM":
        score += 4
    elif likelihood == "LOW":
        score += 1

    # Already a high-density zone (R5+, AM, GM, TD) → max out
    if zone in ("TD", "MC", "MD"):
        score = max(score, 25)

    return min(30, score)


def _score_lot(listing: dict) -> int:
    """Lot score (0-20)."""
    lot_sqft = listing.get("lot_size_sqft") or 0
    frontage = listing.get("lot_frontage_ft") or 0
    depth = listing.get("lot_depth_ft") or 0
    score = 0

    # Size brackets
    if lot_sqft >= 20000:
        score = 20
    elif lot_sqft >= 10000:
        score = 15
    elif lot_sqft >= 5000:
        score = 10
    elif lot_sqft >= 3000:
        score = 5

    # Corner lot heuristic: if frontage is unusually wide relative to depth
    # (typical lots are deeper than wide, corner lots are wider)
    if frontage > 0 and depth > 0:
        ratio = frontage / depth
        if ratio > 0.7:  # Wider than typical → likely corner
            score += 3
            listing["_is_corner_lot"] = True
        # Irregular shape penalty: very narrow or very deep
        if ratio < 0.15 or ratio > 3.0:
            score -= 3

    # Vacant land bonus — no demolition cost
    prop_type = (listing.get("property_type") or "").lower()
    if "vacant" in prop_type or "land" in prop_type:
        score += 2

    return max(0, min(20, score))


def _score_location(listing: dict) -> int:
    """Location score (0-20)."""
    lat = listing.get("latitude") or 0
    lon = listing.get("longitude") or 0
    score = 0

    if lat == 0 or lon == 0:
        return 5  # Unknown location gets neutral score

    # LRT proximity
    min_dist = float("inf")
    for slat, slon in LRT_STATIONS:
        d = _haversine(lat, lon, slat, slon)
        if d < min_dist:
            min_dist = d

    if min_dist < 400:
        score += 20
    elif min_dist < 800:
        score += 15
    elif min_dist < 1200:
        score += 8

    # Arterial road
    for name, lat_min, lat_max, lon_min, lon_max in ARTERIAL_CORRIDORS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            score += 5
            break

    # Intensification corridor
    for name, lat_min, lat_max, lon_min, lon_max in INTENSIFICATION_CORRIDORS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            score += 5
            break

    # Penalties
    desc = (listing.get("description") or "").lower()
    neighbourhood = (listing.get("neighbourhood") or "").lower()
    penalty_keywords = ["flood", "industrial area", "heritage district", "heritage overlay"]
    if any(kw in desc or kw in neighbourhood for kw in penalty_keywords):
        score -= 5

    return max(0, min(20, score))


def _score_price(listing: dict) -> int:
    """Price score (0-15). Based on price per potential unit."""
    potential_units = listing.get("potential_units") or listing.get("estimated_units") or 0
    price = listing.get("price") or 0

    if potential_units <= 0 or price <= 0:
        return 5  # Unknown → neutral

    ppu = price / potential_units

    if ppu < 100_000:
        return 15
    elif ppu < 150_000:
        return 12
    elif ppu < 200_000:
        return 8
    elif ppu < 250_000:
        return 4
    else:
        return 0


def _score_market(listing: dict) -> int:
    """Market score (0-15).

    v1: simplified static estimates based on Ottawa market conditions.
    TODO: Integrate live data from Ottawa DevApps permits API and CMHC stats.
    """
    score = 0
    neighbourhood = (listing.get("neighbourhood") or "").lower()
    zone = (listing.get("zone_main") or "").upper()

    # Ottawa land market is generally strong (2024-2026 trend)
    score += 4  # Base: market conditions are favorable

    # High-growth neighbourhoods (based on Ottawa building permit data 2023-2025)
    high_growth = [
        "barrhaven", "kanata", "orleans", "stittsville", "riverside south",
        "findlay creek", "half moon bay", "leitrim", "manotick",
    ]
    intensifying = [
        "westboro", "hintonburg", "mechanicsville", "lebreton",
        "little italy", "centretown", "sandy hill", "old ottawa south",
        "old ottawa east", "vanier", "overbrook", "alta vista",
        "carlington", "civic hospital", "gladstone",
    ]

    if any(n in neighbourhood for n in intensifying):
        score += 6  # Active intensification = very strong market
    elif any(n in neighbourhood for n in high_growth):
        score += 4  # Suburban growth areas
    else:
        score += 2  # Base Ottawa growth

    # Zones with active development tend to have better permit approvals
    if zone in ("R4", "R5", "AM", "GM", "TD", "MC", "MD"):
        score += 3

    # Low vacancy assumption for Ottawa (sub-2% for years)
    score += 2

    return min(15, score)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two points in metres."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
