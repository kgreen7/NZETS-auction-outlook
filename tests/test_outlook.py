"""Tests for the auction outlook. Run: uv run --group test pytest

1. The method is frozen: on a fixed snapshot of the inputs (tests/fixtures/, taken 12 Nov 2026) the export must
   reproduce tests/fixtures/expected.json. If you change the method ON PURPOSE, bump MODEL_VERSION in
   src/auction_outlook/model.py, then regenerate the expectations with
       uv run python tests/test_outlook.py --regenerate
   and record the change in CHANGELOG.md.
2. The JSON has the expected structure (schema).
3. The publishing checks catch stale prices, a missing auction result and a missing auction notice.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auction_outlook.checks import check_inputs  # noqa: E402
from auction_outlook.export import build, load_inputs, validate_schema  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 12)
VOLATILE = ("generated", "log")


def _built() -> dict:
    data = build(load_inputs(FIX), TODAY)
    data["log"] = []
    return data


def _comparable(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in VOLATILE}


@pytest.fixture(scope="module")
def built():
    return _built()


def test_method_is_frozen(built):
    expected = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
    got = _comparable(built)
    assert got.keys() == expected.keys()
    for k in expected:
        assert got[k] == expected[k], f"'{k}' changed: the public method differs from the frozen version (see docstring)"


def test_schema_is_valid(built):
    assert validate_schema(built) == []


def test_schema_catches_a_broken_file(built):
    broken = dict(built, next_auctions=built["next_auctions"][:1])
    assert any("expected 2 upcoming auctions" in e for e in validate_schema(broken))


def test_checks_pass_on_snapshot():
    errors, _ = check_inputs(load_inputs(FIX), TODAY)
    assert errors == []


def test_checks_block_stale_prices():
    errors, _ = check_inputs(load_inputs(FIX), date(2027, 1, 15))
    assert any("days old" in e for e in errors)


def test_checks_block_missing_result():
    inp = load_inputs(FIX)
    inp.auctions = inp.auctions[inp.auctions["auction_date"] < "2026-09-01"]   # pretend Sep 2026 wasn't entered
    errors, _ = check_inputs(inp, TODAY)
    assert any("No result entered for the September 2026 auction" in e for e in errors)


def test_checks_block_missing_notice():
    inp = load_inputs(FIX)
    inp.settings = inp.settings[inp.settings["auction_date"] < pd.Timestamp("2027-01-01")]  # only Dec 2026 ahead
    errors, _ = check_inputs(inp, TODAY)
    assert any("Fewer than two upcoming auctions" in e for e in errors)


def test_new_result_row_needs_only_the_facts():
    """A results row with just the facts from the results page gets every derived column filled consistently."""
    from auction_outlook import auctions
    _, sett = auctions.load()
    cur = pd.read_csv(auctions.FOLDER / "auctions.csv")
    new = pd.DataFrame([{"auction_name": "December 2026", "auction_date": "2026-12-01", "units_sold": 0,
                         "notice_outcome": "no_bids", "source_url": "https://www.etsauctions.govt.nz/"}])
    full = pd.concat([cur, new], ignore_index=True)
    for c in ["auction_date", "published_date", "settings_published_date", "spot_prev_date"]:
        full[c] = pd.to_datetime(full[c])
    done = auctions.complete(full.sort_values("auction_date").reset_index(drop=True), sett)
    row = done[done["auction_name"] == "December 2026"].iloc[0]
    assert row["price_floor"] == 71 and not row["any_units_sold"] and row["outcome"] == "no_bids"
    assert row["units_unsold"] == row["total_auction_units_published"] == row["non_ccr_units"] + row["ccr_units_total"]
    assert pd.notna(row["spot_prev_price"])
    flags = [m for m in auctions.validate(done, sett) if m.startswith("CHECK") and "spot_prev_price" not in m]
    assert flags == []


def test_new_result_row_rejects_unknown_outcome():
    from auction_outlook import auctions
    _, sett = auctions.load()
    cur = pd.read_csv(auctions.FOLDER / "auctions.csv", parse_dates=["auction_date"])
    bad = pd.concat([cur, pd.DataFrame([{"auction_name": "December 2026", "auction_date": pd.Timestamp("2026-12-01"),
                                         "units_sold": 0, "notice_outcome": "failed", "source_url": "x"}])])
    with pytest.raises(ValueError, match="outcome must be one of"):
        auctions.complete(bad.reset_index(drop=True), sett)


if __name__ == "__main__" and "--regenerate" in sys.argv:
    (FIX / "expected.json").write_text(json.dumps(_comparable(_built()), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {FIX / 'expected.json'}")
