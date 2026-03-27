"""
Ottawa Tear-Down Analyzer — Smart Development Feasibility Calculator

This module determines what COULD be built on a property if torn down/rebuilt,
considering current zoning, rezone potential, and Ottawa-specific development rules.

The calculator is "smart" in several ways:
1. Understands zone-specific nuances (AM zones have 0 setbacks, R zones don't)
2. Estimates rezone potential using transit proximity, corridor analysis, and adjacency
3. Handles missing data gracefully with conservative fallbacks
4. Applies Ottawa-specific rules (angular plane, rear yard landscaping, etc.)
5. Calculates both current-zoning and best-case-rezone scenarios
"""
import math
import logging
from typing import Optional

from config import (
    ZONING_TABLE,
    REZONE_UPGRADE,
    LRT_STATIONS,
    ARTERIAL_CORRIDORS,
    INTENSIFICATION_CORRIDORS,
    VALUE_PER_POTENTIAL_UNIT,
)

log = logging.getLogger(__name__)

M_TO_FT = 3.28084
FT_TO_M = 0.3048

# ── Ottawa-specific development constants ────────────────────────────────
COMMON_AREA_FACTOR = 0.85       # 85% of GFA is usable (corridors, stairs, mechanical)
AVG_UNIT_SIZE_SQFT = 750        # Average 1BR unit in Ottawa
PARKING_REDUCTION_FACTOR = 0.90 # ~10% of ground floor lost to parking access in R4+
ANGULAR_PLANE_ANGLE_DEG = 45    # Ottawa's 45° angular plane from rear lot line
MIN_REAR_AMENITY_M = 6.0        # Practical min rear amenity space beyond setback


