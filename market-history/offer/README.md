# offer/ — Offer Advisor

A single-page tool: put in an address, an asking price, and the house's size, and it
tells you **what comparable homes sold for** and **what the market historically does to
an asking price in that town and month** — with a slider to move the closing month and
watch the number change.

**It is not a valuation.** It reports two measured things and never pretends to a third.
Read [`SPIKE.md`](SPIKE.md) for why the design is shaped the way it is; the short version
is below.

## Run

```bash
python3 build_data.py     # bakes data.js from ../share/ + ../analysis/<newest>/
open index.html           # that's it — no server, no build, no network
```

Re-run `build_data.py` after `sales.csv` grows or a new `analysis/` snapshot lands.
Nothing else in `market-history/` reads this folder; it is a **viewer**, not a routine
(no `job.json`, no cron, no state).

## The one design idea

Two estimators, computed from different samples, and **never intersected**:

| | **Level** — "what is this house?" | **Seasonal factor** — "what does the market do to an ask?" |
|---|---|---|
| filtered by | town + sqft±15% + beds±1 + baths±1 | town + **contract month** (`pending_date`) |
| **pooled across** | **all months** | **all house types** |
| n | ~13–30 | ~10–30 (shape); town-wide (level) |

Slice a comp set *by month* and you get **about one house per bucket** — a slider dragging
that would look like seasonality and be pure noise. So comps pool every month, the
seasonal factor pools every house type, and each rests on 15–30 real sales instead of one.

## Guardrails (all of these are load-bearing)

- **Under 10 sales in a bucket, we widen or refuse** — never across town lines. Clark's
  thin January becomes Clark's *winter*, never New Jersey's January.
- **Every comp tier stays anchored to sq ft.** There is no town-wide-average fallback:
  it made a 9,000 sqft Boonton house answer $2.8M off a $/sqft blended from 1,500 sqft
  homes. Nothing that size has sold there, so the page says so.
- **Ask-based figures use only the ~60% of sales with a known list price.** Medians
  throughout — raw sold-vs-ask hits +980% on placeholder list prices.
- **The slider is the month you go under contract**, and it defaults to *now*. A price is
  struck when the offer is accepted; escrow then runs a median **41 days**. Bucketing by
  closing date smeared the seasonal signal across six weeks — on identical sales, contract
  grain sharpens the swing from **4.88pp to 6.00pp** and moves the cheapest month from
  January to **December**. It's also the only month you control.
- **Level and shape come from different samples, deliberately.** Only 79% of sales report a
  contract date and that subset is biased hot (+4.76% vs +2.45% over ask). So the *level* is
  anchored on all of a town's sales and only the month-to-month *shape* comes from the
  contract subset. See [FOLLOWUPS.md](FOLLOWUPS.md) #1b — the per-town shape is still noisy
  where coverage is thin.
- **Seabra distance and commute times are colour, never inputs.** They don't move the
  offer or rank the town.
- **Condition is not in this data.** That is why the comp output is a band, not a point.

## Files

| file | |
|---|---|
| `index.html` | the whole app — markup, styles, logic. No external assets. |
| `build_data.py` | bakes `data.js` from the market-history exports |
| `data.js` | **generated**, ~350 KB: the 6.9k-row comp universe + month curves + town reference |
| `SPIKE.md` | the design doc, including the measurements that shaped it |

`data.js` ships the comp universe (`town, sqft, beds, baths, sold_price, sold_vs_ask_pct`)
rather than fetching CSVs, because **a `file://` page cannot `fetch()` a local CSV** —
Chrome blocks it cross-origin. A `<script>` tag works, so the data arrives as a global.
`sales.csv` (5.7 MB) never reaches the browser.

## Verifying a change

There's no browser driver here, but macOS ships JavaScriptCore, so the page's real
comp/seasonal functions can be exercised directly:

```bash
python3 - <<'PY'
import re; html=open('index.html').read()
open('/tmp/logic.js','w').write(re.search(r'<script>\n"use strict";(.*?)/\* ── town resolution', html, re.S).group(1))
PY
# then load data.js + /tmp/logic.js in:
#   /System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc
```

The checks worth keeping green: Clark at $700K swings ~$40K between January and August;
tightening to sqft±10% drops Clark from 22 comps to 6 **and moves the estimate $109K**
(which is exactly why ±10% isn't the default); and a house unlike anything in the town
refuses rather than answering.
