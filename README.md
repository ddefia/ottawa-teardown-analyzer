# Ottawa Tear-Down Analyzer

Scrapes Ottawa real estate listings from realtor.ca, looks up each property's zoning via Ottawa's ArcGIS API, calculates development feasibility under Bylaw 2008-250, and scores each property 0–100 for tear-down/redevelopment potential. Top opportunities are saved as Obsidian markdown notes.

## How It Works

1. **Fetch** — `fetch_listings.py` uses a stealth Firefox browser (Camoufox) to solve realtor.ca's WAF challenge, then uses the session cookies to pull Ottawa listings from the internal API. Condos and protected properties are filtered out.
2. **Zone** — Each property's address is geocoded and cross-referenced with Ottawa's ArcGIS zoning layer to get the real zone code, height limits, and FSI.
3. **Feasibility** — Calculates buildable envelope, max GFA, estimated floors/units, and rezone potential (LRT proximity, arterial corridors, intensification areas).
4. **Score** — Ranks 0–100 across 5 dimensions: zoning quality, lot size/shape, location, price efficiency, and market signals.
5. **AI Analysis** — Optionally uses Claude Haiku to generate an investment thesis, teardown signal, and key risks for each top property.
6. **Output** — Saves Obsidian `.md` notes for all properties scoring ≥ 50, plus a full `results.json`.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/ddefia/ottawa-teardown-analyzer
cd ottawa-teardown-analyzer

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Install the stealth browser (one-time, ~200MB)
python3 -c "from camoufox.sync_api import Camoufox; pass" 2>/dev/null || python3 -m camoufox fetch
# OR if using scrapling:
python3 -c "import scrapling; print('ok')"

# 4. Configure your paths
cp .env.example .env
# Edit .env — set OBSIDIAN_VAULT to your vault path
# Optionally add ANTHROPIC_API_KEY for AI analysis

# 5. Load your .env and run
export $(cat .env | grep -v '#' | xargs)

# Fetch fresh listings (~30s)
python3 fetch_listings.py

# Analyze, score, and save to Obsidian (~60s)
python3 main.py
```

## Weekly Workflow

```bash
export $(cat .env | grep -v '#' | xargs)
python3 fetch_listings.py && python3 main.py
```

Results go to your Obsidian vault as `.md` files, plus `results.json` in the project folder.

## Scoring (0–100)

| Component | Max | What it measures |
|-----------|-----|-----------------|
| Zoning    | 30  | Zone density + rezone likelihood (LRT, arterials, intensification corridors) |
| Lot       | 20  | Size, frontage, corner lot, vacancy |
| Location  | 20  | Distance to LRT stations, arterial/intensification corridors |
| Price     | 15  | Price per potential buildable unit |
| Market    | 15  | Neighbourhood growth signals, zone density trends |

## AI Analysis (optional)

When `ANTHROPIC_API_KEY` is set, Claude Haiku enriches each top property (score ≥ 50) with:
- **Investment thesis** — one-sentence plain-English summary
- **Teardown signal** — HIGH / MEDIUM / LOW with reasoning
- **Key risks** — main concerns from the listing
- **Description flags** — red flags extracted from listing text

Cost: ~$0.001/property × ~80 top properties = **~$0.08/week**.

## Dependencies

| Package | Purpose |
|---------|---------|
| `scrapling` | Stealth Firefox browser (Camoufox) to solve realtor.ca's WAF |
| `curl_cffi` | Chrome TLS fingerprint for fast API calls after challenge is solved |
| `requests` | Ottawa ArcGIS zoning API calls |
| `anthropic` | Claude Haiku AI enrichment (optional) |

## Data Sources

- [realtor.ca](https://realtor.ca) — active MLS listings
- [Ottawa ArcGIS](https://maps.ottawa.ca/arcgis/rest/services/Zoning/MapServer) — official zoning layer
- Ottawa Zoning Bylaw 2008-250 — FSI, setback, and height limits (hardcoded lookup table)
- Ottawa LRT station coordinates — for proximity scoring