def calculate_feasibility(listing: dict) -> dict:
    """
    Calculate development feasibility for a listing.
    Adds computed fields directly to the listing dict.
    """
    lot_sqft = listing.get("lot_size_sqft") or 0
    frontage = listing.get("lot_frontage_ft") or 0
    depth = listing.get("lot_depth_ft") or 0
    price = listing.get("price") or 0
    zone_main = (listing.get("zone_main") or "").upper()

    # Get zoning params (already enriched by zoning.py, but ensure defaults)
    max_height = listing.get("max_height_m")
    max_fsi = listing.get("max_fsi")
    front_setback = listing.get("setback_front_m")
    rear_setback = listing.get("setback_rear_m")
    side_setback = listing.get("setback_side_m")

    # ── Infer missing lot dimensions ──────────────────────────────────
    if lot_sqft and frontage and not depth:
        depth = lot_sqft / frontage
        listing["lot_depth_ft"] = round(depth, 1)
    elif lot_sqft and depth and not frontage:
        frontage = lot_sqft / depth
        listing["lot_frontage_ft"] = round(frontage, 1)
    elif frontage and depth and not lot_sqft:
        lot_sqft = frontage * depth
        listing["lot_size_sqft"] = round(lot_sqft, 1)

    # ── Estimate missing lot size from building size ──────────────────
    if not lot_sqft and listing.get("building_sqft"):
        # Conservative: assume building covers ~40% of lot
        lot_sqft = listing["building_sqft"] / 0.4
        listing["lot_size_sqft"] = round(lot_sqft, 1)
        log.debug(f"Estimated lot size {lot_sqft:.0f} sqft from building size")

    # ── Fall back to zone defaults if zoning lookup missed ────────────
    if zone_main and zone_main in ZONING_TABLE:
        zt = ZONING_TABLE[zone_main]
        if max_height is None:
            max_height = zt["max_height_m"]
        if max_fsi is None:
            max_fsi = zt["max_fsi"]
        if front_setback is None:
            front_setback = zt["setback_front_m"]
        if rear_setback is None:
            rear_setback = zt["setback_rear_m"]
        if side_setback is None:
            side_setback = zt["setback_side_m"]

    # Default to R3 assumptions if we have nothing
    if max_height is None:
        max_height = 11.0
    if max_fsi is None:
        max_fsi = 0.75
    if front_setback is None:
        front_setback = 3.0
    if rear_setback is None:
        rear_setback = 7.5
    if side_setback is None:
        side_setback = 1.5

    # ── BUILDABLE ENVELOPE ────────────────────────────────────────────
    if frontage > 0 and depth > 0:
        buildable_width = max(0, frontage - 2 * side_setback * M_TO_FT)
        buildable_depth = max(0, depth - front_setback * M_TO_FT - rear_setback * M_TO_FT)
        buildable_area_sqft = buildable_width * buildable_depth
    elif lot_sqft > 0:
        # Estimate: assume roughly square-ish lot with setbacks eating ~40%
        setback_ratio = _estimate_setback_ratio(front_setback, rear_setback, side_setback)
        buildable_area_sqft = lot_sqft * setback_ratio
    else:
        buildable_area_sqft = 0

    # ── ANGULAR PLANE CONSTRAINT ──────────────────────────────────────
    # In R4+ zones, Ottawa applies a 45° angular plane from the rear lot line
    # This limits actual building height at the rear
    effective_height = max_height
    if depth > 0 and zone_main in ("R4", "R5", "AM", "GM", "TD", "MC", "MD"):
        rear_available_m = (depth * FT_TO_M) - rear_setback
        angular_max_height = rear_available_m * math.tan(math.radians(ANGULAR_PLANE_ANGLE_DEG))
        if angular_max_height < max_height:
            # Average the angular constraint with max height
            # (front of building can be taller, back is constrained)
            effective_height = (max_height + min(max_height, angular_max_height)) / 2
            log.debug(f"Angular plane limits effective height to {effective_height:.1f}m")

    # ── FLOOR CALCULATION ─────────────────────────────────────────────
    floor_to_floor_m = 3.0  # Standard residential floor-to-floor
    if zone_main in ("AM", "GM", "MC", "MD", "TM"):
        floor_to_floor_m = 3.5  # Commercial ground floor is taller
    estimated_floors = max(1, math.floor(effective_height / floor_to_floor_m))

    # ── GFA CALCULATION ───────────────────────────────────────────────
    max_gfa_sqft = lot_sqft * max_fsi if lot_sqft > 0 else 0
    floor_plate = buildable_area_sqft
    raw_gfa = floor_plate * estimated_floors
    actual_gfa = min(max_gfa_sqft, raw_gfa) if max_gfa_sqft > 0 else raw_gfa

    # ── UNIT ESTIMATION ───────────────────────────────────────────────
    usable_gfa = actual_gfa * COMMON_AREA_FACTOR
    # Ground floor parking reduction for mid-rise+
    if estimated_floors >= 4:
        usable_gfa -= floor_plate * (1 - PARKING_REDUCTION_FACTOR)

    estimated_units = max(1, math.floor(usable_gfa / AVG_UNIT_SIZE_SQFT)) if usable_gfa > 0 else 0

    # Sanity check: at least 1 unit if there's buildable area
    if buildable_area_sqft > 500 and estimated_units == 0:
        estimated_units = 1

    # ── PRICE METRICS ─────────────────────────────────────────────────
    price_per_unit = round(price / estimated_units) if estimated_units > 0 and price > 0 else None
    price_per_buildable = round(price / buildable_area_sqft, 2) if buildable_area_sqft > 0 and price > 0 else None

    # ── REZONE POTENTIAL ──────────────────────────────────────────────
    rezone = _assess_rezone_potential(listing, zone_main)

    # ── POTENTIAL (REZONE) SCENARIO ───────────────────────────────────
    potential_zone = rezone["potential_zone"]
    potential_params = ZONING_TABLE.get(potential_zone, {})
    potential_height = potential_params.get("max_height_m", max_height)
    potential_fsi = potential_params.get("max_fsi", max_fsi)

    # Override with rezone-specific height if zone code suggests it
    if rezone.get("potential_height_override"):
        potential_height = rezone["potential_height_override"]

    potential_gfa = lot_sqft * potential_fsi if lot_sqft > 0 else 0
    potential_floors = max(1, math.floor(potential_height / floor_to_floor_m))
    potential_raw_gfa = floor_plate * potential_floors
    potential_actual_gfa = min(potential_gfa, potential_raw_gfa) if potential_gfa > 0 else potential_raw_gfa
    potential_usable = potential_actual_gfa * COMMON_AREA_FACTOR
    if potential_floors >= 4:
        potential_usable -= floor_plate * (1 - PARKING_REDUCTION_FACTOR)
    potential_units = max(1, math.floor(potential_usable / AVG_UNIT_SIZE_SQFT)) if potential_usable > 0 else 0

    # ── UPSIDE CALCULATION ────────────────────────────────────────────
    potential_value = potential_units * VALUE_PER_POTENTIAL_UNIT
    spread = potential_value - price if price > 0 else 0

    # ── Store everything ──────────────────────────────────────────────
    listing["buildable_area_sqft"] = round(buildable_area_sqft, 1)
    listing["max_gfa_sqft"] = round(max_gfa_sqft, 1)
    listing["estimated_floors"] = estimated_floors
    listing["estimated_units"] = estimated_units
    listing["price_per_unit"] = price_per_unit
    listing["price_per_buildable_sqft"] = price_per_buildable
    listing["potential_zone"] = potential_zone
    listing["potential_height_m"] = potential_height
    listing["potential_fsi"] = potential_fsi
    listing["potential_units"] = potential_units
    listing["potential_value"] = round(potential_value)
    listing["rezone_likelihood"] = rezone["likelihood"]
    listing["rezone_reasoning"] = rezone["reasoning"]
    listing["spread"] = round(spread)

    # Ensure zoning params are stored
    listing["max_height_m"] = max_height
    listing["max_fsi"] = max_fsi
    listing["setback_front_m"] = front_setback
    listing["setback_rear_m"] = rear_setback
    listing["setback_side_m"] = side_setback

    return listing


def _estimate_setback_ratio(front: float, rear: float, side: float) -> float:
    """Estimate what fraction of a lot is buildable given setbacks.
    Assumes a typical ~50ft × 100ft lot for the ratio calculation."""
    typical_w = 50 * FT_TO_M
    typical_d = 100 * FT_TO_M
    usable_w = max(0, typical_w - 2 * side)
    usable_d = max(0, typical_d - front - rear)
    total = typical_w * typical_d
    if total == 0:
        return 0.5
    return (usable_w * usable_d) / total


