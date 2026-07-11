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
