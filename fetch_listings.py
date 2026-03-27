#!/usr/bin/env python3
"""
fetch_listings.py — Fetch real Ottawa listings from realtor.ca

Two-step approach:
  1. StealthyFetcher (Camoufox/Firefox) loads realtor.ca to solve Incapsula challenge
  2. curl_cffi uses the session cookies to hit the PropertySearch API at full speed

Usage:
    python3 fetch_listings.py     → saves listings.csv
    python3 main.py               → analyze + score + output Obsidian notes
"""
import csv
import logging
import os
import re
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

BOUNDS = {
    "lat_min": 45.25,
    "lat_max": 45.55,
    "lon_min": -76.00,
    "lon_max": -75.45,
}

CSV_PATH = os.path.join(os.path.dirname(__file__), "listings.csv")
CSV_FIELDS = [
    "id", "mls_number", "source", "address", "city", "neighbourhood",
    "latitude", "longitude", "price", "property_type", "building_type",
    "lot_size_sqft", "lot_frontage_ft", "lot_depth_ft", "building_sqft",
    "bedrooms", "bathrooms", "year_built", "description", "listing_url",
]

API_URL = "https://api2.realtor.ca/Listing.svc/PropertySearch_Post"


# ─── Helpers ────────────────────────────────────────────────────────────────

_SQFT_PER_ACRE = 43560.0
_SQFT_PER_HA   = 107639.0
_SQFT_PER_SQM  = 10.7639
_M_TO_FT       = 3.28084


def _safe_float(val):
    if val is None or val == "":
        return None
    try:
        s = re.sub(r'[a-zA-Z²$,\' ]+', '', str(val)).strip()
        # Take only the first number if multiple remain
        m = re.match(r'-?\d+\.?\d*', s)
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def _parse_frontage_ft(raw: str):
    """Parse SizeFrontage/SizeDepth to feet.
    Handles: '65 ft', '45 m', '139 ft ,9 in', '36 ft ,11 in', bare numbers."""
    if not raw:
        return None
    s = str(raw).lower().strip()

    # "N ft ,M in" or "N ft M in"
    ft_in = re.match(r'(\d+\.?\d*)\s*ft\s*[,\s]*(\d+\.?\d*)\s*in', s)
    if ft_in:
        return float(ft_in.group(1)) + float(ft_in.group(2)) / 12

    # "N ft" or "N '"
    ft_only = re.match(r'(\d+\.?\d*)\s*(ft|\')', s)
    if ft_only:
        return float(ft_only.group(1))

    # "N m" (meters → feet)
    m_only = re.match(r'(\d+\.?\d*)\s*m\b', s)
    if m_only:
        return float(m_only.group(1)) * _M_TO_FT

    # Bare number — assume feet
    bare = re.search(r'\d+\.?\d*', s)
    return float(bare.group()) if bare else None


