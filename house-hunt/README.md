# house-hunt

Daily (8am ET) new-listing scout for a couple of target neighborhoods. Each
morning it pulls listings from multiple sources, reconciles them, and posts a
board to Slack with these sections:

- **🆕 New today** — listings that just hit the market and match your criteria.
- **🔔 Changes** — on houses already shown: **price drops/bumps**, **went
  pending**, **back on market**, and nearby **solds**. (The "don't miss it" row.)
- **🤏 Close enough** — near-misses that *bend* one rule a little (price slightly
  over, a bed short), each shown with *what* it bends.
- **🔁 This week** — still-active matches from previous days, so a good listing
  doesn't scroll away after one morning.
- **👀 Watchlist** — houses you liked but won't buy. Tracked from list price to
  **sold** price (and days-on-market) over the following months.
- **📊 Market** — per-zip comps from solds we've tracked: median sold **$/sqft**,
  sold-vs-list ratio, days-on-market.

The board also opens with a one-line **⏱ timing nudge** — the soonest date a
winning offer needs to be accepted to still close in the target window (see the
Timing planner below).

Every listing row also carries **days-on-market** and a **vs-area** pricing tag
(its list $/sqft vs the median *sold* $/sqft for its zip) — so an overpriced
house is obvious at a glance.

## ⏱ Timing planner (`timing.py`)
A standalone *closing-runway* planner — the "when," to the board's "what." Given
month-to-month rent with a landlord **notice period** and a **target close
window** (`timing.json`), it back-plans from each candidate close month to tell
you **when a winning offer must be accepted** and **when to give notice**. The
lead time it needs — **escrow (under-contract → close), ≈38 days** locally — is
read straight off the hand-tracked comps in `comps.json`, with the price ceiling
from `criteria.json`. It also reads **seasonality** off those comps (which months
closed over vs under ask) and flags when the hot "frenzy" comps sit in a price
tier above your budget.

The headline insight is computed, not assumed: escrow (~38d) is *shorter* than a
60-day notice, so giving notice the day you go under contract leaves the lease
running ~3 weeks past closing — a safe overlap, not a gap.

```bash
python3 timing.py [YYYY-MM-DD]   # prints the runway board
```
`comps.json` is hand-researched reference solds (list → pending → close dates,
asking, closed, Zestimate) — the data that seeds the timing lead times.

Each run can also emit **Slack Block Kit cards** (lead photo + "View listing"
button) via `--blocks`, which the agent POSTs to the webhook.

## How it works
1. **Fetch** each source in `sources.json` (Redfin, Realtor.com, Zillow) into
   `raw/<source>.json` — done by the scheduled agent.
2. **Reconcile** in `match.py`: the same house across sources is matched by
   normalized *address + zip*; numeric fields (price/beds/sqft) use a 2-of-3
   consensus, and any disagreement is flagged with ⚠ on the row.
3. **Score** each listing against `criteria.json` → match / close-enough / excluded.
4. **Diff** against `seen.json` → new-today vs this-week.
5. **Track** watchlist items → capture price changes and the eventual sold price.
6. **Post** the board to Slack (channel in `job.json`).

Like bracket-challenge, this repo is also the **memory**: `history/`, `seen.json`,
and `watchlist.json` persist between runs and are committed. `raw/` is transient
(re-fetched each run, gitignored).

## Adding to the watchlist
Reply in a listing's **Slack thread** (see `job.json` → `watchlist_intake`).
Each run the agent scans listing-post threads for new replies, extracts the
house, and appends it to `watchlist.json` with its current list price.

## Files
| file | what |
|------|------|
| `match.py` | deterministic reconcile + score + diff + watchlist tracker + ASCII board |
| `timing.py` | closing-runway planner: back-plans offer/notice dates from a target close window |
| `timing.json` | notice period + target close window for the timing planner |
| `comps.json` | hand-researched reference solds (list→pending→close dates); seeds the timing lead times |
| `criteria.json` | your neighborhoods, price range, must-haves, relax tolerances, dealbreakers |
| `criteria.template.json` | annotated template — copy to `criteria.json` |
| `sources.json` | listing sources + reconciliation/consensus rule |
| `watchlist.json` | liked-but-won't-buy houses, list→sold tracking (memory) |
| `seen.json` | every listing we've shown + first/last seen (memory; new-vs-week diff) |
| `history/` | dated snapshots of the full reconciled set (memory) |
| `raw/` | transient per-run source fetches (gitignored) |
| `fixtures/` | sample source files for a demo run |
| `job.json` | schedule + Slack delivery + watchlist intake config |

## Run it (demo)
```bash
cp fixtures/*.json raw/                  # stand in for a real fetch
python3 match.py [YYYY-MM-DD]            # prints the board; writes history/ + seen.json
python3 match.py [YYYY-MM-DD] --blocks  # ALSO prints Slack Block Kit JSON (photo cards)
```
The `fixtures/` demo spans two days (run `2026-06-10` then `2026-06-12`) to show
the Changes section (price drop + went-pending), sold comps, and vs-area tags.

## Status — SPIKE
Criteria set (Scotch Plains 07076 + Colonia 07067, $300–650k, 3+ beds), running
daily 8am ET. Scoring, reconcile, change-alerts, comps, and Slack cards all work
on sample data. Still to wire up:
- The agent-side **fetch** step per source (the part that writes `raw/`), incl.
  recent **solds** (Redfin best) to feed the comps.
- Slack **thread-reply parsing** for watchlist intake.
- Confirm `#housing-updates` == channel `C0B9JHL9NE9`; webhook stays out of repo.

Memory is resolved: no external DB — the committed state files (`history/`,
`seen.json`, `watchlist.json`, `mutes.json`) are the datastore, committed +
pushed at the end of each run (same "fake DB" pattern as bracket-challenge; see
`job.json` → `data_home`).
