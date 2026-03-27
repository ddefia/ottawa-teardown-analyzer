"""
Ottawa Tear-Down Analyzer — Listing Scraper

Multiple data source support:
  1. realtor.ca API (via PlayWright stealth browser to bypass Incapsula)
  2. CSV import (manual export from realtor.ca / HouseSigma / Zolo)
  3. Sample data (for testing the pipeline)
"""
import csv
import json
import os
import re
import time
import logging
from typing import Optional

import requests

from config import (
    REALTOR_CA_SEARCH,
    OTTAWA_BOUNDS,
    RECORDS_PER_PAGE,
    REQUEST_DELAY_S,
    MAX_PAGES,
    MIN_LOT_SQFT,
    CONDO_KEYWORDS,
    PROTECTED_KEYWORDS,
)

log = logging.getLogger(__name__)

HEADERS = {
    "Referer": "https://www.realtor.ca/",
    "Origin": "https://www.realtor.ca",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# Source 1: realtor.ca via Playwright stealth browser
# ═══════════════════════════════════════════════════════════════════════════

def scrape_realtor_ca_playwright() -> list[dict]:
    """Scrape realtor.ca using Playwright with stealth fingerprints.
    Navigates like a real user and intercepts the API responses."""
    try:
        from scrapling import PlayWrightFetcher
    except ImportError:
        log.error("scrapling not installed. Run: pip3 install scrapling && scrapling install")
        return []

    log.info("Launching stealth browser for realtor.ca...")
    all_listings = []

    try:
        # Configure before instantiating
        PlayWrightFetcher.configure(headless=True, disable_resources=False)
        fetcher = PlayWrightFetcher()

        # Load the search page with Ottawa bounds
        url = (
            "https://www.realtor.ca/map"
            "#ZoomLevel=11"
            f"&Center=45.39%2C-75.69"
            f"&LatitudeMax={OTTAWA_BOUNDS['lat_max']}"
            f"&LongitudeMax={OTTAWA_BOUNDS['lon_max']}"
            f"&LatitudeMin={OTTAWA_BOUNDS['lat_min']}"
            f"&LongitudeMin={OTTAWA_BOUNDS['lon_min']}"
            "&Sort=6-A"
            "&PropertyTypeGroupID=1"
            "&TransactionTypeId=2"
            "&PropertySearchTypeId=0"
        )
        page = fetcher.fetch(url, timeout=45000)

        if page.status != 200 or not page.html_content or len(page.html_content) < 5000:
            log.warning("realtor.ca blocked the stealth browser request")
            return []

        # Parse listings from the page HTML
        all_listings = _parse_realtor_html(page.html_content)
        log.info(f"Scraped {len(all_listings)} listings via Playwright")

    except Exception as e:
        log.error(f"Playwright scraping failed: {e}")

    return all_listings


def _parse_realtor_html(html: str) -> list[dict]:
    """Parse realtor.ca HTML for listing data embedded in JSON."""
    listings = []
    # realtor.ca embeds listing data as JSON in script tags or data attributes
    # Try to find the __NEXT_DATA__ or similar JSON blob
    matches = re.findall(r'"Results"\s*:\s*\[(.*?)\]', html, re.DOTALL)
    if matches:
        for match in matches:
            try:
                results = json.loads(f"[{match}]")
                for raw in results:
                    listing = _parse_realtor_listing(raw)
                    if listing:
                        listings.append(listing)
            except json.JSONDecodeError:
                pass
    return listings


# ═══════════════════════════════════════════════════════════════════════════
# Source 2: realtor.ca direct API (works if not blocked)
# ═══════════════════════════════════════════════════════════════════════════

def scrape_realtor_ca_api() -> list[dict]:
    """Try the direct realtor.ca API. Returns empty list if blocked (403)."""
    session = requests.Session()
    session.headers.update(HEADERS)

    all_listings = []
    seen_ids = set()

    for search_type in [0, 6]:  # 0=all, 6=vacant land
        page = 1
        while page <= MAX_PAGES:
            log.info(f"API: Fetching page {page} (type={search_type})...")
            payload = {
                "LatitudeMin": str(OTTAWA_BOUNDS["lat_min"]),
                "LatitudeMax": str(OTTAWA_BOUNDS["lat_max"]),
                "LongitudeMin": str(OTTAWA_BOUNDS["lon_min"]),
                "LongitudeMax": str(OTTAWA_BOUNDS["lon_max"]),
                "PriceMin": "0",
                "PriceMax": "0",
                "RecordsPerPage": str(RECORDS_PER_PAGE),
                "CurrentPage": str(page),
                "ApplicationId": "1",
                "CultureId": "1",
                "PropertySearchTypeId": str(search_type),
                "TransactionTypeId": "2",
                "SortBy": "6",
                "SortOrder": "A",
                "HashCode": "0",
            }

            try:
                resp = session.post(REALTOR_CA_SEARCH, data=payload, timeout=30)
                if resp.status_code == 403:
                    log.warning("realtor.ca API returned 403 (blocked)")
                    return []  # Signal to try another source
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.error(f"API request failed page={page}: {e}")
                return []

            results = data.get("Results", [])
            if not results:
                break

            paging = data.get("Paging", {})
            total_pages = paging.get("TotalPages", 0)

            for raw in results:
                lid = raw.get("Id")
                if lid in seen_ids:
                    continue
                seen_ids.add(lid)
                listing = _parse_realtor_listing(raw)
                if listing and _is_redevelopment_candidate(listing):
                    all_listings.append(listing)

            if page >= total_pages:
                break
            page += 1
            time.sleep(REQUEST_DELAY_S)

    log.info(f"API: Scraped {len(all_listings)} candidates from {len(seen_ids)} listings")
    return all_listings


def _parse_realtor_listing(raw: dict) -> Optional[dict]:
    """Parse a single realtor.ca JSON listing into standard format."""
    prop = raw.get("Property", {})
    addr = prop.get("Address", {})
    building = raw.get("Building", {})
    land = raw.get("Land", {})

    address_str = addr.get("AddressText", "")
    description = raw.get("PublicRemarks", "") or ""
    property_type = prop.get("Type", "")
    building_type = building.get("Type", "")
    all_text = f"{address_str} {description} {property_type} {building_type}".lower()

    # Exclusion filters
    if any(kw in all_text for kw in CONDO_KEYWORDS):
        return None
    if any(kw in all_text for kw in PROTECTED_KEYWORDS):
        return None

    lot_size_sqft = _parse_lot_size(land)
    lot_frontage_ft = _safe_float(land.get("SizeFrontage", ""))
    lot_depth_ft = _safe_float(land.get("SizeDepth", ""))

    is_vacant = "vacant" in all_text or "land" in property_type.lower()
    if lot_size_sqft and lot_size_sqft < MIN_LOT_SQFT and not is_vacant:
        return None

    lat = _safe_float(addr.get("Latitude"))
    lon = _safe_float(addr.get("Longitude"))
    price_raw = prop.get("Price", "")

    year_built = None
    construction = building.get("ConstructedDate", "")
    if construction:
        try:
            year_built = int(str(construction)[:4])
        except (ValueError, TypeError):
            pass

    return {
        "id": f"realtor_ca_{raw.get('Id', '')}",
        "mls_number": raw.get("MlsNumber", ""),
        "source": "realtor.ca",
        "address": address_str,
        "city": "Ottawa",
        "neighbourhood": addr.get("CommunityName", ""),
        "latitude": lat,
        "longitude": lon,
        "price": _parse_price(price_raw),
        "property_type": property_type,
        "building_type": building_type,
        "lot_size_sqft": lot_size_sqft,
        "lot_frontage_ft": lot_frontage_ft,
        "lot_depth_ft": lot_depth_ft,
        "building_sqft": _safe_float(building.get("SizeInterior", "")),
        "bedrooms": _safe_int(building.get("Bedrooms", "")),
        "bathrooms": _safe_int(building.get("BathroomTotal", "")),
        "year_built": year_built,
        "description": description[:2000],
        "listing_url": f"https://www.realtor.ca{raw.get('RelativeDetailsURL', '')}",
        "photo_url": _get_photo_url(raw),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Source 3: CSV Import
# ═══════════════════════════════════════════════════════════════════════════

def import_from_csv(csv_path: str) -> list[dict]:
    """Import listings from a CSV file.
    Supports exports from realtor.ca, HouseSigma, or any CSV with address columns.
    """
    if not os.path.exists(csv_path):
        log.error(f"CSV file not found: {csv_path}")
        return []

    listings = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            listing = _parse_csv_row(row, i)
            if listing and _is_redevelopment_candidate(listing):
                listings.append(listing)

    log.info(f"CSV: Imported {len(listings)} candidates from {csv_path}")
    return listings


def _parse_csv_row(row: dict, idx: int) -> Optional[dict]:
    """Parse a CSV row into standard listing format.
    Handles various column naming conventions."""
    # Normalize column names to lowercase
    r = {k.lower().strip(): v for k, v in row.items()}

    address = (
        r.get("address") or r.get("address_text") or r.get("full_address")
        or r.get("street_address") or r.get("addr") or ""
    )
    if not address:
        return None

    return {
        "id": r.get("id") or r.get("mls") or r.get("mls_number") or f"csv_{idx}",
        "mls_number": r.get("mls") or r.get("mls_number") or r.get("mls#") or "",
        "source": "csv",
        "address": address,
        "city": r.get("city") or "Ottawa",
        "neighbourhood": r.get("neighbourhood") or r.get("neighborhood") or r.get("area") or "",
        "latitude": _safe_float(r.get("latitude") or r.get("lat")),
        "longitude": _safe_float(r.get("longitude") or r.get("lon") or r.get("lng")),
        "price": _parse_price(r.get("price") or r.get("list_price") or r.get("asking_price")),
        "property_type": r.get("property_type") or r.get("type") or "",
        "building_type": r.get("building_type") or "",
        "lot_size_sqft": _safe_float(r.get("lot_size_sqft") or r.get("lot_size") or r.get("lot_area")),
        "lot_frontage_ft": _safe_float(r.get("lot_frontage_ft") or r.get("frontage")),
        "lot_depth_ft": _safe_float(r.get("lot_depth_ft") or r.get("depth")),
        "building_sqft": _safe_float(r.get("building_sqft") or r.get("sqft") or r.get("interior_sqft")),
        "bedrooms": _safe_int(r.get("bedrooms") or r.get("beds")),
        "bathrooms": _safe_int(r.get("bathrooms") or r.get("baths")),
        "year_built": _safe_int(r.get("year_built") or r.get("built")),
        "description": r.get("description") or r.get("remarks") or "",
        "listing_url": r.get("listing_url") or r.get("url") or r.get("link") or "",
        "photo_url": r.get("photo_url") or r.get("photo") or "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Source 4: Sample data for testing
# ═══════════════════════════════════════════════════════════════════════════

def generate_sample_data() -> list[dict]:
    """Generate realistic Ottawa sample listings for pipeline testing."""
    samples = [
        {
            "id": "sample_001", "mls_number": "X0000001",
            "source": "sample", "address": "1234 Bank St, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Old Ottawa South",
            "latitude": 45.3876, "longitude": -75.6870,
            "price": 850000, "property_type": "Vacant Land",
            "lot_size_sqft": 12500, "lot_frontage_ft": 50, "lot_depth_ft": 250,
            "building_sqft": 0, "year_built": None,
            "description": "Large vacant lot on Bank St near Lansdowne. Excellent development opportunity. Zoned for mixed use.",
            "listing_url": "https://www.realtor.ca/sample/1",
        },
        {
            "id": "sample_002", "mls_number": "X0000002",
            "source": "sample", "address": "456 Gladstone Ave, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Centretown",
            "latitude": 45.4105, "longitude": -75.6975,
            "price": 675000, "property_type": "Single Family",
            "lot_size_sqft": 5500, "lot_frontage_ft": 40, "lot_depth_ft": 137,
            "building_sqft": 1200, "bedrooms": 2, "bathrooms": 1,
            "year_built": 1945,
            "description": "Older home on large lot in Centretown. Tear down and rebuild potential. Near LRT and amenities.",
            "listing_url": "https://www.realtor.ca/sample/2",
        },
        {
            "id": "sample_003", "mls_number": "X0000003",
            "source": "sample", "address": "789 Montreal Rd, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Vanier",
            "latitude": 45.4420, "longitude": -75.6500,
            "price": 525000, "property_type": "Commercial",
            "lot_size_sqft": 8000, "lot_frontage_ft": 60, "lot_depth_ft": 133,
            "building_sqft": 2400, "year_built": 1960,
            "description": "Commercial building on Montreal Rd. Investor alert. Can be converted to residential mixed-use.",
            "listing_url": "https://www.realtor.ca/sample/3",
        },
        {
            "id": "sample_004", "mls_number": "X0000004",
            "source": "sample", "address": "321 Carling Ave, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Civic Hospital",
            "latitude": 45.3810, "longitude": -75.7200,
            "price": 1250000, "property_type": "Multi Family",
            "building_type": "Duplex",
            "lot_size_sqft": 9000, "lot_frontage_ft": 55, "lot_depth_ft": 164,
            "building_sqft": 3200, "bedrooms": 4, "bathrooms": 3,
            "year_built": 1955,
            "description": "Duplex on Carling Ave near Civic Hospital and future LRT. Large lot with severance potential.",
            "listing_url": "https://www.realtor.ca/sample/4",
        },
        {
            "id": "sample_005", "mls_number": "X0000005",
            "source": "sample", "address": "555 St Laurent Blvd, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Elmvale Acres",
            "latitude": 45.3990, "longitude": -75.6370,
            "price": 950000, "property_type": "Vacant Land",
            "lot_size_sqft": 22000, "lot_frontage_ft": 100, "lot_depth_ft": 220,
            "building_sqft": 0,
            "description": "Huge vacant parcel on St Laurent Blvd. Ideal for mid-rise development. Near LRT station.",
            "listing_url": "https://www.realtor.ca/sample/5",
        },
        {
            "id": "sample_006", "mls_number": "X0000006",
            "source": "sample", "address": "88 Hinton Ave N, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Hintonburg",
            "latitude": 45.3960, "longitude": -75.7275,
            "price": 595000, "property_type": "Single Family",
            "lot_size_sqft": 4500, "lot_frontage_ft": 35, "lot_depth_ft": 128,
            "building_sqft": 1000, "bedrooms": 2, "bathrooms": 1,
            "year_built": 1920,
            "description": "Handyman special in hot Hintonburg. Steps to Westboro LRT. Sold as-is. Builder's lot value.",
            "listing_url": "https://www.realtor.ca/sample/6",
        },
        {
            "id": "sample_007", "mls_number": "X0000007",
            "source": "sample", "address": "1500 Scott St, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Mechanicsville",
            "latitude": 45.3945, "longitude": -75.7180,
            "price": 2100000, "property_type": "Commercial",
            "lot_size_sqft": 15000, "lot_frontage_ft": 80, "lot_depth_ft": 187,
            "building_sqft": 5000, "year_built": 1970,
            "description": "Former industrial site on Scott St near Bayview LRT. Rezoning application in progress to R5.",
            "listing_url": "https://www.realtor.ca/sample/7",
        },
        {
            "id": "sample_008", "mls_number": "X0000008",
            "source": "sample", "address": "200 Rideau St, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Sandy Hill",
            "latitude": 45.4290, "longitude": -75.6830,
            "price": 1800000, "property_type": "Multi Family",
            "building_type": "Triplex",
            "lot_size_sqft": 6500, "lot_frontage_ft": 45, "lot_depth_ft": 144,
            "building_sqft": 4800, "bedrooms": 6, "bathrooms": 3,
            "year_built": 1940,
            "description": "Income property near uOttawa and Rideau LRT. Triplex with development potential. Minor variance possible.",
            "listing_url": "https://www.realtor.ca/sample/8",
        },
        {
            "id": "sample_009", "mls_number": "X0000009",
            "source": "sample", "address": "45 Presland Rd, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Overbrook",
            "latitude": 45.4350, "longitude": -75.6550,
            "price": 380000, "property_type": "Single Family",
            "lot_size_sqft": 7200, "lot_frontage_ft": 60, "lot_depth_ft": 120,
            "building_sqft": 900, "bedrooms": 2, "bathrooms": 1,
            "year_built": 1950,
            "description": "Estate sale. Large lot in Overbrook near St Laurent LRT. Fixer upper or tear down for multi-unit.",
            "listing_url": "https://www.realtor.ca/sample/9",
        },
        {
            "id": "sample_010", "mls_number": "X0000010",
            "source": "sample", "address": "2200 Riverside Dr, Ottawa ON",
            "city": "Ottawa", "neighbourhood": "Mooney's Bay",
            "latitude": 45.3640, "longitude": -75.6850,
            "price": 720000, "property_type": "Single Family",
            "lot_size_sqft": 11000, "lot_frontage_ft": 70, "lot_depth_ft": 157,
            "building_sqft": 1800, "bedrooms": 3, "bathrooms": 2,
            "year_built": 1965,
            "description": "Large corner lot near Mooney's Bay LRT. Close to riverfront. Underbuilt for the lot size.",
            "listing_url": "https://www.realtor.ca/sample/10",
        },
    ]
    log.info(f"Sample: Generated {len(samples)} sample listings")
    return samples


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point — tries sources in priority order
# ═══════════════════════════════════════════════════════════════════════════

def scrape_ottawa_listings(csv_path: str = None) -> list[dict]:
    """Scrape Ottawa listings. Tries multiple sources in order:
    1. CSV import (if path provided)
    2. realtor.ca direct API
    3. realtor.ca via Playwright stealth browser
    4. Sample data (fallback for testing)
    """
    # CSV import
    if csv_path:
        listings = import_from_csv(csv_path)
        if listings:
            return listings

    # Check for CSV in project directory
    auto_csv = os.path.join(os.path.dirname(__file__), "listings.csv")
    if os.path.exists(auto_csv):
        log.info(f"Found listings.csv — importing from CSV")
        listings = import_from_csv(auto_csv)
        if listings:
            return listings

    # Try direct API first (fastest if not blocked)
    log.info("Trying realtor.ca direct API...")
    listings = scrape_realtor_ca_api()
    if listings:
        return listings

    # Try Playwright stealth browser
    log.info("Direct API blocked. Trying stealth browser...")
    listings = scrape_realtor_ca_playwright()
    if listings:
        return listings

    # Fallback to sample data
    log.warning("All live sources failed. Using sample data for pipeline testing.")
    log.warning("To use real data, export listings to 'listings.csv' in the project directory.")
    return generate_sample_data()


# ═══════════════════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════════════════

def _is_redevelopment_candidate(listing: dict) -> bool:
    """Smart filter: does this listing have tear-down/rebuild potential?"""
    desc = (listing.get("description") or "").lower()
    prop_type = (listing.get("property_type") or "").lower()
    btype = (listing.get("building_type") or "").lower()
    lot = listing.get("lot_size_sqft") or 0
    year = listing.get("year_built")
    building_sqft = listing.get("building_sqft") or 0

    if "vacant" in prop_type or "land" in prop_type or (lot > 0 and building_sqft == 0):
        return True

    opportunity_keywords = [
        "tear down", "teardown", "tear-down", "redevelop", "development",
        "builder", "investor", "potential", "lot value", "land value",
        "as-is", "as is", "estate sale", "handyman", "fixer",
        "needs work", "sold as-is", "infill", "severance",
        "zoning", "rezone", "multi-unit", "multi unit",
        "income property", "investment", "commercial zoning",
        "mixed use", "mixed-use", "conversion",
    ]
    if any(kw in desc for kw in opportunity_keywords):
        return True

    if year and year < 1970 and lot >= 5000:
        return True
    if lot >= 6000 and building_sqft > 0 and building_sqft < lot * 0.3:
        return True
    if any(t in prop_type for t in ["multi", "commercial", "industrial"]):
        return True
    if any(t in btype for t in ["duplex", "triplex", "fourplex", "multiplex"]):
        return True
    if lot >= 10000:
        return True

    return False


def _parse_lot_size(land: dict) -> Optional[float]:
    size_total = land.get("SizeTotal", "")
    if not size_total:
        frontage = _safe_float(land.get("SizeFrontage", ""))
        depth = _safe_float(land.get("SizeDepth", ""))
        if frontage and depth:
            return frontage * depth
        return None

    size_str = str(size_total).lower().replace(",", "").strip()
    if "sqft" in size_str or "sq ft" in size_str:
        return _extract_number(size_str)
    if "acre" in size_str:
        n = _extract_number(size_str)
        return n * 43560 if n else None
    if "hectare" in size_str or "ha" in size_str:
        n = _extract_number(size_str)
        return n * 107639 if n else None
    if "sqm" in size_str or "m2" in size_str or "m²" in size_str:
        n = _extract_number(size_str)
        return n * 10.7639 if n else None
    return _extract_number(size_str)


def _extract_number(s: str) -> Optional[float]:
    match = re.search(r'[\d]+\.?\d*', s.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _parse_price(price_raw) -> Optional[float]:
    if not price_raw:
        return None
    s = str(price_raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _safe_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        s = re.sub(r'[a-zA-Z²]+$', '', str(val).replace(",", "").replace("'", "")).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    f = _safe_float(val)
    return int(f) if f is not None else None


def _get_photo_url(raw: dict) -> Optional[str]:
    photos = raw.get("Property", {}).get("Photo", [])
    if photos and isinstance(photos, list) and len(photos) > 0:
        return photos[0].get("HighResPath") or photos[0].get("MedResPath", "")
    return None