def _parse_lot_size(land: dict):
    """Parse realtor.ca Land dict to lot size in sqft.

    SizeTotal formats seen in the wild:
      '27.83 ac', '6154 m2', '31093 sqft', '26.98 ha',
      '36.96 x 134.96 FT', '139.76 x 109.9 FT',
      '150 FT' (single dimension — skip, unreliable),
      'under 1/2 acre' (descriptive)
    SizeFrontage / SizeDepth: '65 ft', '45 m', '36 ft ,11 in'
    """
    size_total = (land.get("SizeTotal") or "").strip()

    if size_total:
        s = size_total.lower().replace(",", "")

        # ── Dimension string "W x D FT" or "W x D m" ──────────────────────
        dim = re.match(r'(\d+\.?\d*)\s*x\s*(\d+\.?\d*)\s*(ft|m\b)?', s)
        if dim:
            w, d = float(dim.group(1)), float(dim.group(2))
            unit = (dim.group(3) or "ft").strip()
            area = w * d
            return area * _SQFT_PER_SQM if unit == "m" else area

        # ── sqft / sq ft ────────────────────────────────────────────────────
        if "sqft" in s or "sq ft" in s:
            m = re.search(r'\d+\.?\d*', s)
            return float(m.group()) if m else None

        # ── acres: "ac" or "acre" ───────────────────────────────────────────
        if re.search(r'\bac\b', s) or "acre" in s:
            m = re.search(r'\d+\.?\d*', s)
            return float(m.group()) * _SQFT_PER_ACRE if m else None

        # ── hectares ────────────────────────────────────────────────────────
        if "ha" in s or "hectare" in s:
            m = re.search(r'\d+\.?\d*', s)
            return float(m.group()) * _SQFT_PER_HA if m else None

        # ── square metres ───────────────────────────────────────────────────
        if "m2" in s or "sqm" in s or "m²" in s:
            m = re.search(r'\d+\.?\d*', s)
            return float(m.group()) * _SQFT_PER_SQM if m else None

        # ── "under 1/2 acre" style — must come before the acre check ─────────
        if "half acre" in s or "1/2 acre" in s:
            return 0.5 * _SQFT_PER_ACRE

        # ── "N FT" single dimension — skip (frontage masquerading as area) ──
        if re.search(r'^\d+\.?\d*\s*ft$', s):
            return None  # not a reliable area — fall back to frontage×depth

        # ── bare number — heuristic ─────────────────────────────────────────
        bare_m = re.search(r'\d+\.?\d*', s)
        if bare_m:
            val = float(bare_m.group())
            # <5  → almost certainly acres (rural lots like 2.5 ac, 0.25 ac)
            if val < 5:
                return val * _SQFT_PER_ACRE
            # 5–2000 → likely sqm (urban lots are typically 100–700 sqm)
            if val <= 2000:
                return val * _SQFT_PER_SQM
            # >2000 → treat as sqft directly
            return val

    # ── Fallback: frontage × depth ──────────────────────────────────────────
    front_ft = _parse_frontage_ft(land.get("SizeFrontage", ""))
    depth_ft = _parse_frontage_ft(land.get("SizeDepth", ""))
    if front_ft and depth_ft and front_ft < 800 and depth_ft < 800:
        return front_ft * depth_ft

    return None


def _cross_validate_lot(result, land: dict, price=None):
    """Cross-validate lot_size_sqft against frontage and price.
    Catches realtor.ca unit-mismatch errors (e.g., '78 ac' when frontage='78 ft').
    """
    if not result or result <= 50000:
        return result

    front = _parse_frontage_ft(land.get("SizeFrontage", ""))
    if front and front > 0 and result / front > 2000:
        depth = _parse_frontage_ft(land.get("SizeDepth", ""))
        return front * (depth if depth and depth < 800 else 120)

    # Price sanity: Ottawa urban land ~$500-2000/sqft.
    # If lot > 500K sqft at < $20M it's almost certainly a data error.
    if result > 500_000 and price and price < 20_000_000:
        return 500_000

    return result


_CONDO_PROP_TYPES = {
    "condo", "condominium", "apartment/condo", "condo apt",
    "comm element condo", "condo townhouse", "condo apartment", "strata",
}


def _is_condo(raw: dict) -> bool:
    """Return True if this realtor.ca API result is a condo/strata unit."""
    prop = raw.get("Property", {})
    addr = prop.get("Address", {})
    building = raw.get("Building", {})
    address_text = addr.get("AddressText", "")
    prop_type = (prop.get("Type") or "").lower()
    btype = (building.get("Type") or "").lower()
    desc = (raw.get("PublicRemarks") or "").lower()

    # Address starts with unit designator: "705 - 203 CATHERINE", "C002 - 1910 ST"
    if re.match(r'^[A-Z0-9]+[-\s]*\d*\s+-\s+\d', address_text):
        return True

    if any(kw in prop_type for kw in _CONDO_PROP_TYPES):
        return True
    if any(kw in btype for kw in _CONDO_PROP_TYPES):
        return True

    condo_desc_keywords = [
        "condo", "condominium", "strata", "apartment unit",
        "unit #", "suite #",
    ]
    if any(kw in desc for kw in condo_desc_keywords):
        return True

    return False


