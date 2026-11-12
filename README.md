# NZ ETS auction outlook

The code and data behind the auction outlook at [kapiticlimate.com/insights](https://kapiticlimate.com/insights): the chance that each of the next two New Zealand Emissions Trading Scheme (NZ ETS) auctions sells any units.

In short, it looks at how much the NZU price has moved in the past over the same length of time as there is until each auction, and applies those moves to today's price. That gives the chance the price will be above the floor on auction day. That's multiplied by how often past auctions have sold units when the price was above the floor.

The outlook is updated every week by a GitHub Action. Because it updates weekly, the useful signal is often the trend: whether the chance is rising or falling as an auction approaches, and how it moves after a policy announcement. The price source updates every week or two (less often over Christmas–January, when the market barely trades), so some weeks the estimate won't change. Each week's estimates are added to [`outputs/auction_outlook_log.csv`](outputs/auction_outlook_log.csv), so the commit history is a dated, public record of every published estimate.

## The method

An auction sells units only if bids are at or above the price floor, and also clear the confidential reserve price. So the chance an auction clears is:

> **P(clear) = P(market price ≥ floor on the auction day) × reserve-clearing rate**

- **P(price ≥ floor):** a range of where the NZU price could be by the auction. It comes from the actual price moves over the same number of weeks during the last three years, centred on today's price. There's no view on direction, so the middle of the range is today's price.
- **Reserve-clearing rate:** the share of past auctions that sold units when the market price was above the floor, computed as (cleared + 1) / (auctions + 2) so a handful of auctions can't push it to 0% or 100%.
- **Floor price:** taken from the Climate Change (Auctions, Limits, and Price Controls for Units) Regulations in force at the time, cross-checked against the auction notices.

**What it assumes:** price moves over the coming weeks will be like those of the past three years, including the usual run of policy news. A surprise that's bigger than anything in that window can move the price, and the outlook, sharply. The weekly updates then show the effect.

### Track record

The track record on the website tests the method on every auction since March 2021: what it would have said about 12 weeks before each auction, using only information available at that time. Accuracy is measured with a Brier score: the average squared gap between the forecast chance and what happened (1 if the auction sold units, 0 if it didn't). 0 is perfect, and lower is better.

To show whether the method adds anything, it's compared with two simpler ways of forecasting the same 23 auctions. Both the method and the floor check use the **reserve-clearing rate**: of past auctions where the market price was above the floor, the share that also cleared the confidential reserve price and sold units (10 of 14, about 69%, as of November 2026).

| Forecast | How it works | Brier score |
| --- | --- | --- |
| **This method** | Chance the price is at or above the floor on the auction day × reserve-clearing rate | **0.18** |
| Past clearing rate | The share of all earlier auctions that sold units. Every auction gets the same chance, whatever the price. | 0.28 |
| Floor check | A yes/no version of this method: if the NZU price 12 weeks before the auction is above the floor, forecast the reserve-clearing rate; if it's below, forecast only a 2% chance (a small, fixed allowance in case the price recovers). It ignores how far the price could move in those 12 weeks. | 0.19 |

With only 23 auctions to test on, treat the estimates as a simple guide, not a precise forecast.

The method is deliberately simple and frozen. A test checks that it still reproduces a fixed snapshot, and any change gets a new `MODEL_VERSION` (recorded in each published estimate) and an entry in [CHANGELOG.md](CHANGELOG.md).

## Data

| Data | Source | Licence |
| --- | --- | --- |
| NZU daily prices | [github.com/theecanmole/nzu](https://github.com/theecanmole/nzu) (`spotprices.csv`) | ODC-PDDL (public domain) |
| Auction results and notices | [etsauctions.govt.nz](https://www.etsauctions.govt.nz), entered by hand in `data/curated/` | Public government information |
| Floor and price-control settings | Climate Change (Auctions, Limits, and Price Controls for Units) Regulations | NZ legislation (no copyright) |
| Settings decision dates | Beehive releases and Ministry for the Environment pages (links in the file) | Public government information |

## Run it yourself

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m auction_outlook.publish --no-log   # refresh prices, rebuild, check, write outputs/auction-outlook.json
uv run --group test pytest                          # tests
```

## What's here

```text
src/auction_outlook/   the code (model.py is the method)
data/curated/          hand-entered auction results, notices, regulations and decision dates
data/processed/        built by the weekly job
outputs/               auction-outlook.json (read by the website) and the published-estimates log
tests/                 the frozen-method test and its snapshot
```

**`data/curated/` vs `data/processed/`:** `curated/` holds the only data entered by hand: auction results and notices from etsauctions.govt.nz, the regulations' floor and price-control settings, and the dates each annual settings decision became public. It's the source of truth, and the only data folder to edit. `processed/` is rebuilt from it on every run: the NZU price series as downloaded and cleaned, plus the curated auction tables with the working columns added (such as the floor from the regulation in force on the auction date, and the market price just before each auction). It's kept in the repo so anyone can see exactly what each published estimate used, and so each run can flag if the price source has revised past prices. Some file names appear in both folders. Edit only the `curated/` copies.

## Disclaimer

This is general information about the NZ ETS auction process, not financial advice. The estimates are statistical and can be wrong, especially around policy announcements, which have driven the largest price moves historically.

## How to cite

If you use or adapt the method, the code or the published estimates, please credit Kapiti Climate and link back here. GitHub's **Cite this repository** button (top right of the repo page) gives APA and BibTeX versions. In short:

> Kapiti Climate (2026). *NZ ETS auction outlook* (version 1.0.0) [software and data]. <https://github.com/kgreen7/NZETS-auction-outlook>

When quoting a specific estimate, also give its date and model version, both recorded in each row of [`outputs/auction_outlook_log.csv`](outputs/auction_outlook_log.csv). For example: "Kapiti Climate NZ ETS auction outlook, estimate of 12 November 2026 (auction-outlook 1.0), kapiticlimate.com/insights".

## Licence

- **Code:** MIT (see [LICENSE](LICENSE)).
- **Published estimates** (everything in [`outputs/`](outputs/)): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You're free to reuse them, including commercially, with credit to "Kapiti Climate, NZ ETS auction outlook" and a link to [kapiticlimate.com/insights](https://kapiticlimate.com/insights).
- **Input data:** each source's own terms (see [Data](#data) above).

By [Kapiti Climate](https://kapiticlimate.com).
