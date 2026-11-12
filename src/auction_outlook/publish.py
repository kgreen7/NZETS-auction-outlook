"""Update the auction outlook. The only command the website depends on.

To run it:
  uv run python -m auction_outlook.publish [--site <website folder>] [--offline] [--no-log]

Steps
  1. refresh NZU prices from github.com/theecanmole/nzu (skipped with --offline)
  2. rebuild the auction tables from data/curated/
  3. data checks (errors stop here: nothing is published)
  4. build the JSON and check its structure
  5. append the estimates to outputs/auction_outlook_log.csv (the public, dated record)
  6. write outputs/auction-outlook.json, and copy it to <site>/public/data/insights/ if --site or NZETS_SITE_DIR

Exit code 1 if anything blocks publishing. Weekly GitHub Action: .github/workflows/weekly-update.yml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from auction_outlook import CURATED, OUTPUTS, PROCESSED, ROOT
from auction_outlook.checks import check_inputs
from auction_outlook.export import build, load_inputs, validate_schema
from auction_outlook.model import MODEL_VERSION

OUT_JSON = OUTPUTS / "auction-outlook.json"
LOG = OUTPUTS / "auction_outlook_log.csv"
SITE_PATH = Path("public") / "data" / "insights" / "auction-outlook.json"


def log_estimates(data: dict) -> pd.DataFrame:
    """Append this run's estimates (one row per upcoming auction per price date; re-runs overwrite)."""
    rows = pd.DataFrame([{"price_as_of": data["price_as_of"], "generated": data["generated"], "auction": a["name"],
                          "auction_date": a["date"], "floor": a["floor"], "latest_price": data["latest_price"],
                          "p_above_floor": a["p_above_floor"], "p_clear": a["p_clear"],
                          "model": data["model_version"]} for a in data["next_auctions"]]).astype(str)
    if LOG.exists():
        rows = pd.concat([pd.read_csv(LOG, dtype=str), rows]).drop_duplicates(["price_as_of", "auction"], keep="last")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(LOG, index=False)
    return rows


def run(offline: bool = False, site: str | None = None, write_log: bool = True, today: date | None = None) -> int:
    today = today or date.today()
    if not offline:
        from auction_outlook import prices
        report, rev = prices.update()
        print(f"1. Prices: {report['clean_rows']} rows to {report['last_date']} (${report['last_price']:.2f}); "
              f"+{rev.get('rows_added', 0)} new, {rev.get('historical_prices_changed', 0)} revised")
    else:
        print("1. Prices: skipped (--offline)")

    from auction_outlook import auctions
    notes = auctions.rebuild()
    flagged = [n for n in notes if n.startswith("CHECK")]
    print(f"2. Auction tables rebuilt from data/curated/ ({len(flagged)} consistency flags)")

    inp = load_inputs(PROCESSED, CURATED)
    errors, warnings = check_inputs(inp, today)
    warnings += flagged
    data = build(inp, today) if not errors else None
    if data is not None:
        data["log"] = []
        errors += validate_schema(data)

    for w in warnings:
        print(f"   WARNING: {w}")
    if errors:
        print("3. BLOCKED: nothing published.")
        for e in errors:
            print(f"   ERROR: {e}")
        return 1
    print(f"3-4. Checks passed; JSON valid (schema {data['schema_version']}, {MODEL_VERSION})")

    if write_log:
        log = log_estimates(data)
    else:  # dry run: keep the existing record, add nothing
        log = pd.read_csv(LOG, dtype=str) if LOG.exists() else pd.DataFrame()
    data["log"] = log.to_dict(orient="records")
    text = json.dumps(data, indent=1, ensure_ascii=False)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(text, encoding="utf-8")
    print(f"5-6. Wrote {OUT_JSON.relative_to(ROOT)}" + ("" if write_log else " (log not updated)"))
    for a in data["next_auctions"]:
        print(f"     {a['name']:<15} {a['date']}  floor ${a['floor']:.0f}  chance of selling units {a['p_clear']:.1%}")
    if site:
        dest = Path(site) / SITE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"     Copied to {dest}")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Update the NZ ETS auction outlook")
    ap.add_argument("--site", default=os.environ.get("NZETS_SITE_DIR"), help="website folder (copies the JSON)")
    ap.add_argument("--offline", action="store_true", help="don't download prices; use the last download")
    ap.add_argument("--no-log", action="store_true", help="don't append to the published-estimates log (dry runs)")
    args = ap.parse_args(argv)
    sys.exit(run(offline=args.offline, site=args.site, write_log=not args.no_log))


if __name__ == "__main__":
    main()