def _parse_listing(raw: dict):
    """Parse a realtor.ca API result. Returns None for condo/strata units."""
    # Skip condo units — they have no tear-down/rebuild value
    if _is_condo(raw):
        return None

    prop = raw.get("Property", {})
    addr = prop.get("Address", {})
    building = raw.get("Building", {})
    land = raw.get("Land", {})

    price_raw = str(prop.get("Price", "") or "").replace("$", "").replace(",", "").strip()
    try:
        price = float(price_raw)
    except ValueError:
        price = None

    year_built = None
    c = building.get("ConstructedDate", "")
    if c:
        try:
            year_built = int(str(c)[:4])
        except (ValueError, TypeError):
            pass

    return {
        "id": f"realtor_ca_{raw.get('Id', '')}",
        "mls_number": raw.get("MlsNumber", ""),
        "source": "realtor.ca",
        "address": addr.get("AddressText", ""),
        "city": "Ottawa",
        "neighbourhood": addr.get("CommunityName", ""),
        "latitude": _safe_float(addr.get("Latitude")),
        "longitude": _safe_float(addr.get("Longitude")),
        "price": price,
        "property_type": prop.get("Type", ""),
        "building_type": building.get("Type", ""),
        "lot_size_sqft": _cross_validate_lot(_parse_lot_size(land), land, price),
        "lot_frontage_ft": _parse_frontage_ft(land.get("SizeFrontage", "")),
        "lot_depth_ft": _parse_frontage_ft(land.get("SizeDepth", "")),
        "building_sqft": _safe_float(building.get("SizeInterior", "")),
        "bedrooms": _safe_float(building.get("Bedrooms", "")),
        "bathrooms": _safe_float(building.get("BathroomTotal", "")),
        "year_built": year_built,
        "description": (raw.get("PublicRemarks") or "")[:2000],
        "listing_url": f"https://www.realtor.ca{raw.get('RelativeDetailsURL', '')}",
    }


def _is_in_ottawa(listing: dict) -> bool:
    """Filter to Ottawa proper — exclude Gatineau/Chelsea/Quebec side."""
    addr = listing.get("address", "").lower()
    lat = listing.get("latitude") or 0
    lon = listing.get("longitude") or 0
    # Quebec addresses contain QC/Quebec province codes
    if " qc" in addr or "quebec" in addr or "gatineau" in addr:
        return False
    # Latitude/longitude check — Ottawa is entirely south of 45.55 and west of -75.45
    if lat and lon:
        if not (45.25 <= lat <= 45.55 and -76.00 <= lon <= -75.45):
            return False
    return True


# ─── Step 1: Solve Incapsula challenge ───────────────────────────────────────

