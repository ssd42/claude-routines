# market-history

Aggregate **3 years of NJ sold + market data** across multiple free sources,
**dedupe** it, resolve conflicts, and emit **CSVs**. Re-runnable — every run
pulls more data and merges it into the committed CSVs. Not a dashboard, not a
decision tool (yet): the sole job right now is to **hydrate a clean dataset**.

> **Status: SPIKE.** All three data layers are live. `sales.csv` holds **~26k
> real NJ sales, 2023-07 → present**, merged across MOD-IV deed records and
> Realtor.com sold listings (~4.7k matched in both). `market.csv` (zip-month
> trends via redfin_dc) is verified on a fixture; its first real pull is pending
> (large national download). `listing_scrape` is **local-only** (403s in cloud).

## What it produces
| file | grain | filled by | holds |
|------|-------|-----------|-------|
| `market.csv` | one row per **(zip, month, property_type)** | redfin_dc ✅ | median sale price, median $/sqft, median DOM, sale-to-list ratio, % sold above list, homes sold, new listings, inventory — i.e. **how each neighborhood moved up/down** |
| `sales.csv` | one row per **property sale** | nj_records + listing_scrape ⏳ | address, zip, list/sold dates, DOM, list/sold price, **sold-vs-ask ($ and %)**, sqft/beds/baths, lot, year built, garage/solar/ac_type, `conflicts`, `_sources` |
| `listings.csv` | one row per **listing SPELL** | `listings.py` ⏳ | one continuous period a house sat on the market. A property with 2 spells was **relisted**. See below — this is how we catch the days-on-market reset |
| `_provenance.json` | per merged sale | merge | **every** source's value for every field + which disagreed |
| `history/<date>/` | snapshot | each run | committed point-in-time copy of both CSVs |
| `raw/<source>.json` | per-source pull | fetch | normalized rows, **gitignored** (transient, reproducible) |
| `state.json` | cursor | each run | per (source, zip): latest period + last-fetched, so re-runs extend |

## The three layers (`sources.json`)
No single free source has everything you asked for going back 3 years, so the
job **stitches complementary layers** together:

| layer | status | grain | cloud-safe? | gives | misses |
|-------|--------|-------|-------------|-------|--------|
| **redfin_dc** — Redfin Data Center | ✅ live | zip-month | yes | market trends per zip (median $, $/sqft, DOM, sale-to-list, %-above-list) | per-property rows |
| **nj_records** — MOD-IV deed sales (maps.nj.gov) | ✅ live | sale | yes | authoritative **address + sold price + sold date**, year built, lot, best-effort sqft/garage | DOM, list price, beds/baths, amenities; **lags ~1 yr** |
| **listing_scrape** — HomeHarvest/Realtor.com | ✅ live | sale | **no** (403s datacenter IPs → run locally) | **DOM, list price, sold-vs-ask, beds/baths, garage**, best-effort solar/ac_type; fills the **recent ~12–18 mo** nj_records lacks | solar/AC sparse (parsed from text); local-only |

### nj_records — how it works (the pattern that spreads to every county)
One statewide endpoint — `maps.nj.gov/.../Framework/Cadastral/MapServer/0` — holds
MOD-IV for **all** NJ counties, so a single integration covers everything. It is
queried **per municipality**, because the data taught us:
- **Zip is unreliable** — the `ZIP5` field is dirty (a `ZIP5=07076` query returned
  Essex County rows). MOD-IV is keyed by `COUNTY + MUN_NAME`, so
  [`nj_municipalities.json`](nj_municipalities.json) maps each town → exact
  municipality string(s).
- **Some towns are sections of a bigger municipality** — Colonia→Woodbridge,
  Basking Ridge→Bernards, Towaco→Montville. Marked `section_of`; the pull is
  subset back to the section's zip. Some towns split into Boro + Twp (Chatham,
  Mendham, Boonton) — both are listed.
- **Non-arms-length deeds are filtered** — SR1A non-usable codes (01–33) and
  nominal `$1`/`$10` transfers (via `--min-price`, default $10k) are dropped.
- **Residential only** (`PROP_CLASS='2'`) by default; commercial/land/exempt skipped.
- **~1-year data lag** — MOD-IV is assessment data; it currently covers through
  ~end of 2024. Recent sales are what `listing_scrape` will add on top.
- **DEED_DATE** is `YYMMDD`; `sqft`/`garage` are best-effort parsed from `BLDG_DESC`.

## `listings.py` — catching the days-on-market reset

A seller whose house isn't moving can pull the listing and put it back later. The
MLS starts a **fresh listing** — new `days_on_market`, usually a new `mls_id` — and
the house reads as brand new. That is the point: buyers pay more for a home that
looks like it just arrived.

**Our sold-listings source cannot see this.** It returns one row per sold property
with one `list_date`, and does not return withdrawn listings. A house that listed in
February, was pulled in April, relisted in June and sold in July reaches us as *a
single listing that began in June*.

So `days_on_market` in `sales.csv` is a **floor, not a fact** — and the error is not
random, it is **biased**: the houses that struggled longest have the most understated
DOM, so they look *fresher and more in demand than they were*. Read a **high** DOM as
real evidence of weakness (nobody inflates it); never read a **low** one as evidence
of demand.

