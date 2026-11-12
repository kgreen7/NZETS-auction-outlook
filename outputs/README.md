# Published estimates

The two data files in this folder are written by the weekly update (see [MAINTAINING.md](../MAINTAINING.md)). Please don't edit them by hand.

| File | What it is |
| --- | --- |
| `auction-outlook.json` | The current outlook, as shown at [kapiticlimate.com/insights](https://kapiticlimate.com/insights): the next two auctions, the price range, the track record and its scores. |
| `auction_outlook_log.csv` | Every published estimate: one row per auction for each NZU price date. Earlier rows are kept; if the job re-runs on the same price date, that date's row is replaced (the git history keeps the earlier version). |

Columns in the log:

| Column | Meaning |
| --- | --- |
| `price_as_of` | Date of the latest NZU price used |
| `generated` | Date the estimate was made |
| `auction`, `auction_date` | The auction being estimated |
| `floor` | Auction floor price (NZD) |
| `latest_price` | NZU price on `price_as_of` (NZD) |
| `p_above_floor` | Chance the NZU price is at or above the floor on the auction day |
| `p_clear` | Chance the auction sells any units |
| `model` | Method version that produced the estimate |

## Licence

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You're free to reuse the estimates in this folder (`auction-outlook.json` and `auction_outlook_log.csv`), including commercially, with credit to "Kapiti Climate, NZ ETS auction outlook" and a link to [kapiticlimate.com/insights](https://kapiticlimate.com/insights). See [How to cite](../README.md#how-to-cite).
