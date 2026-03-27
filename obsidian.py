"""
Ottawa Tear-Down Analyzer — Obsidian Markdown Output
Generates property analysis notes with YAML frontmatter for Dataview.
"""
import os
import re
import logging
from config import OBSIDIAN_VAULT, SCORE_MINIMUM_FOR_OBSIDIAN, RUN_TIMESTAMP

log = logging.getLogger(__name__)


def save_obsidian_summaries(listings: list[dict]):
    """Save markdown summaries for top-scoring listings to the Obsidian vault."""
    os.makedirs(OBSIDIAN_VAULT, exist_ok=True)

    saved = 0
    for listing in listings:
        if (listing.get("score") or 0) < SCORE_MINIMUM_FOR_OBSIDIAN:
            continue

        filename = _sanitize_filename(listing.get("address", "unknown"))
        filepath = os.path.join(OBSIDIAN_VAULT, f"{filename}.md")

        content = _render_markdown(listing)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        saved += 1
        log.info(f"Saved: {filepath}")

    log.info(f"Saved {saved} Obsidian notes to {OBSIDIAN_VAULT}")
    return saved


def _sanitize_filename(address: str) -> str:
    """Clean an address into a valid filename."""
    s = address.strip()
    s = re.sub(r'[<>:"/\\|?*]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s[:100]  # Limit length


def _render_markdown(L: dict) -> str:
    """Render a listing as Obsidian-friendly markdown with YAML frontmatter."""
    score = L.get("score", 0)
    price = L.get("price", 0)

    # Star rating for quick visual scanning
    stars = _star_rating(score)

    md = f"""---
tags: [real-estate, ottawa, teardown-analysis]
score: {score}
price: {_fmt_price(price)}
zone: "{L.get('zone_code', 'Unknown')}"
zone_main: "{L.get('zone_main', '')}"
neighbourhood: "{L.get('neighbourhood', '')}"
lot_sqft: {L.get('lot_size_sqft') or 0:.0f}
estimated_units: {L.get('estimated_units') or 0}
potential_units: {L.get('potential_units') or 0}
rezone_likelihood: "{L.get('rezone_likelihood', 'Unknown')}"
mls: "{L.get('mls_number', '')}"
analyzed: "{RUN_TIMESTAMP}"
---

# {L.get('address', 'Unknown Address')}

{stars} **Score: {score}/100** | {_fmt_price(price)}

## Quick Facts

| Field | Value |
|-------|-------|
| MLS | {L.get('mls_number', 'N/A')} |
| Price | {_fmt_price(price)} |
| Property Type | {L.get('property_type', 'N/A')} |
| Lot Size | {L.get('lot_size_sqft') or 0:,.0f} sqft |
| Frontage | {L.get('lot_frontage_ft') or 'N/A'} ft |
| Depth | {L.get('lot_depth_ft') or 'N/A'} ft |
| Building | {L.get('building_sqft') or 0:,.0f} sqft |
| Year Built | {L.get('year_built') or 'N/A'} |
| Neighbourhood | {L.get('neighbourhood', 'N/A')} |

## Zoning Analysis

| Field | Value |
|-------|-------|
| Zone Code | `{L.get('zone_code', 'Unknown')}` |
| Zone Main | {L.get('zone_main', '')} |
| Max Height | {L.get('max_height_m', 'N/A')}m |
| Max FSI | {L.get('max_fsi', 'N/A')} |
| Front Setback | {L.get('setback_front_m', 'N/A')}m |
| Rear Setback | {L.get('setback_rear_m', 'N/A')}m |
| Side Setback | {L.get('setback_side_m', 'N/A')}m |

## Development Feasibility (Current Zoning)

| Metric | Value |
|--------|-------|
| Buildable Area | {L.get('buildable_area_sqft') or 0:,.0f} sqft |
| Max GFA | {L.get('max_gfa_sqft') or 0:,.0f} sqft |
| Estimated Floors | {L.get('estimated_floors') or 0} |
| **Estimated Units** | **{L.get('estimated_units') or 0}** |
| Price / Unit | {_fmt_price(L.get('price_per_unit'))} |
| Price / Buildable sqft | {_fmt_price(L.get('price_per_buildable_sqft'), decimals=2)} |

## Rezone Potential

| Field | Value |
|-------|-------|
| Potential Zone | **{L.get('potential_zone', 'N/A')}** |
| Potential Height | {L.get('potential_height_m', 'N/A')}m |
| Potential FSI | {L.get('potential_fsi', 'N/A')} |
| **Potential Units** | **{L.get('potential_units') or 0}** |
| Rezone Likelihood | **{L.get('rezone_likelihood', 'Unknown')}** |
| Potential Value | {_fmt_price(L.get('potential_value'))} |
| **Spread (Upside)** | **{_fmt_price(L.get('spread'))}** |

> **Rezone Reasoning:** {L.get('rezone_reasoning', 'N/A')}

## Score Breakdown

| Component | Score | Max |
|-----------|-------|-----|
| Zoning | {L.get('score_zoning', 0)} | 30 |
| Lot | {L.get('score_lot', 0)} | 20 |
| Location | {L.get('score_location', 0)} | 20 |
| Price | {L.get('score_price', 0)} | 15 |
| Market | {L.get('score_market', 0)} | 15 |
| **Total** | **{score}** | **100** |
{_llm_section(L)}
## Description

{L.get('description', 'No description available.')[:1000]}

---
[View on Realtor.ca]({L.get('listing_url', '#')})
*Analyzed: {RUN_TIMESTAMP}*
"""
    return md


def _llm_section(L: dict) -> str:
    """Render the Claude Haiku analysis block if enrichment ran."""
    thesis = L.get("llm_investment_thesis")
    if not thesis:
        return ""
    signal = L.get("llm_teardown_signal", "")
    reasoning = L.get("llm_teardown_reasoning", "")
    risks = L.get("llm_key_risks", "")
    flags = L.get("llm_description_flags") or []
    flags_str = ", ".join(flags) if flags else "None"
    return f"""
## AI Analysis (Claude Haiku)

> **Investment Thesis:** {thesis}

| | |
|-|-|
| Teardown Signal | **{signal}** |
| Teardown Reasoning | {reasoning} |
| Key Risks | {risks} |
| Description Flags | {flags_str} |
"""


def _fmt_price(val, decimals=0) -> str:
    """Format a number as a price string."""
    if val is None or val == 0:
        return "N/A"
    if decimals > 0:
        return f"${val:,.{decimals}f}"
    return f"${val:,.0f}"


def _star_rating(score: int) -> str:
    """Visual star rating based on score."""
    if score >= 80:
        return "***** (Excellent)"
    elif score >= 65:
        return "**** (Very Good)"
    elif score >= 50:
        return "*** (Good)"
    elif score >= 35:
        return "** (Fair)"
    else:
        return "* (Low)"
