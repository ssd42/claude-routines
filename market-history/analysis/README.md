# analysis/ — derived rollups

Question-driven rollups computed **from `share/sales.csv`** (+ `zips.json` for
county). Nothing here is a new data source: every figure is derived, and the
scripts regenerate a snapshot from scratch. If a number here disagrees with
`share/`, `share/` wins — re-run and the disagreement goes away.

This is a **third grain**, distinct from the two in [`../CLAUDE.md`](../CLAUDE.md):

| grain | where | one row per |
|-------|-------|-------------|
| sale | `sales.csv` | transaction |
| town | `layers/` | place |
| **question** | **`analysis/`** | **bucket of sales that answers a specific question** |

Snapshots are dated (`analysis/<YYYY-MM-DD>/`) because `sales.csv` grows. An old
snapshot is a point-in-time answer, not a stale file to fix — leave it, write a
new one beside it.

## Run

```bash
python3 analysis/seasonality.py                  # snapshot dated today
python3 analysis/seasonality.py --out 2026-07-13 # name the snapshot
python3 analysis/seasonality.py --keep-defects   # keep corrupt list_dates (don't)
python3 analysis/defects.py                      # scan for bad rows -> defects/<date>/
```

---

## `seasonality.py` — when in the year do homes sell over/under asking?

Written to answer: *we're pre-approving in July; when is it cheapest to close, what
will we actually have to bid, and when do we need to be shopping?*

| file | one row per | answers |
|------|-------------|---------|
| `seasonality_all_towns.csv` | month-of-year (12) | the headline curve — which months are cheap, all 53 towns pooled |
| `seasonality_by_year.csv` | (month, year) | is the seasonal effect stable, or is 2025 softer than 2024? |
| `by_town_month_of_year.csv` | (town, month-of-year) | per-town curve — 635 rows, pooled across years |
| `by_county_month_of_year.csv` | (county, month-of-year) | the same, rolled up to county |
| `listing_lag_by_town_month.csv` | (town, close month) | of the homes that CLOSED then, when did they hit market? |
| `listing_lag_all_towns.csv` | close month (12) | the same, pooled |

### Three denominators. Mixing them up is the easiest way to be wrong.

| column | counts | use for |
|--------|--------|---------|
| `sales_all` | **every** sale in the bucket | context only — **never** a denominator |
| `n` | sales with a usable **list price** (~60%) | anything ask-based: sold-vs-ask, at-or-under, DOM |
| `n_lag` | sales with a **trustworthy list date** | anything about *when a home hit the market* |

Deed records carry no asking price, so they can't answer an ask question. And
`list_date` is corrupt on ~1,862 rows — **excluded by default** (see
[`../DEFECTS.md`](../DEFECTS.md)); `--keep-defects` turns that off, which you
shouldn't want.

### Columns

**Ask files:** `median_sold_vs_ask_pct` is the headline (positive = sold over
asking); `median_sold_vs_ask_abs` is the same thing in dollars — what a typical
buyer paid above ask. `mean_*` exists because it was asked for; **prefer the
median** — `sold_vs_ask_pct` reaches +980% on placeholder list prices.
`pct_at_or_under_ask` is the buyer's-leverage proxy.

**Lag files:** `pct_fresh` = listed the same month or the month before closing.
`pct_aged` = listed **2+ months** before closing. `median_days_list_to_close`
speaks for itself.

`thin` = `yes` when the bucket is under 10 sales. **Too thin to conclude from.**

### Two traps in reading these files

1. **Median list/sold price is a mix, not a trend.** Westfield's median list reads
   $1,312,000 in September and $999,000 in October. The market did not fall 24% in
   four weeks — a different *set of houses* sold. Use those columns to picture a
   typical sale; use `median_sold_vs_ask_pct` to track the market.
2. **Town-months are noisy.** The pooled curve rests on 22,691 sales; a single
   town-month often rests on 15–40. Check `n` and `thin` before believing a spike.
   Springfield's "+6.28% in February" is 14 sales, contradicts the pooled curve and
   every other town, and is noise.

### What the 2026-07-13 snapshot found

**The seasonal curve is the finding, and it is monotone.** The sold-vs-ask premium
peaks in **May (+6.38% / $45,001 over ask)** and falls every month through
**February (+1.56% / $10,000)**. Within a Jul→Oct window **October is the best
month to close** (+3.00% / $19,000, vs July's +5.67% / $39,000) — but the actual
trough is Jan–Feb, ~$9,000 lower again, with >40% of homes closing at or under ask.
**Not one of the 53 towns has its cheapest month between March and August.**

Median list-to-close is 63 days, so a July pre-approval lines up with an autumn
close. **But `days_on_market` is list-to-CLOSING, not list-to-contract** — the
offer-accepted date is nowhere in this dataset (DEFECTS.md #3). You cannot get
"when should I offer" from these files without knowing your own escrow period.

**Winter's cheapness is partly a leftovers effect — but less than it first looks.**
January closings are **87.7% aged** (listed 2+ months earlier) and take a median
**77 days** list-to-close, both the year's extremes; December is 82.7% / 64 days.
So winter buyers are disproportionately picking through fall inventory that didn't
sell, and that is where the leverage comes from.

⚠️ **The honest caveat:** the year-round baseline is already ~75% aged. January
(87.7%) is a genuine outlier; **December (82.7%) is only modestly above baseline.**
An earlier read of the Union County December numbers ("81% aged!") overstated this
— 81% aged in December is close to normal. Compare a month against the baseline,
not against zero.
