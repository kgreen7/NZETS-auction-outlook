"""The auction-outlook method (frozen: version 1.0, 12 Nov 2026).

To change the method: edit it deliberately, bump MODEL_VERSION, regenerate the test expectations
(tests/test_outlook.py explains how) and record the change in CHANGELOG.md. Every published estimate carries the
model version, so past estimates stay traceable.

P(auction sells units) = P(price on the day before >= floor known at the time) x q
  price range: absolute k-week log price changes over the last 156 weeks, applied symmetrically to today's price
               (falls back to a normal band with 52-week volatility while fewer than 26 changes exist)
  q:           share of past auctions with price >= floor that sold units, Beta(1,1) prior: (k + 1) / (n + 2)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

MODEL_VERSION = "auction-outlook 1.0 (2026-11-12): 3-year empirical price range x reserve-clearing rate"
QUANTILES = np.round(np.arange(0.05, 0.951, 0.05), 2)  # 19 levels: P5 ... P95
Z = norm.ppf(QUANTILES)
WINDOW_WEEKS = 156
MIN_CHANGES = 26
FALLBACK_VOL_WEEKS = 52
MIN_HISTORY_WEEKS = 60      # backtest origins need this much weekly history
NAIVE_BELOW_FLOOR = 0.02    # the simple rule's chance when the price is below the floor


@dataclass
class Inputs:
    weekly: pd.DataFrame          # index week (Friday), columns price, log_price
    daily: pd.DataFrame           # date, price
    auctions: pd.DataFrame        # results
    settings: pd.DataFrame        # settings incl. upcoming auctions
    regulations: pd.DataFrame
    decisions: pd.DataFrame


def weekly_prices(daily: pd.DataFrame, start: str = "2018-01-01", max_fill_weeks: int = 5) -> pd.DataFrame:
    """Friday series of the last observed price in each week; quiet weeks carry the last price (at most 5 weeks)."""
    d = daily[daily["date"] >= start].set_index("date")["price"]
    w = d.resample("W-FRI").last()
    out = pd.DataFrame({"price": w.ffill(limit=max_fill_weeks)})
    out["log_price"] = np.log(out["price"])
    out.index.name = "week"
    return out


def price_band(y: np.ndarray, h: int) -> np.ndarray:
    """(h, 19) log-price quantiles for 1..h weeks ahead."""
    r = np.diff(y)[-FALLBACK_VOL_WEEKS:]
    k = np.arange(1, h + 1)[:, None]
    out = y[-1] + r.std(ddof=1) * np.sqrt(k) * Z[None, :]
    level, sign = np.abs(2 * QUANTILES - 1), np.sign(QUANTILES - 0.5)
    for kk in range(1, h + 1):
        yy = y[-(WINDOW_WEEKS + kk):]
        ch = np.abs(yy[kk:] - yy[:-kk])
        if len(ch) >= MIN_CHANGES:
            out[kk - 1] = y[-1] + sign * np.quantile(ch, level)
    return out


def prob_above(qrow: np.ndarray, x: float) -> float:
    """P(log price > x) from a row of quantiles; normal tails beyond P5/P95."""
    if qrow[0] <= x <= qrow[-1]:
        cdf = np.interp(x, qrow, QUANTILES)
    else:
        med = qrow[QUANTILES.tolist().index(0.5)]
        sig = (qrow[-1] - med) / norm.ppf(0.95) if x > qrow[-1] else (med - qrow[0]) / norm.ppf(0.95)
        cdf = norm.cdf((x - med) / max(sig, 1e-9))
    return float(1 - cdf)


def known_floors(regs: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Regulation rows with the date each became public: announcement, else the decision's upper-bound date,
    else the in-force date."""
    regs = regs.copy()
    first_year = regs.groupby(["sr_number", "in_force_date"])["year"].transform("min")
    bound = first_year.map(decisions.set_index("year_from")["known_by"].to_dict())
    regs["known_date"] = regs["announced_date"].fillna(bound).fillna(regs["in_force_date"])
    return regs


def floor_known_at(regs: pd.DataFrame, origin: pd.Timestamp, year: int) -> float | None:
    c = regs[(regs["year"] == year) & (regs["known_date"] <= origin)]
    return None if c.empty else float(c.sort_values(["known_date", "in_force_date"]).iloc[-1]["price_floor"])


def reserve_rate(au: pd.DataFrame, origin: pd.Timestamp) -> float:
    past = au[(au["auction_date"] < origin) & (au["spot_prev_price"] >= au["price_floor"])]
    return (1 + int(past["any_units_sold"].sum())) / (2 + len(past))


def backtest(inp: Inputs, lead_weeks: int) -> pd.DataFrame:
    """For each past auction: the estimate made `lead_weeks` before, using only what was known then."""
    w, au = inp.weekly, inp.auctions
    y, idx = w["log_price"].to_numpy(), w.index
    regs = known_floors(inp.regulations, inp.decisions)
    rows = []
    for _, a in au.iterrows():
        target = a["auction_date"] - pd.Timedelta("1D")
        o = idx.searchsorted(target - pd.Timedelta(f"{lead_weeks}W"), side="right") - 1
        if o < MIN_HISTORY_WEEKS:
            continue
        origin = idx[o]
        h = max(1, int(round((target - origin).days / 7)))
        floor = floor_known_at(regs, origin, a["auction_date"].year)
        if floor is None:
            continue
        q = reserve_rate(au, origin)
        price_then = float(np.exp(y[o]))
        p_above = prob_above(price_band(y[: o + 1], h)[h - 1], np.log(floor))
        base = au[au["auction_date"] < origin]
        rows.append({"auction": a["auction_name"], "auction_date": a["auction_date"], "origin": origin,
                     "price_at_origin": price_then, "floor_known": floor, "floor_actual": a["price_floor"],
                     "q_reserve": q, "p_above": p_above, "p_clear": p_above * q,
                     "p_clear_naive": q if price_then >= floor else NAIVE_BELOW_FLOOR,
                     "p_clear_baserate": (1 + base["any_units_sold"].sum()) / (2 + len(base)),
                     "cleared": int(a["any_units_sold"]), "outcome": a["outcome"],
                     "clearing_price": a["clearing_price"], "spot_prev_price": a["spot_prev_price"]})
    return pd.DataFrame(rows)


def brier(bt: pd.DataFrame) -> dict[str, float]:
    out = {}
    for name, col in [("model", "p_clear"), ("base_rate", "p_clear_baserate"), ("above_floor_rule", "p_clear_naive")]:
        p = bt[col].clip(0.01, 0.99)
        out[name] = float(((p - bt["cleared"]) ** 2).mean())
    return out


def upcoming(inp: Inputs, n: int = 2) -> pd.DataFrame:
    """Estimates for the next n scheduled auctions from the latest weekly price."""
    w = inp.weekly
    y, origin = w["log_price"].to_numpy(), w.index[-1]
    q = reserve_rate(inp.auctions, origin + pd.Timedelta("1D"))
    rows = []
    for _, s in inp.settings[inp.settings["auction_date"] > origin].sort_values("auction_date").head(n).iterrows():
        h = max(1, int(round((s["auction_date"] - pd.Timedelta("1D") - origin).days / 7)))
        band = price_band(y, h)[h - 1]
        p_above = prob_above(band, np.log(s["price_floor"]))
        rows.append({"auction": s["auction_name"], "auction_date": s["auction_date"], "weeks_ahead": h,
                     "floor": float(s["price_floor"]), "q_reserve": q, "p_above": p_above, "p_clear": p_above * q,
                     "band": np.exp(band)})
    return pd.DataFrame(rows)