No field fixes this. The only way to know a house left the market is **to have been
watching**. `listings.py` watches:

```bash
python3 listings.py              # one observation run -> listings.csv
python3 listings.py --dry-run    # scrape + report, write nothing
```

Each run records what is currently for sale. A listing that was there last run and is
gone this run has **ended**; if the same property reappears later, that is a
**relist**, and we know the true first-list date because we saw it.

`listings.csv` is **one row per listing SPELL** — one continuous period a house sat on
the market. A property with 2 spells was relisted once. Join it to `sales.csv` on
`property_key`. It is a **third grain** (listing), alongside sale and town — don't
merge it into a sales file.

**We deliberately do NOT fuse two spells just because the gap was short.** A 6-week gap
at the *same* price is a DOM reset; a 6-week gap at a price cut from $700K to $625K is a
genuine repricing, and calling that "180 days on market" would misrepresent a real new
offer to the market. **The price delta is the tell, not the gap.** Spells are recorded as
facts, each keeping its own first/last price; collapsing is left to whoever asks the
question, because a fused row destroys the distinction forever.

### ⚠️ It is forward-only, so it has to actually run

It detects a relist by seeing a listing vanish and come back — which it can only do
**across runs**. It knows nothing before its first run (2026-07-13, 3,503 active
listings) and **cannot be backfilled**. Every unobserved week is a permanent hole.

It **cannot run in the cloud** (Realtor.com 403s datacenter IPs — same constraint as
`listing_scrape`). It needs a weekly *local* trigger:

```bash
cp schedule/com.claude-routines.market-history-listings.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude-routines.market-history-listings.plist
launchctl list | grep market-history      # confirm it registered
```

If that agent silently stops, `listings.csv` quietly stops accumulating and the relist
analysis is worth nothing. Check `last_seen` in `listings.csv` if you suspect it died.

## Merge — how conflicts resolve
The layers are **complementary** (different columns), so the merge uses
**per-field authority**, not 2-of-3 consensus:

- Each field fills from the first source in `sources.json:field_authority` that
  has a value. e.g. `sold_price` ← nj_records, else listing_scrape, else redfin;
  `days_on_market` ← listing_scrape only; `sqft` ← listing_scrape, else nj_records.
- **Best-effort / nullable:** a missing field is left blank; a sale is never
  dropped for missing amenities.
- **Conflict flag:** when 2+ sources give differing non-null values for a field
  (beyond `conflict_tolerance` — e.g. sold_price >3% apart), the field name is
  added to that row's **`conflicts`** column, and *all* values are kept in
  `_provenance.json`. Nothing is silently discarded.
- **Dedupe key:** market = `(zip, period_end, property_type)`; sales =
  `(address_norm, zip, sold_month)` — `sold_month` lets a house that sold twice
  in the window be two rows, while `St`/`Street` etc. normalize to one.

## Run
```bash
python3 aggregate.py                       # all LIVE sources → merge → CSVs (real network)
python3 aggregate.py --source nj_records   # deed sales only (~1 min, all 36 municipalities)
python3 aggregate.py --source redfin_dc    # trends only (large national download)
python3 aggregate.py --fixture             # offline demo from fixtures/ (what the spike was verified with)
python3 aggregate.py --zip 07076 07067     # limit to towns owning these zips
python3 aggregate.py --since 2023-07       # earliest month to keep (default: 3 years ago)
python3 aggregate.py --min-price 25000     # raise the nominal-deed floor for nj_records
```
Re-running is **idempotent + additive**: it re-reads the existing CSVs and
merges new rows in, so you can keep hydrating in batches.

> ⚠️ Redfin's public file is a **large national TSV**, streamed and filtered
> line-by-line (memory-safe) — `--zip` narrows what's *kept*, not what's
> downloaded. If the S3 path moves, override `MARKET_HISTORY_REDFIN_URL`.
> Scraping (`listing_scrape`) must run on a **residential IP** (see house-hunt
> `FETCH.md`); redfin_dc and nj_records are cloud-safe.

## Next
1. **redfin_dc real pull** — first live run to populate `market.csv` (verified on
   the fixture; the real national TSV is a large download).
2. **Re-run cadence** — `python3 aggregate.py --source nj_records listing_scrape`
   locally on a schedule (weekly?) keeps `sales.csv` current; it's idempotent and
   additive. nj_records/redfin_dc are cloud-safe; listing_scrape needs local.
3. **price_changes / price-cut timeline** — not yet captured (HomeHarvest's basic
   scrape omits list-price history); add if a source exposes it.
4. **SR1A annual files** (optional) — NJ Treasury's full deed history (every sale,
   not just latest-per-parcel) for homes that sold 2+ times in the window.

A new source just returns sale-grain (or zip-month) dicts in the contract
documented above `fetch_nj_records` in `aggregate.py`, flips its `status` to
`live` in `sources.json`, and appears in `field_authority`; merge/CSV/provenance
already handle it.

## Independence
Self-contained routine (see root [`../CLAUDE.md`](../CLAUDE.md)). `zips.json` was
seeded from house-hunt but is **owned here** — do not import house-hunt's files.
