"""
Ottawa Tear-Down Analyzer — Zoning & Geocoding
Queries Ottawa's ArcGIS zoning layer and geocoder.
"""
import logging
import math
import requests
from typing import Optional

from config import ZONING_QUERY_URL, GEOCODER_URL, ZONING_TABLE

log = logging.getLogger(__name__)


def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """Geocode an Ottawa address to (lat, lon) using the city's ArcGIS geocoder.
    Returns (lat, lon) in WGS-84 or None if geocoding fails."""
    try:
        resp = requests.get(
            GEOCODER_URL,
            params={
                "SingleLine": address,
                "f": "json",
                "outSR": "4326",  # Request WGS-84 directly
                "maxLocations": "1",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates and candidates[0].get("score", 0) >= 70:
            loc = candidates[0]["location"]
            return (loc["y"], loc["x"])  # (lat, lon)
    except Exception as e:
        log.warning(f"Geocoding failed for '{address}': {e}")
    return None


def lookup_zoning(lat: float, lon: float) -> dict:
    """Query the Ottawa ArcGIS zoning layer for a point (lat, lon).
    Returns a dict with zone_code, zone_main, max_height_m, and bylaw params."""
    result = {
        "zone_code": None,
        "zone_main": None,
        "max_height_m": None,
        "max_fsi": None,
        "setback_front_m": None,
        "setback_rear_m": None,
        "setback_side_m": None,
    }

    try:
        resp = requests.get(
            ZONING_QUERY_URL,
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "ZONE_CODE,ZONE_MAIN,HEIGHT,HEIGHTINFO,ZONINGTYPE",
                "f": "json",
                "returnGeometry": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"Zoning query failed for ({lat}, {lon}): {e}")
        return result

    features = data.get("features", [])
    if not features:
        log.debug(f"No zoning features found for ({lat}, {lon})")
        return result

    # Take the first zoning feature (not flood/heritage overlays)
    attrs = None
    for feat in features:
        a = feat.get("attributes", {})
        ztype = (a.get("ZONINGTYPE") or "").lower()
        if ztype == "zoning" or not ztype:
            attrs = a
            break
    if attrs is None:
        attrs = features[0].get("attributes", {})

    zone_code = attrs.get("ZONE_CODE", "")
    zone_main = attrs.get("ZONE_MAIN", "")
    result["zone_code"] = zone_code
    result["zone_main"] = zone_main

    # ── Extract height from API ───────────────────────────────────────
    api_height = attrs.get("HEIGHT")
    height_info = attrs.get("HEIGHTINFO")
    if api_height and api_height > 0:
        result["max_height_m"] = float(api_height)
    elif height_info:
        try:
            result["max_height_m"] = float(height_info)
        except (ValueError, TypeError):
            pass

    # ── Merge with bylaw lookup table ─────────────────────────────────
    # Try exact zone_main first, then first two chars
    table_entry = _lookup_zone_params(zone_main)
    if table_entry:
        # Use table values as defaults, API height overrides if present
        if result["max_height_m"] is None:
            result["max_height_m"] = table_entry["max_height_m"]
        result["max_fsi"] = table_entry["max_fsi"]
        result["setback_front_m"] = table_entry["setback_front_m"]
        result["setback_rear_m"] = table_entry["setback_rear_m"]
        result["setback_side_m"] = table_entry["setback_side_m"]

    # ── Parse subzone suffix for height/FSI overrides ─────────────────
    _apply_subzone_overrides(zone_code, result)

    return result


def _lookup_zone_params(zone_main: str) -> Optional[dict]:
    """Look up bylaw parameters for a zone prefix."""
    if not zone_main:
        return None
    # Exact match
    if zone_main.upper() in ZONING_TABLE:
        return ZONING_TABLE[zone_main.upper()]
    # Try first 2 characters (handles R5B → R5, etc.)
    prefix = zone_main.upper()[:2]
    if prefix in ZONING_TABLE:
        return ZONING_TABLE[prefix]
    # Try first character + digit
    if len(zone_main) >= 2:
        for i in range(len(zone_main), 0, -1):
            candidate = zone_main[:i].upper()
            if candidate in ZONING_TABLE:
                return ZONING_TABLE[candidate]
    return None


def _apply_subzone_overrides(zone_code: str, result: dict):
    """Parse zone code suffixes like H(18), F(2.5), etc.
    Ottawa zone codes follow patterns:
      R5B[856] H(18)     → height override = 18m
      GM[1234] F(3.5)    → FSI override = 3.5
      AM12[456] H(20)    → height = 20m
    """
    import re
    if not zone_code:
        return

    # Height override: H(number) or H (number)
    h_match = re.search(r'H\s*\((\d+\.?\d*)\)', zone_code)
    if h_match:
        result["max_height_m"] = float(h_match.group(1))

    # FSI override: F(number)
    f_match = re.search(r'F\s*\((\d+\.?\d*)\)', zone_code)
    if f_match:
        result["max_fsi"] = float(f_match.group(1))


def enrich_listing_with_zoning(listing: dict) -> dict:
    """Add zoning data to a listing dict.
    Uses listing lat/lon, falling back to geocoding the address."""
    lat = listing.get("latitude")
    lon = listing.get("longitude")

    # Geocode if we don't have coordinates
    if not lat or not lon:
        address = listing.get("address", "")
        if address:
            coords = geocode_address(f"{address}, Ottawa, ON")
            if coords:
                lat, lon = coords
                listing["latitude"] = lat
                listing["longitude"] = lon

    if not lat or not lon:
        log.warning(f"No coordinates for {listing.get('address')} — skipping zoning")
        return listing

    zoning = lookup_zoning(lat, lon)
    listing.update(zoning)
    return listing
