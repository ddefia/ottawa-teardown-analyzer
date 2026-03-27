# Ottawa Tear-Down Analyzer

Scrapes Ottawa real estate listings, analyzes each property for tear-down/rebuild potential under Ottawa zoning laws, scores and ranks opportunities, and saves results as Obsidian markdown notes.

## How It Works

1. **Scrape** — Pulls active Ottawa listings from realtor.ca's internal API
2. **Zone** — Looks up each property's zoning via Ottawa's ArcGIS service
3. **Analyze** — Calculates buildable envelope, max units, rezone potential
4. **Score** — Ranks properties 0-100 across zoning, lot, location, price, market
5. **Output** — Saves top opportunities as Obsidian notes + full JSON

## Quick Start

```bash
cd ottawa-teardown-analyzer
python3 main.py
```

Results appear in:
- `results.json` — full analysis data
- Obsidian vault at configured path — markdown notes for score >= 50

## Scoring (0-100)

| Component | Max | What it measures |
|-----------|-----|------------------|
| Zoning | 30 | Current zone quality + rezone likelihood |
| Lot | 20 | Size, shape, vacancy |
| Location | 20 | LRT proximity, arterials, intensification |
| Price | 15 | Price per potential unit |
| Market | 15 | Neighbourhood growth, vacancy rates |

## Dependencies

- Python 3.9+
- `requests` (HTTP)
- `pandas` (optional, for future data analysis)

## Data Sources

- [realtor.ca](https://realtor.ca) — listing data
- [Ottawa ArcGIS](https://maps.ottawa.ca/arcgis/rest/services/Zoning/MapServer) — zoning
- Ottawa Bylaw 2008-250 — FSI, setbacks, height limits
