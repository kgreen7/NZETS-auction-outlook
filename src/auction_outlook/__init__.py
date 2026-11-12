"""NZ ETS auction outlook: the chance the next two NZ ETS auctions sell units.

  prices.py    download and clean NZU prices (github.com/theecanmole/nzu, public domain)
  auctions.py  build the auction tables from the hand-entered CSVs in data/curated/
  model.py     the method (frozen; MODEL_VERSION)
  checks.py    data checks that block publishing (stale prices, missing auction results or notices)
  export.py    builds and validates outputs/auction-outlook.json
  publish.py   the single entry point: uv run python -m auction_outlook.publish
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURATED = ROOT / "data" / "curated"
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
OUTPUTS = ROOT / "outputs"
