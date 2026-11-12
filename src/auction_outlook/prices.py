"""Download and clean the NZU daily price series.

Source: https://github.com/theecanmole/nzu (ODC-PDDL, public domain), file `spotprices.csv` (irregular dates, not
infilled). The maintainer updates it every one to three weeks, with a longer break over Christmas-January when the
market barely trades.

To download and clean the prices:
  uv run python -m auction_outlook.prices
To re-clean the last download without downloading again:
  uv run python -m auction_outlook.prices --offline

Writes data/processed/nzu_prices.csv (one row per trading date) and nzu_prices_meta.json (source, fetch time, file
hash, and whether the maintainer revised any past prices). The raw download goes to data/raw/ (not committed).

Cleaning is deliberately light: unparseable or non-positive rows are dropped, duplicate dates keep the last entry, and
nothing is infilled. Large moves are kept: big jumps in this market are real policy shocks, not data errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from auction_outlook import PROCESSED, RAW

SOURCE_URL = "https://raw.githubusercontent.com/theecanmole/nzu/master/spotprices.csv"
RAW_FILE = RAW / "spotprices.csv"
PROCESSED_FILE = PROCESSED / "nzu_prices.csv"
META_FILE = PROCESSED / "nzu_prices_meta.json"
LARGE_MOVE = 0.10  # |log return| above this is flagged, never removed


def era(date: pd.Series) -> pd.Series:
    return pd.Series(np.select([date < "2018-01-01", date < "2021-01-01"], ["pre-2018 (sparse)", "2018-2020"],
                               default="2021+ (auctions)"), index=date.index)


def fetch(url: str = SOURCE_URL, timeout: int = 60) -> None:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "nzets-auction-outlook"})
    resp.raise_for_status()
    RAW.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_bytes(resp.content)


def clean(raw_path=RAW_FILE) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(raw_path, dtype=str)
    raw.columns = [c.strip().lower() for c in raw.columns]
    report: dict = {"raw_rows": len(raw)}

    date = pd.to_datetime(raw["date"].str.strip(), errors="coerce", format="%Y-%m-%d")
    price = pd.to_numeric(raw["price"].str.strip(), errors="coerce")
    bad = date.isna() | price.isna() | (price <= 0)
    report["dropped_unparseable_or_nonpositive"] = int(bad.sum())

    df = pd.DataFrame({"date": date, "price": price})[~bad]
    n = len(df)
    df = df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    report["dropped_duplicate_dates"] = n - len(df)

    df["gap_days"] = df["date"].diff().dt.days.astype("Int64")
    df["log_return"] = np.log(df["price"]).diff()
    df["weekend"] = df["date"].dt.dayofweek >= 5
    df["large_move"] = df["log_return"].abs() > LARGE_MOVE
    df["era"] = era(df["date"])

    report.update(
        clean_rows=len(df),
        first_date=df["date"].min().date().isoformat(),
        last_date=df["date"].max().date().isoformat(),
        last_price=float(df["price"].iloc[-1]),
        weekend_rows=int(df["weekend"].sum()),
        large_moves=int(df["large_move"].sum()),
        large_moves_2018plus=int(df.loc[df["date"] >= "2018-01-01", "large_move"].sum()),
        max_gap_days_2018plus=int(df.loc[df["date"] >= "2018-01-01", "gap_days"].max()),
    )
    return df, report


def check_revisions(df: pd.DataFrame) -> dict:
    """Compare against the previously saved series: did the source revise history?"""
    if not PROCESSED_FILE.exists():
        return {"previous_file": False}
    old = pd.read_csv(PROCESSED_FILE, parse_dates=["date"])[["date", "price"]]
    m = old.merge(df[["date", "price"]], on="date", how="outer", suffixes=("_old", "_new"))
    common = m.dropna(subset=["price_old", "price_new"])
    changed = common[~np.isclose(common["price_old"], common["price_new"])]
    return {
        "previous_file": True,
        "rows_added": int(m["price_old"].isna().sum()),
        "rows_removed": int(m["price_new"].isna().sum()),
        "historical_prices_changed": len(changed),
        "changed_examples": [{"date": d.date().isoformat(), "old": o, "new": n}
                             for d, o, n in changed[["date", "price_old", "price_new"]].head(10).itertuples(index=False)],
    }


def update(offline: bool = False) -> tuple[dict, dict]:
    """Download (unless offline), clean, and write the processed series and metadata. Returns (report, revisions)."""
    if offline:
        if not RAW_FILE.exists():
            raise SystemExit(f"No raw file at {RAW_FILE}; run without --offline first.")
        fetched_at = None
    else:
        fetch()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    df, report = clean(RAW_FILE)
    revisions = check_revisions(df)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED_FILE, index=False, date_format="%Y-%m-%d")
    META_FILE.write_text(json.dumps({
        "source_url": SOURCE_URL,
        "licence": "ODC-PDDL (public domain)",
        "fetched_at_utc": fetched_at,
        "raw_sha256": hashlib.sha256(RAW_FILE.read_bytes()).hexdigest(),
        "cleaning": report,
        "revisions_vs_previous": revisions,
    }, indent=2))
    return report, revisions


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Download and clean NZU prices")
    ap.add_argument("--offline", action="store_true", help="re-clean the last download")
    rep, rev = update(ap.parse_args().offline)
    print(f"{rep['clean_rows']} rows, {rep['first_date']} to {rep['last_date']} (last price ${rep['last_price']:.2f})")
