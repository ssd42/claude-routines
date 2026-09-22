# RUNBOOK — what to run, and in what order

Two jobs come up in practice: **refresh the data**, and **add a town**. This file is only
the running order. `README.md` explains how the pieces work; `CLAUDE.md` has the rules.

The order matters because each step reads what the one before it wrote:

```
  fetch the data  →  build_share.py  →  analysis/seasonality.py  →  offer/build_data.py
   (sales, market)      (share/)            (analysis/<date>/)          (the 4 web pages)
```

Skip a step and nothing errors — the pages just quietly show older numbers than the data.

---

## A. Refresh the data ("rehydrate")

Run these from `market-history/`. Steps 1–3 need the network; 4–6 don't.

`python3 hydrate.py` does all six in this order with the guards attached, and
`--check` first tells you what is actually stale. The hand commands below are what it
runs. To refresh **only a few towns**, see [A2](#a2-refresh-just-a-few-towns).

**1. Sold sales — in batches of ~8 zips**

```bash
python3 aggregate.py --source nj_records listing_scrape --zip 07016 07027 07023 …
```

Both sources go in **one command on purpose**: they only cross-link when run together.
Run one alone and it just appends rows without matching them up. All 74 zips at once
works but takes a while and hammers the listing site — batches of ~8 are kinder.

**2. Market trends — once, not per zip**

```bash
python3 aggregate.py --source redfin_dc
```

This downloads a large national file and filters it, so `--zip` narrows the *filter*, not
the download. No point batching it.

**3. What's on the market right now — LOCAL ONLY**

```bash
python3 listings.py
```

Must run on your own machine: the listing site blocks datacenter IPs, so this can never
be a cloud job. It also verifies every town against the map boundaries automatically at
the end — you don't need to run that separately.

⚠️ **This one is forward-only.** It spots a house leaving and coming back by comparing
against the last run. A run you skip is a relist nobody can ever recover.

`--zip`/`--town` narrow the scrape **and** the "these houses have left the market" sweep
together. Before 2026-09-22 they didn't: the sweep always covered the whole file, so a
one-town run marked every listing in the other 60-odd towns as gone. If you have an old
scoped run in your shell history, don't re-use it — get it from A2 instead.

**4–6. Rebuild everything downstream**

```bash
python3 build_share.py            # the shared CSVs
python3 analysis/seasonality.py   # the month-by-month analysis snapshot
python3 offer/build_data.py       # the four web pages
```

**If a source comes back empty** the run stops and says so, loudly. That is deliberate:
the trend feed silently returned nothing for weeks because the provider renamed its
columns, and every run still looked fine. A source that returns far less than last time
warns but keeps going.

---

## A2. Refresh just a few towns

The full pull is 74 zips in batches of 8 and takes a while. When you only care about a
handful of towns today:

```bash
python3 hydrate.py --town Cranford Garwood --check    # how stale are just these?
python3 hydrate.py --town Cranford Garwood            # sold sales + on-market, then rebuild
python3 hydrate.py --zip 07016                        # by zip if you prefer
```

It refreshes sold sales and what's on the market for those towns, then rebuilds the
share CSVs, the analysis snapshot and the pages — those always run in full, because they
read the whole dataset.

**Only those two steps can be narrowed.** Market trends is one national download that is
filtered afterwards, and the layer fetchers cover all of our towns in a single call, so
asking to scope either is refused rather than quietly doing everything.

**You will often get more towns than you asked for.** A zip is not a town in either
direction — Edison spans 08820/08817/08837, while 07006 is Caldwell *and* North Caldwell
*and* West Caldwell — and every fetcher is queried by zip. So asking for West Caldwell
refreshes all three Caldwells. The run prints which neighbours came along. They are
labelled correctly either way: a sale takes its town from the deed, and a listing gets its
town from its coordinates.

**The towns you didn't name are left exactly as they were** — no listing of theirs is
marked gone, no freshness date moves. `--check` keeps reporting them stale until you
actually pull them, which is the point: staleness is judged per zip, so a two-town refresh
can't make the other 72 look current.

---

## B. Add a new town

The scripts won't discover it for you. A town has to be added by hand in a few places
first, then you re-run section A.

### 1. Tell the system the town exists

| File | Add | If you skip it |
|---|---|---|
| `config/zips.json` | name, county, its zip(s), rough miles from Westfield | Nothing else sees the town at all |
| `config/nj_municipalities.json` | its county + municipality name | No deed sales — the biggest source of history |
| `layers/geo/zip_centroids.json` | the new zip's centre point | No shop/commute distances, and it can't borrow comps from neighbours |

### 2. Re-run the per-town layers (they cover *our* towns, not all of NJ)

```bash
python3 layers/geo/fetch_boundaries.py      # gives the town a shape on the map
python3 layers/tax/fetch_tax.py             # property tax
python3 layers/appreciation/fetch_appreciation.py   # how prices moved
```

Without the boundary, houses there can't be checked against a map, so they show as
**"town unverified"** on the market page and the town is missing from the map.

### 3. Fill in the hand-maintained layers

Nothing fetches these — add a row for the town or it shows blanks (which is safe, just
empty):

- `layers/schools/school_ratings.csv`
- `layers/income/income.csv`
- `layers/transit/transit.json`
- `tierlist/tiers.json` — optional, your own ranking

Shop distances (Wawa / Trader Joe's / Seabra) need **no** work: they're measured from the
zip centre you added in step 1.

### 4. Now hydrate it

Run section A. For a quick first pull you can limit to the new zip:

```bash
python3 aggregate.py --source nj_records listing_scrape --zip 08820
```

…then still run steps 4–6 so the pages pick it up.

---

## Which file does what

| You want | Run |
|---|---|
| Newer sold history | `aggregate.py --source nj_records listing_scrape` |
| Newer market trends | `aggregate.py --source redfin_dc` |
| Newer for-sale listings | `listings.py` *(local only)* |
| Pages showing the latest data | `build_share.py` → `analysis/seasonality.py` → `offer/build_data.py` |
| Just re-check towns against the map | `relabel_listings.py` *(runs automatically inside `listings.py`)* |
| Re-dedupe without fetching | `aggregate.py --dedupe-only` |
| Try it offline, no network | `aggregate.py --fixture` |

**Layers refresh on their own clock, not with a rehydrate.** Re-scraping sales tells the
tax or appreciation layers nothing new — those come from outside sources. Refresh them
when *those* publish (see the table in `CLAUDE.md`), not every time you pull sales.