def get_incapsula_cookies() -> dict:
    """Use StealthyFetcher (Camoufox/Firefox) to solve the Incapsula challenge
    and return the session cookies needed for API calls."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.error("scrapling not installed. Run: pip3 install scrapling")
        return {}

    log.info("Solving Incapsula challenge via StealthyFetcher (Firefox)...")
    log.info("(This takes ~15 seconds — a headless Firefox window will run)")

    try:
        page = StealthyFetcher.fetch(
            "https://www.realtor.ca/map",
            headless=True,
            network_idle=True,
            timeout=60000,
            wait=5000,
            google_search=True,
            humanize=True,
        )
        log.info(f"  Challenge status: {page.status} | Cookies: {len(page.cookies)}")
        incap_keys = [k for k in page.cookies if any(x in k for x in
                      ["incap", "nlbi", "visid", "reese84", "__AntiXsrf", "cf_"])]
        log.info(f"  Incapsula cookies captured: {incap_keys}")
        return dict(page.cookies)
    except Exception as e:
        log.error(f"  StealthyFetcher failed: {e}")
        return {}


# ─── Step 2: Fetch listings with session cookies ─────────────────────────────

def fetch_listings_with_cookies(cookies: dict) -> list[dict]:
    """Use curl_cffi + Incapsula session cookies to paginate through listings."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        log.error("curl_cffi not installed. Run: pip3 install curl_cffi")
        return []

    session = cffi_requests.Session(impersonate="chrome110")
    session.headers.update({
        "Referer": "https://www.realtor.ca/",
        "Origin": "https://www.realtor.ca",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
    })
    for k, v in cookies.items():
        session.cookies.set(k, v)

    all_listings = []
    seen_ids = set()
    total_pages_fetched = 0

    # Search types: 0=all property types, 6=vacant land only
    for search_type in [0, 6]:
        for page_num in range(1, 21):  # up to 20 pages × 200 = 4000 listings
            payload = {
                "LatitudeMin": str(BOUNDS["lat_min"]),
                "LatitudeMax": str(BOUNDS["lat_max"]),
                "LongitudeMin": str(BOUNDS["lon_min"]),
                "LongitudeMax": str(BOUNDS["lon_max"]),
                "RecordsPerPage": "200",
                "CurrentPage": str(page_num),
                "ApplicationId": "1",
                "CultureId": "1",
                "PropertySearchTypeId": str(search_type),
                "TransactionTypeId": "2",
                "SortBy": "6",
                "SortOrder": "A",
                "HashCode": "0",
            }

            try:
                resp = session.post(API_URL, data=payload, timeout=30)
                total_pages_fetched += 1
            except Exception as e:
                log.error(f"  Request error (type={search_type} page={page_num}): {e}")
                break

            if resp.status_code == 403:
                log.warning(f"  Got 403 — cookies may have expired. Re-run to refresh.")
                break

            if resp.status_code != 200:
                log.warning(f"  HTTP {resp.status_code} on page {page_num}")
                break

            try:
                data = resp.json()
            except Exception as e:
                log.error(f"  JSON parse error: {e}")
                break

            results = data.get("Results", [])
            if not results:
                break

            paging = data.get("Paging", {})
            total_pages = paging.get("TotalPages", 1)
            new_count = 0
            for raw in results:
                rid = raw.get("Id")
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    listing = _parse_listing(raw)
                    if listing and _is_in_ottawa(listing):
                        all_listings.append(listing)
                        new_count += 1

            log.info(
                f"  type={search_type} page={page_num}/{total_pages}: "
                f"+{new_count} Ottawa listings (total: {len(all_listings)})"
            )

            if page_num >= total_pages:
                break

            time.sleep(0.8)  # polite delay between pages

    log.info(f"Fetched {len(all_listings)} Ottawa listings across {total_pages_fetched} API calls")
    return all_listings


# ─── Save + Main ─────────────────────────────────────────────────────────────

def save_to_csv(listings: list[dict]) -> int:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(listings)
    return len(listings)


def main():
    log.info("=" * 60)
    log.info("Ottawa Tear-Down Analyzer — Listing Fetcher")
    log.info("=" * 60)

    # Step 1: solve Incapsula
    cookies = get_incapsula_cookies()
    if not cookies:
        log.error("Could not get session cookies. Exiting.")
        sys.exit(1)

    # Step 2: paginate through listings
    log.info("\nFetching listings from realtor.ca API...")
    listings = fetch_listings_with_cookies(cookies)

    if not listings:
        log.error("No listings returned. Cookies may have expired or API changed.")
        sys.exit(1)

    # Save
    n = save_to_csv(listings)
    log.info(f"\n✓ Saved {n} listings → {CSV_PATH}")
    log.info("Now run: python3 main.py")


if __name__ == "__main__":
    main()
