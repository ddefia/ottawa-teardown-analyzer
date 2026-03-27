#!/usr/bin/env python3
"""
Ottawa Tear-Down Analyzer — Main Orchestrator
Scrapes listings → looks up zoning → calculates feasibility → scores → outputs.
"""
import json
import logging
import sys
import time

from config import OUTPUT_JSON, RUN_TIMESTAMP, SCORE_MINIMUM_FOR_OBSIDIAN
from scraper import scrape_ottawa_listings
from zoning import enrich_listing_with_zoning
from feasibility import calculate_feasibility
from scoring import score_listing
from obsidian import save_obsidian_summaries
from llm_enrichment import enrich_listings_with_llm

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def run():
    """Main pipeline."""
    start = time.time()
    log.info(f"=== Ottawa Tear-Down Analyzer — {RUN_TIMESTAMP} ===")

    # ── Step 1: Scrape listings ───────────────────────────────────────
    log.info("Step 1: Scraping Ottawa listings from realtor.ca...")
    listings = scrape_ottawa_listings()
    log.info(f"  → {len(listings)} redevelopment candidates found")

    if not listings:
        log.warning("No listings found. The realtor.ca API may be blocking requests.")
        log.info("Try again later or check your network connection.")
        return

    # ── Step 2: Zoning lookup ─────────────────────────────────────────
    log.info("Step 2: Looking up zoning for each property...")
    for i, listing in enumerate(listings):
        enrich_listing_with_zoning(listing)
        if (i + 1) % 25 == 0:
            log.info(f"  → Zoned {i + 1}/{len(listings)} properties")
            time.sleep(0.5)  # Rate limit for ArcGIS
    log.info(f"  → Zoning complete for {len(listings)} properties")

    # ── Step 3: Feasibility calculation ───────────────────────────────
    log.info("Step 3: Calculating development feasibility...")
    for listing in listings:
        calculate_feasibility(listing)

    # ── Step 4: Scoring ───────────────────────────────────────────────
    log.info("Step 4: Scoring properties...")
    for listing in listings:
        score_listing(listing)

    # ── Sort by score ─────────────────────────────────────────────────
    listings.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── Step 5: LLM enrichment (optional, requires ANTHROPIC_API_KEY) ─
    log.info("Step 5: LLM enrichment (top candidates)...")
    listings = enrich_listings_with_llm(listings)

    # ── Step 6: Output ────────────────────────────────────────────────
    log.info("Step 6: Generating output...")

    # JSON output
    output = {
        "run_timestamp": RUN_TIMESTAMP,
        "total_candidates": len(listings),
        "top_opportunities": len([l for l in listings if l.get("score", 0) >= SCORE_MINIMUM_FOR_OBSIDIAN]),
        "listings": listings,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"  → JSON saved to {OUTPUT_JSON}")

    # Obsidian markdown
    saved_count = save_obsidian_summaries(listings)
    log.info(f"  → {saved_count} Obsidian notes saved")

    # ── Summary ───────────────────────────────────────────────────────
    elapsed = time.time() - start
    _print_summary(listings, elapsed)


def _print_summary(listings: list[dict], elapsed: float):
    """Print a nice summary table to stdout."""
    print()
    print("=" * 80)
    print(f"  OTTAWA TEAR-DOWN ANALYZER — RESULTS ({RUN_TIMESTAMP})")
    print("=" * 80)
    print(f"  Total candidates analyzed: {len(listings)}")
    print(f"  Run time: {elapsed:.1f}s")
    print()

    top = [l for l in listings if l.get("score", 0) >= SCORE_MINIMUM_FOR_OBSIDIAN]
    if not top:
        print("  No properties scored >= 50. Try adjusting filters.")
        return

    print(f"  TOP {len(top)} OPPORTUNITIES (score >= {SCORE_MINIMUM_FOR_OBSIDIAN}):")
    print("-" * 80)
    print(f"  {'Score':>5} {'Price':>12} {'Units':>5} {'Pot.':>5} {'Zone':>6} "
          f"{'Rezone':>8} {'Spread':>12}  Address")
    print("-" * 80)

    for l in top[:30]:  # Show top 30
        score = l.get("score", 0)
        price = l.get("price", 0)
        units = l.get("estimated_units", 0)
        pot = l.get("potential_units", 0)
        zone = l.get("zone_main", "?")
        rezone = l.get("rezone_likelihood", "?")
        spread = l.get("spread", 0)
        addr = (l.get("address") or "Unknown")[:35]

        print(f"  {score:>5} {_fmt(price):>12} {units:>5} {pot:>5} {zone:>6} "
              f"{rezone:>8} {_fmt(spread):>12}  {addr}")

    print("-" * 80)
    print()

    # Top 5 detailed view
    print("  TOP 5 DETAILED:")
    for i, l in enumerate(top[:5], 1):
        print(f"\n  #{i} — {l.get('address', 'Unknown')} — Score: {l.get('score', 0)}/100")
        print(f"     Price: {_fmt(l.get('price'))} | Zone: {l.get('zone_code', '?')} | "
              f"Lot: {l.get('lot_size_sqft', 0):,.0f} sqft")
        print(f"     Current: {l.get('estimated_units', 0)} units | "
              f"Potential: {l.get('potential_units', 0)} units ({l.get('potential_zone', '?')})")
        print(f"     Spread: {_fmt(l.get('spread'))} | "
              f"Rezone: {l.get('rezone_likelihood', '?')}")
        print(f"     {l.get('rezone_reasoning', '')[:80]}")
        print(f"     {l.get('listing_url', '')}")


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        if val >= 1_000_000:
            return f"${val / 1_000_000:.1f}M"
        elif val >= 1000:
            return f"${val:,.0f}"
        else:
            return f"${val:,.0f}"
    return str(val)


if __name__ == "__main__":
    run()
