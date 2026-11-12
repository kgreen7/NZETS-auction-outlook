# Maintaining the auction outlook

How the published outlook is kept up to date. This is Kapiti Climate's runbook. If you've copied the repo to run your own version, the same steps apply, and you can skip the website section.

## Weekly (automatic)

The **Weekly update** Action runs every Monday at 19:00 UTC (Tuesday morning NZ). It runs the tests, downloads the latest NZU prices, rebuilds the auction tables, runs the checks, writes `outputs/auction-outlook.json`, appends to the log, commits, and (if switched on) copies the JSON to the website repo.

Nothing to do unless GitHub sends a failure email. The bot commits to `main`, so `git pull` before working locally. To run it on demand: **Actions → Weekly update → Run workflow**.

## By hand (about 8–10 times a year)

Edit the CSVs in `data/curated/`, then commit and push. A push that changes `data/curated/` starts the Action straight away, so the new result or notice is published within a few minutes.

**After an auction:** add one row to `auctions.csv` from the etsauctions.govt.nz results page. Only these columns are needed; leave the rest blank and they're filled in automatically.

| Column | Example | Notes |
| --- | --- | --- |
| `auction_name` | `December 2026` | Same name as in `auction_settings.csv` |
| `auction_date` | `2026-12-01` | YYYY-MM-DD |
| `units_sold` | `0` | Total units sold, including any CCR units |
| `notice_outcome` | `no_bids` | `cleared_full`, `cleared_partial`, `declined_min_price` or `no_bids` |
| `source_url` | results page link | |
| `clearing_price` | `64.00` | Blank if nothing sold |
| `ccr_units_sold` | `0` | Only if the CCR was triggered |

**When an auction update notice is published:** add or update the auction's row in `auction_settings.csv` (date, units, floor, CCR tiers, source link). The outlook always needs **two** upcoming auctions in this file.

**When new regulations or an annual settings decision are made (about once a year):** add rows to `auction_regulations.csv` (one per calendar year the regulation covers) and `ets_settings_decisions.csv`. Regulations are the source of truth for the floor. Auction notices are the cross-check: if a notice disagrees with the regulation, the run prints a `CHECK` warning, and the regulation's value is used.

## If the weekly run fails

Nothing is published, so the website keeps the last good numbers. The **Publish** step prints one line per problem:

| Message | What to do |
| --- | --- |
| `No result entered for the X auction` | Add the result row, commit, push |
| `Fewer than two upcoming auctions` | Add the next auction notice to `auction_settings.csv` |
| `No floor price for the X auction` | Fill `price_floor` in `auction_settings.csv` |
| `NZU prices are N days old` | Only blocks when prices are over 45 days old. The source normally updates every one to three weeks (longer over Christmas-January), so this means it may have stopped. Check github.com/theecanmole/nzu, re-run later |
| `auctions.csv: required fields blank` / `outcome must be one of` | Fix the row you entered |
| `test_method_is_frozen` failed | Something changed the method. See below |

## Copying to the website (optional)

The numbers on [kapiticlimate.com/insights](https://kapiticlimate.com/insights) come from `outputs/auction-outlook.json`. When the repository variable `PUSH_TO_SITE` is `true`, the Action's last step copies that file into the website's repository (`kgreen7/kapiti-climate`), and the site redeploys. When it isn't set, everything else still runs and publishes here.

The copy needs a token that can write to the website repository and nothing else:

1. On GitHub: **Settings → Developer settings → Fine-grained tokens**. Give it access to **only**
   `kgreen7/kapiti-climate`, with **Contents: Read and write**. Note its expiry date.
2. In this repo: **Settings → Secrets and variables → Actions**. On the **Secrets** tab add `SITE_REPO_TOKEN` (paste
   the token there, nowhere else). On the **Variables** tab add `PUSH_TO_SITE` = `true`.

To pause the copy, set `PUSH_TO_SITE` to `false`.

**When the token expires**, the copy step fails and GitHub notifies by email. Create a new token as in step 1 and replace the `SITE_REPO_TOKEN` secret.

## Changing the method

1. Edit `src/auction_outlook/model.py` (or `export.py`) and bump `MODEL_VERSION`.
2. Check the numbers: `uv run python -m auction_outlook.publish --offline --no-log`.
3. Regenerate the test expectations: `uv run python tests/test_outlook.py --regenerate`.
4. Add an entry to `CHANGELOG.md`.

If the JSON's structure changes (renamed or removed fields), also bump `SCHEMA_VERSION` in `export.py` and update the website's `components/insights/outlookData.ts`.

## Running locally

```bash
uv sync --group test
uv run python -m auction_outlook.publish --site "path/to/kapiti-climate-website"
uv run --group test pytest
```

Add `--no-log` for a dry run that doesn't change the log, and `--offline` to skip the price download.
