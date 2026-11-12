"""Data checks run before anything is published. ERRORS block publishing; WARNINGS are printed only.

Each message says what to do, so a failed weekly run can be fixed without reading code (see MAINTAINING.md).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from auction_outlook.model import Inputs

# The price source updates every one to three weeks, with a longer break over Christmas-January when the market
# barely trades. Old prices only print a warning; publishing is blocked only if the source looks to have stopped.
PRICE_WARN_DAYS = 10
PRICE_ERROR_DAYS = 45
RESULT_GRACE_DAYS = 3      # results are published on auction day; allow a few days to enter them
CURATED = "data/curated/"


def check_inputs(inp: Inputs, today: date) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    t = pd.Timestamp(today)

    last_price = inp.daily["date"].max()
    age = (t - last_price).days
    if age > PRICE_ERROR_DAYS:
        errors.append(f"NZU prices are {age} days old (last {last_price.date()}). The source repo "
                      f"(github.com/theecanmole/nzu) may not have updated; check it, then re-run.")
    elif age > PRICE_WARN_DAYS:
        warnings.append(f"NZU prices are {age} days old (last {last_price.date()}).")

    done = set(inp.auctions["auction_date"])
    missing = inp.settings[(inp.settings["auction_date"] < t - pd.Timedelta(f"{RESULT_GRACE_DAYS}D"))
                           & ~inp.settings["auction_date"].isin(done)]
    for _, s in missing.iterrows():
        errors.append(f"No result entered for the {s['auction_name']} auction ({s['auction_date'].date()}). "
                      f"Add it to {CURATED}auctions.csv (see the runbook).")

    ahead = inp.settings[inp.settings["auction_date"] > t].sort_values("auction_date")
    if len(ahead) < 2:
        errors.append(f"Fewer than two upcoming auctions in {CURATED}auction_settings.csv. Add the next auction "
                      f"update notice (date, units, floor, CCR).")
    for _, s in ahead.head(2).iterrows():
        if pd.isna(s.get("price_floor")):
            errors.append(f"No floor price for the {s['auction_name']} auction in {CURATED}auction_settings.csv.")
        reg = inp.regulations[inp.regulations["year"] == s["auction_date"].year]
        if reg.empty:
            warnings.append(f"No regulation loaded for {s['auction_date'].year}: the {s['auction_name']} floor comes "
                            f"from the notice only. Add its rows to {CURATED}auction_regulations.csv when it's made.")
    return errors, warnings