def _assess_rezone_potential(listing: dict, zone_main: str) -> dict:
    """Assess the likelihood and potential outcome of rezoning.

    Uses a multi-factor analysis:
    1. Transit proximity (LRT distance)
    2. Arterial road location
    3. Intensification corridor designation
    4. Current zone (higher base zones have more upside)
    5. Lot size (larger lots are more attractive for rezoning)
    6. Description clues (existing rezoning language)
    """
    lat = listing.get("latitude") or 0
    lon = listing.get("longitude") or 0
    lot_sqft = listing.get("lot_size_sqft") or 0
    desc = (listing.get("description") or "").lower()

    factors = []
    score = 0  # 0-100 internal rezone confidence

    # ── Factor 1: LRT Proximity ───────────────────────────────────────
    lrt_dist = _min_distance_to_stations(lat, lon)
    if lrt_dist < 400:
        score += 35
        factors.append(f"Within 400m of LRT ({lrt_dist:.0f}m)")
    elif lrt_dist < 800:
        score += 25
        factors.append(f"Within 800m of LRT ({lrt_dist:.0f}m)")
    elif lrt_dist < 1200:
        score += 10
        factors.append(f"Within 1.2km of LRT ({lrt_dist:.0f}m)")

    # ── Factor 2: Arterial Road ───────────────────────────────────────
    on_arterial = _is_in_corridor(lat, lon, ARTERIAL_CORRIDORS)
    if on_arterial:
        score += 15
        factors.append(f"On arterial: {on_arterial}")

    # ── Factor 3: Intensification Corridor ────────────────────────────
    in_intensification = _is_in_corridor(lat, lon, INTENSIFICATION_CORRIDORS)
    if in_intensification:
        score += 20
        factors.append(f"In intensification corridor: {in_intensification}")

    # ── Factor 4: Current Zone Upside ─────────────────────────────────
    if zone_main in ("R1", "R2"):
        score += 5  # Low density → easy case for upzoning
        factors.append("Low-density zone with upzoning potential")
    elif zone_main in ("R3", "R4"):
        score += 10  # Already medium density, one step up is common
        factors.append("Medium-density zone, incremental upzone likely")
    elif zone_main in ("IL", "IG"):
        score += 15  # Industrial-to-residential conversions are hot
        factors.append("Industrial zone with residential conversion potential")

    # ── Factor 5: Lot Size ────────────────────────────────────────────
    if lot_sqft >= 20000:
        score += 10
        factors.append("Large lot (>20K sqft) — attractive for assembly")
    elif lot_sqft >= 10000:
        score += 5
        factors.append("Good lot size (>10K sqft)")

    # ── Factor 6: Description Clues ───────────────────────────────────
    rezone_keywords = ["rezone", "re-zone", "rezoning", "official plan", "site plan",
                       "development application", "minor variance", "zba"]
    if any(kw in desc for kw in rezone_keywords):
        score += 15
        factors.append("Listing mentions zoning/development applications")

    # ── Determine potential zone ──────────────────────────────────────
    potential_zone = zone_main
    potential_height_override = None

    if lrt_dist < 400:
        potential_zone = "TD"
        potential_height_override = 30.0
    elif lrt_dist < 800:
        if zone_main in ("R1", "R2", "R3"):
            potential_zone = "R5"
        elif zone_main in ("R4",):
            potential_zone = "AM"
        elif on_arterial:
            potential_zone = "AM"
        else:
            potential_zone = REZONE_UPGRADE.get(zone_main, zone_main)
    elif on_arterial or in_intensification:
        if zone_main in ("R1", "R2", "R3", "R4"):
            potential_zone = "AM"
        else:
            potential_zone = REZONE_UPGRADE.get(zone_main, zone_main)
    else:
        potential_zone = REZONE_UPGRADE.get(zone_main, zone_main)

    # ── Classify likelihood ───────────────────────────────────────────
    if score >= 50:
        likelihood = "HIGH"
    elif score >= 25:
        likelihood = "MEDIUM"
    else:
        likelihood = "LOW"

    return {
        "potential_zone": potential_zone,
        "potential_height_override": potential_height_override,
        "likelihood": likelihood,
        "score": score,
        "reasoning": "; ".join(factors) if factors else "No strong rezone indicators",
    }


def _min_distance_to_stations(lat: float, lon: float) -> float:
    """Calculate distance to the nearest LRT station in metres.
    Uses the Haversine formula."""
    if lat == 0 or lon == 0:
        return 99999

    min_dist = float("inf")
    for slat, slon in LRT_STATIONS:
        d = _haversine(lat, lon, slat, slon)
        if d < min_dist:
            min_dist = d
    return min_dist


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two points in metres."""
    R = 6371000  # Earth radius in metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_in_corridor(lat: float, lon: float, corridors: list) -> Optional[str]:
    """Check if a point falls within any of the defined corridors.
    Returns corridor name or None."""
    for name, lat_min, lat_max, lon_min, lon_max in corridors:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None
