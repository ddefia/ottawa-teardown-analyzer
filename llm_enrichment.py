"""
llm_enrichment.py — Claude Haiku enrichment for Ottawa Tear-Down Analyzer

Uses Claude Haiku to extract structured insights from listing descriptions:
  - Tear-down signal strength
  - Any dimensions/lot info mentioned in the text
  - Key risks or concerns
  - One-line plain-English investment thesis

Called optionally from main.py. Skipped if ANTHROPIC_API_KEY is not set.
Cost: ~$0.001 per property (Haiku). ~$0.35 for a full 336-listing run.
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return None
            _client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            log.warning("anthropic not installed. Run: pip3 install anthropic")
            return None
    return _client


def enrich_listings_with_llm(listings: list[dict]) -> list[dict]:
    """
    Enrich listings with Claude Haiku insights.
    Only runs if ANTHROPIC_API_KEY is set.
    Enriches top candidates (score >= 50) only to keep costs minimal.
    """
    client = _get_client()
    if not client:
        log.info("LLM enrichment skipped (no ANTHROPIC_API_KEY set)")
        return listings

    candidates = [l for l in listings if (l.get("score") or 0) >= 50]
    log.info(f"LLM: Enriching {len(candidates)} top candidates with Claude Haiku...")

    enriched = 0
    for listing in candidates:
        try:
            result = _enrich_one(client, listing)
            if result:
                listing.update(result)
                enriched += 1
        except Exception as e:
            log.warning(f"LLM enrichment failed for {listing.get('address', '')}: {e}")
        time.sleep(0.1)  # gentle rate limiting

    log.info(f"LLM: Enriched {enriched}/{len(candidates)} listings")
    return listings


def _enrich_one(client, listing: dict):
    """Call Claude Haiku to extract insights from a single listing."""
    address = listing.get("address", "")
    price = listing.get("price") or 0
    lot_sqft = listing.get("lot_size_sqft") or 0
    zone = listing.get("zone_code", "Unknown")
    desc = (listing.get("description") or "")[:800]
    prop_type = listing.get("property_type", "")
    year_built = listing.get("year_built") or "unknown"
    rezone = listing.get("rezone_likelihood", "Unknown")
    units_current = listing.get("estimated_units") or 0
    units_potential = listing.get("potential_units") or 0

    prompt = f"""You are a real estate development analyst in Ottawa, Canada.
Analyze this property listing for tear-down/redevelopment potential.

Property:
- Address: {address}
- Price: ${price:,.0f}
- Property Type: {prop_type}
- Year Built: {year_built}
- Lot Size: {lot_sqft:,.0f} sqft
- Zone: {zone}
- Estimated Units (current zoning): {units_current}
- Potential Units (after rezone): {units_potential}
- Rezone Likelihood: {rezone}
- Description: {desc}

Return ONLY a JSON object with these exact keys:
{{
  "teardown_signal": "HIGH" | "MEDIUM" | "LOW",
  "teardown_reasoning": "<one sentence why>",
  "key_risks": "<one sentence: main risks or concerns>",
  "investment_thesis": "<one sentence plain-English summary for an investor>",
  "description_lot_sqft": <number or null if not mentioned in description>,
  "description_flags": ["<any red flags mentioned in description>"]
}}
Return only valid JSON, no explanation."""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data = json.loads(raw)
    return {
        "llm_teardown_signal": data.get("teardown_signal"),
        "llm_teardown_reasoning": data.get("teardown_reasoning"),
        "llm_key_risks": data.get("key_risks"),
        "llm_investment_thesis": data.get("investment_thesis"),
        "llm_description_lot_sqft": data.get("description_lot_sqft"),
        "llm_description_flags": data.get("description_flags", []),
    }
