"""NZ ETS auction results and settings: hand-entered CSVs in data/curated/ -> data/processed/.

Sources: etsauctions.govt.nz results pages and auction update notices; the Climate Change (Auctions, Limits, and Price
Controls for Units) Regulations (the source of truth for floor and CCR trigger prices at any date); and the dates each
annual settings decision became public (data/curated/ets_settings_decisions.csv).

To rebuild the tables and print the consistency checks:
  uv run python -m auction_outlook.auctions
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from auction_outlook import CURATED, PROCESSED

FOLDER = CURATED
SOURCE_LABEL = {"res": "curated/auctions.csv", "sett": "curated/auction_settings.csv"}


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    res = pd.read_csv(FOLDER / "auctions.csv",
                      parse_dates=["auction_date", "published_date", "settings_published_date", "spot_prev_date"])
    sett = pd.read_csv(FOLDER / "auction_settings.csv", parse_dates=["auction_date", "notice_published_date"])
    res = res.sort_values("auction_date").reset_index(drop=True)
    sett = sett.sort_values("auction_date").reset_index(drop=True)
    return complete(res, sett), sett


# Fields a new results row needs (from the etsauctions.govt.nz results page); everything else can be left blank
# and is derived by complete(). Bid statistics (participants, num_bids, cover ratios...) are optional.
REQUIRED_RESULT_FIELDS = ["auction_name", "auction_date", "units_sold", "source_url"]   # plus outcome or notice_outcome
OUTCOMES = {"cleared_full", "cleared_partial", "declined_min_price", "no_bids"}


def _fill(df: pd.DataFrame, col: str, values) -> None:
    """Fill only blanks: values entered by hand are never overwritten."""
    if col not in df:
        df[col] = values
    else:
        df[col] = df[col].where(df[col].notna(), values)


def complete(res: pd.DataFrame, sett: pd.DataFrame) -> pd.DataFrame:
    """Derive the computed columns of the results table where they are blank (e.g. a newly entered auction)."""
    res = res.copy()
    missing = [c for c in REQUIRED_RESULT_FIELDS if c not in res or res[c].isna().any()]
    if missing:
        raise ValueError(f"auctions.csv: required fields blank or missing: {missing}")
    for col in ("outcome", "notice_outcome"):
        if col not in res:
            res[col] = None
    _fill(res, "outcome", res["notice_outcome"])
    if res["outcome"].isna().any():
        raise ValueError(f"auctions.csv: enter notice_outcome for {res.loc[res['outcome'].isna(), 'auction_name'].tolist()}")
    bad = set(res["outcome"]) - OUTCOMES
    if bad:
        raise ValueError(f"auctions.csv: outcome must be one of {sorted(OUTCOMES)}; got {sorted(bad)}")
    s = res[["auction_date"]].merge(sett, on="auction_date", how="left")
    for col in ["units_available", "unsold_from_previous", "ccr_tier1_units", "ccr_tier1_trigger", "ccr_tier2_units",
                "ccr_tier2_trigger", "price_floor"]:
        _fill(res, col, s[col])
    _fill(res, "settings_published_date", s["notice_published_date"])
    _fill(res, "floor_source", np.where(res["price_floor"].notna(), "auction update notice", None))
    _fill(res, "published_date", res["auction_date"])
    _fill(res, "year", res["auction_date"].dt.year)
    _fill(res, "outcome", res["notice_outcome"])
    _fill(res, "ccr_units_total", res["ccr_tier1_units"].fillna(0) + res["ccr_tier2_units"].fillna(0))
    _fill(res, "non_ccr_units", res["units_available"] + res["unsold_from_previous"])
    _fill(res, "total_units_incl_ccr", res["non_ccr_units"] + res["ccr_units_total"])
    _fill(res, "total_auction_units_published", res["total_units_incl_ccr"])   # results pages count CCR units offered
    _fill(res, "units_unsold", res["total_auction_units_published"] - res["units_sold"])
    _fill(res, "ccr_units_sold", 0)
    _fill(res, "ccr_triggered", res["ccr_units_sold"] > 0)
    _fill(res, "non_ccr_unsold", res["non_ccr_units"] - (res["units_sold"] - res["ccr_units_sold"]))
    _fill(res, "share_non_ccr_sold", (res["units_sold"] - res["ccr_units_sold"]) / res["non_ccr_units"])
    _fill(res, "any_units_sold", res["units_sold"] > 0)
    # spot price on the last trading day before the auction, from our cleaned series
    try:
        px = pd.read_csv(PROCESSED / "nzu_prices.csv", parse_dates=["date"])[["date", "price"]].sort_values("date")
        prev = pd.merge_asof(res[["auction_date"]].assign(t=res["auction_date"] - pd.Timedelta("1D")).sort_values("t"),
                             px, left_on="t", right_on="date", direction="backward").set_index("auction_date")
        _fill(res, "spot_prev_date", res["auction_date"].map(prev["date"]))
        _fill(res, "spot_prev_price", res["auction_date"].map(prev["price"]))
    except FileNotFoundError:
        pass
    _fill(res, "spot_minus_floor", res["spot_prev_price"] - res["price_floor"])
    _fill(res, "clearing_minus_spot", res["clearing_price"] - res["spot_prev_price"])
    res["any_units_sold"] = res["any_units_sold"].astype(bool)
    res["ccr_triggered"] = res["ccr_triggered"].astype(bool)
    return res


def validate(res: pd.DataFrame, sett: pd.DataFrame) -> list[str]:
    """Internal-consistency and cross-table checks. Returns human-readable findings ('OK ...' or 'CHECK ...')."""
    out = []

    def check(name, ok: pd.Series, cols=("auction_name",)):
        bad = res.loc[~ok.fillna(False), list(cols)]
        out.append(f"OK   {name}" if bad.empty else f"CHECK {name}: {bad.to_dict('records')}")

    check("units sold + unsold = total offered", res.units_sold + res.units_unsold == res.total_auction_units_published)
    check("non-CCR units = available + carried forward", res.non_ccr_units == res.units_available + res.unsold_from_previous)
    check("CCR tier1 + tier2 = CCR total", res.ccr_tier1_units + res.ccr_tier2_units.fillna(0) == res.ccr_units_total)
    prev = res.groupby(res.auction_date.dt.year, group_keys=False)["non_ccr_unsold"].shift().fillna(0)
    check("unsold non-CCR units carried to next auction in same year", res.unsold_from_previous == prev)
    cleared = res.clearing_price.notna()
    check("clearing price >= floor", ~cleared | (res.clearing_price >= res.price_floor - 1e-9))
    check("no clearing price => nothing sold", cleared | (res.units_sold == 0))
    check("spot price date is before auction date", res.spot_prev_date < res.auction_date)

    # one row per quarterly auction since March 2021, none missing
    expected = pd.period_range("2021Q1", res.auction_date.max().to_period("Q"), freq="Q")
    missing = sorted(set(expected) - set(res.auction_date.dt.to_period("Q")))
    out.append("OK   no missing auctions" if not missing else f"CHECK missing auctions: {[str(m) for m in missing]}")

    # results table vs settings table
    m = res.merge(sett, on="auction_date", suffixes=("", "_s"), how="left")
    for col in ["units_available", "unsold_from_previous", "price_floor", "ccr_tier1_units",
                "ccr_tier1_trigger", "ccr_tier2_units", "ccr_tier2_trigger"]:
        a, b = m[col], m[f"{col}_s"]
        same = (a == b) | (a.isna() & b.isna())
        bad = m.loc[~same, ["auction_name", col, f"{col}_s"]]
        out.append(f"OK   results vs settings: {col}" if bad.empty
                   else f"CHECK results vs settings: {col} differs {bad.to_dict('records')}")

    # settings notices must be published before the auction; flag same-year notices reused for changed settings
    late = sett[sett.notice_published_date > sett.auction_date]
    same_day = sett[sett.notice_published_date == sett.auction_date]
    out.append("OK   settings notices precede auctions" if late.empty
               else f"CHECK notice published after auction: {late.auction_name.tolist()}")
    if len(same_day):
        out.append(f"NOTE notice_published_date = auction day (placeholder; update-notice date unknown). Use settings_known_date (from the decision announcement) for look-ahead: "
                   f"{same_day.auction_name.tolist()}")
    key = ["price_floor", "units_available", "ccr_tier1_trigger"]
    for d, g in sett.groupby("notice_published_date"):
        if len(g.drop_duplicates(subset=key)) > 1:
            out.append(f"CHECK notices dated {d.date()} cover auctions with different settings "
                       f"({g.auction_name.tolist()}): a later notice date is likely for the changed rows")

    # spot price used in the table vs our own cleaned price series
    try:
        px = pd.read_csv(PROCESSED / "nzu_prices.csv", parse_dates=["date"])[["date", "price"]]
        j = res[["auction_name", "spot_prev_date", "spot_prev_price"]].merge(
            px, left_on="spot_prev_date", right_on="date", how="left")
        diff = j[~np.isclose(j.spot_prev_price, j.price)]
        out.append("OK   spot_prev_price matches nzu_prices.csv" if diff.empty
                   else f"CHECK spot_prev_price differs from nzu_prices.csv: "
                        f"{diff[['auction_name', 'spot_prev_date', 'spot_prev_price', 'price']].to_dict('records')}")
    except FileNotFoundError:
        out.append("SKIP spot price check (run auction_outlook.prices first)")
    return out



# ---- settings decisions and regulations ----


def governing_decision(dec: pd.DataFrame, auction_date, year: int) -> pd.Series | None:
    """The decision whose settings applied at an auction: covers the year, effective by the auction date,
    and (among those) the most recently known."""
    cand = dec[(dec["year_from"] <= year) & (dec["year_to"] >= year)
               & (dec["effective_from"] <= pd.Timestamp(auction_date))
               & (dec["known_by"] <= pd.Timestamp(auction_date))]
    return None if cand.empty else cand.sort_values("known_by").iloc[-1]


def settings_as_of(tab: pd.DataFrame, date, year: int, basis: str = "gazette_date") -> pd.Series | None:
    """Settings for calendar `year` as known on `date`.

    basis: 'announced_date' (earliest public signal), 'gazette_date' (formally public, default),
    'made_date', or 'in_force_date' (legally binding).
    """
    cand = tab[(tab["year"] == year) & (tab[basis] <= pd.Timestamp(date))]
    return None if cand.empty else cand.sort_values(basis).iloc[-1]


PRICE_FIELDS = ["price_floor", "ccr_tier1_trigger", "ccr_tier2_trigger"]
ANNUAL_FIELDS = {"ccr_tier1_reserve_m": "reg_ccr_tier1_reserve_annual_m",
                 "ccr_tier2_reserve_m": "reg_ccr_tier2_reserve_annual_m",
                 "auction_volume_incl_ccr_m": "reg_auction_volume_incl_ccr_annual_m",
                 "overall_limit_m": "reg_overall_limit_annual_m"}


def apply_to_auctions(tab: pd.DataFrame, df: pd.DataFrame, label: str) -> tuple[pd.DataFrame, list[str]]:
    """THE REGULATIONS ARE THE SOURCE OF TRUTH for price-control settings.

    For each auction, take the floor and CCR trigger prices from the regulation in force on the auction
    date. Notice values are kept as `<field>_notice` for cross-checking; where no regulation covers
    the year yet, the notice value is used and `settings_source` says so. Annual reserve amounts and
    limits from the regulation are added as `reg_*_annual_m`. Per-auction volumes (units available,
    carry-forward, remaining CCR units) stay as published in notices: the regulations set annual totals only.
    """
    df, out = df.copy(), []
    for f in PRICE_FIELDS:
        df[f"{f}_notice"] = df[f]
    for c in ANNUAL_FIELDS.values():
        df[c] = float("nan")
    df["settings_source"] = "auction notice (regulation not loaded)"
    df["settings_sr_number"] = None
    first_of_year = df.groupby(df["auction_date"].dt.year)["auction_date"].transform("min") == df["auction_date"]
    n = 0
    for i, a in df.iterrows():
        reg = settings_as_of(tab, a["auction_date"], a["auction_date"].year, basis="in_force_date") if len(tab) else None
        if reg is None:
            continue
        n += 1
        df.loc[i, "settings_source"] = f"regulation SR {reg['sr_number']}"
        df.loc[i, "settings_sr_number"] = reg["sr_number"]
        for f in PRICE_FIELDS:
            if f in reg and pd.notna(reg[f]):
                if pd.notna(a[f"{f}_notice"]) and abs(reg[f] - a[f"{f}_notice"]) > 1e-6:
                    out.append(f"CHECK {label} {a['auction_name']}: {f} regulation {reg[f]} vs notice "
                               f"{a[f + '_notice']} (regulation used)")
                df.loc[i, f] = reg[f]
        for rc, col in ANNUAL_FIELDS.items():
            if rc in reg:
                df.loc[i, col] = reg[rc]
        # CCR reserve volumes: notices show what is left, so compare only at the first auction of a year
        if first_of_year[i]:
            for rc, ac in (("ccr_tier1_reserve_m", "ccr_tier1_units"), ("ccr_tier2_reserve_m", "ccr_tier2_units")):
                if rc in reg and pd.notna(reg[rc]) and pd.notna(a[ac]) and abs(reg[rc] * 1e6 - a[ac]) > 1:
                    out.append(f"CHECK {label} {a['auction_name']}: {rc} {reg[rc]}m vs notice {ac} {a[ac]:,.0f}")
    loaded = sorted(df.loc[df["settings_sr_number"].notna(), "auction_date"].dt.year.unique())
    pending = sorted(df.loc[df["settings_sr_number"].isna(), "auction_date"].dt.year.unique())
    out.insert(0, f"{label}: settings from regulations for {n} auctions (years {list(map(int, loaded))}); "
                  f"notice values used for years {list(map(int, pending))} until those regulations are added"
                  + ("; regulation and notice agree everywhere checked" if not out else ""))
    return df, out


def build_tables(decisions: pd.DataFrame, regs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Results and settings with the governing settings decision (known-by dates, for no look-ahead) and the regulation
    in force (the source of truth for floor / CCR prices)."""
    res, sett = load()
    for df in (res, sett):
        gov = [governing_decision(decisions, d, d.year) for d in df["auction_date"]]
        df["settings_known_date"] = [g["known_by"] if g is not None else pd.NaT for g in gov]
        df["settings_date_basis"] = [g["date_basis"] if g is not None else None for g in gov]
        df["settings_decision"] = [g["decision"] if g is not None else None for g in gov]
    sett, n1 = apply_to_auctions(regs, sett, "auction_settings")
    res, n2 = apply_to_auctions(regs, res, "auctions")
    res["spot_minus_floor"] = res["spot_prev_price"] - res["price_floor"]
    res["source_file"], sett["source_file"] = SOURCE_LABEL["res"], SOURCE_LABEL["sett"]
    return res, sett, n1 + n2


def rebuild() -> list[str]:
    """Rebuild data/processed/auctions.csv and auction_settings.csv from data/curated/. Returns the check messages."""
    dec = pd.read_csv(CURATED / "ets_settings_decisions.csv", parse_dates=["announced_date", "known_by", "effective_from"])
    regs = pd.read_csv(CURATED / "auction_regulations.csv",
                       parse_dates=["announced_date", "made_date", "gazette_date", "in_force_date"])
    res, sett, notes = build_tables(dec, regs)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    res.to_csv(PROCESSED / "auctions.csv", index=False, date_format="%Y-%m-%d")
    sett.to_csv(PROCESSED / "auction_settings.csv", index=False, date_format="%Y-%m-%d")
    return validate(res, sett) + notes


if __name__ == "__main__":
    for line in rebuild():
        print(line)
