"""Build and validate outputs/auction-outlook.json (the file kapiticlimate.com/insights reads).

SCHEMA_VERSION changes only when the JSON's structure changes in a way readers must follow. Adding optional fields
doesn't need a bump; renaming or removing does.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from auction_outlook.model import MODEL_VERSION, QUANTILES, Inputs, backtest, brier, price_band, upcoming, weekly_prices

SCHEMA_VERSION = 1
LEAD_WEEKS = 12            # track record: estimates made about three months before each auction
HISTORY_FROM = "2021-01-01"
FAN_Q = [0.10, 0.25, 0.50, 0.75, 0.90]
OUTCOME_LABEL = {"cleared_full": "Cleared", "cleared_partial": "Partly cleared",
                 "declined_min_price": "Bids below reserve", "no_bids": "No valid bids"}
SOURCES = {"prices": "github.com/theecanmole/nzu (public domain)",
           "auctions": "etsauctions.govt.nz notices and results; Climate Change (Auctions, Limits, and Price Controls "
                       "for Units) Regulations"}


def load_inputs(proc: Path, curated: Path | None = None) -> Inputs:
    """The five tables the outlook depends on: prices and the two auction tables from `proc`, and the regulations
    and settings decisions from `curated` (defaults to `proc`, as in the test snapshot)."""
    curated = curated or proc
    daily = pd.read_csv(proc / "nzu_prices.csv", parse_dates=["date"])[["date", "price"]].dropna()
    au = pd.read_csv(proc / "auctions.csv", parse_dates=["auction_date"])
    sett = pd.read_csv(proc / "auction_settings.csv", parse_dates=["auction_date"])
    regs = pd.read_csv(curated / "auction_regulations.csv",
                       parse_dates=["announced_date", "made_date", "gazette_date", "in_force_date"])
    dec = pd.read_csv(curated / "ets_settings_decisions.csv",
                      parse_dates=["announced_date", "known_by", "effective_from"])
    return Inputs(weekly=weekly_prices(daily), daily=daily, auctions=au, settings=sett, regulations=regs, decisions=dec)


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def build(inp: Inputs, today: date | None = None) -> dict:
    today = today or date.today()
    w = inp.weekly
    y, idx = w["log_price"].to_numpy(), w.index
    last = inp.daily.sort_values("date").iloc[-1]
    qi = [int(np.argmin(np.abs(QUANTILES - q))) for q in FAN_Q]

    nxt = upcoming(inp, 2)
    h_max = int(nxt["weeks_ahead"].max())
    band = np.exp(price_band(y, h_max))[:, qi]
    fan = [{"date": str(idx[-1].date()), **{f"p{int(q * 100)}": _r(np.exp(y[-1])) for q in FAN_Q}}]
    fan += [{"date": str((idx[-1] + pd.Timedelta(f"{k}W")).date()), **{f"p{int(q * 100)}": _r(v) for q, v in zip(FAN_Q, row)}}
            for k, row in enumerate(band, start=1)]

    bt = backtest(inp, LEAD_WEEKS)
    hist = w.loc[w.index >= HISTORY_FROM, "price"]
    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "generated": str(today),
        "price_as_of": str(pd.Timestamp(last["date"]).date()),
        "latest_price": _r(last["price"]),
        "model": {"name": "Empirical 3-year price ranges x reserve-clearing rate",
                  "price_band": "Range of actual k-week NZU price moves over the last 3 years, centred on today's price",
                  "reserve_clear_rate": _r(nxt["q_reserve"].iloc[0], 3),
                  "reserve_clear_basis": "Share of past auctions that sold units when the price was above the floor "
                                         "(Beta(1,1) prior, so (cleared + 1) / (auctions + 2))"},
        "next_auctions": [{"name": a["auction"], "date": str(a["auction_date"].date()), "floor": _r(a["floor"]),
                           "weeks_ahead": int(a["weeks_ahead"]), "p_above_floor": _r(a["p_above"], 3),
                           "p_clear": _r(a["p_clear"], 3), "p_bids_clear_reserve": _r(a["q_reserve"], 3),
                           "price_p10": _r(a["band"][qi[0]]), "price_p50": _r(a["band"][qi[2]]),
                           "price_p90": _r(a["band"][qi[4]])} for _, a in nxt.iterrows()],
        "fan": fan,
        "history": [{"date": str(dt.date()), "price": _r(p)} for dt, p in hist.items()],
        "track_record": [{"name": r["auction"], "date": str(r["auction_date"].date()), "floor": _r(r["floor_actual"]),
                          "price_lead_before": _r(r["price_at_origin"]), "price_day_before": _r(r["spot_prev_price"]),
                          "clearing_price": _r(r["clearing_price"]), "p_clear_lead": _r(r["p_clear"], 3),
                          "cleared": bool(r["cleared"]), "outcome": OUTCOME_LABEL.get(r["outcome"], r["outcome"])}
                         for _, r in bt.iterrows()],
        "lead_weeks": LEAD_WEEKS,
        "scores": {k: _r(v, 3) for k, v in brier(bt).items()} | {"n": int(len(bt))},
        "sources": SOURCES,
    }


# What components/insights/outlookData.ts expects (field -> type). Checked before anything is published.
REQUIRED = {
    "schema_version": int, "model_version": str, "generated": str, "price_as_of": str, "latest_price": float,
    "model": dict, "next_auctions": list, "fan": list, "history": list, "track_record": list, "lead_weeks": int,
    "scores": dict, "sources": dict, "log": list,
}
NEXT_FIELDS = {"name": str, "date": str, "floor": float, "weeks_ahead": int, "p_above_floor": float, "p_clear": float,
               "p_bids_clear_reserve": float, "price_p10": float, "price_p50": float, "price_p90": float}
TRACK_FIELDS = {"name": str, "date": str, "floor": float, "p_clear_lead": float, "cleared": bool, "outcome": str}


def _type_ok(v, t) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) if t is float else isinstance(v, t)


def validate_schema(data: dict) -> list[str]:
    errs = [f"missing or wrong type: {k}" for k, t in REQUIRED.items() if k not in data or not _type_ok(data[k], t)]
    if errs:
        return errs
    if data["schema_version"] != SCHEMA_VERSION:
        errs.append(f"schema_version {data['schema_version']} != {SCHEMA_VERSION}")
    if len(data["next_auctions"]) != 2:
        errs.append(f"expected 2 upcoming auctions, got {len(data['next_auctions'])}")
    for a in data["next_auctions"]:
        errs += [f"next_auctions {a.get('name')}: {k}" for k, t in NEXT_FIELDS.items() if not _type_ok(a.get(k), t)]
        for k in ("p_above_floor", "p_clear", "p_bids_clear_reserve"):
            if _type_ok(a.get(k), float) and not 0 <= a[k] <= 1:
                errs.append(f"next_auctions {a['name']}: {k} outside 0-1")
        if all(_type_ok(a.get(k), float) for k in ("price_p10", "price_p50", "price_p90")) and not (
                a["price_p10"] <= a["price_p50"] <= a["price_p90"]):
            errs.append(f"next_auctions {a['name']}: price range out of order")
    for r in data["track_record"]:
        errs += [f"track_record {r.get('name')}: {k}" for k, t in TRACK_FIELDS.items() if not _type_ok(r.get(k), t)]
    if any(not (f["p10"] <= f["p50"] <= f["p90"]) for f in data["fan"]):
        errs.append("fan: quantiles out of order")
    if not data["history"]:
        errs.append("history is empty")
    return errs
