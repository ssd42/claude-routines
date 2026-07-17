# market-history — agent notes

Aggregate 3 years of NJ sold + market data across free sources, dedupe, and emit
CSVs. See [`README.md`](README.md) for layers, merge rule, and run commands.
**Status: SPIKE** — all three layers live (`redfin_dc`, `nj_records`,
`listing_scrape`). `sales.csv` ≈ 26k merged NJ sales 2023-07→present. The point
is purely to *hydrate a clean dataset*, not to decide or dashboard anything.

## listing_scrape (live) — key facts
- HomeHarvest (Realtor.com) SOLD listings, **zip-based** (not municipality). Copies
  house-hunt's field mapping (pattern, not import). **LOCAL ONLY** — 403s in cloud.
- Fills DOM, list price, sold-vs-ask, beds/baths, garage; solar/ac_type are
  best-effort from the description text (sparse: ~1%/6%). No price-cut history.
- **Merge only cross-links with nj_records when BOTH run in the same command** —
  `--source nj_records listing_scrape`. Running one alone just appends (main()'s
  existing-row preservation won't re-merge a committed row against a new source).
- Matches nj by `address_norm+zip+sold_month`; deed-date vs MLS-close-date lag is
  tolerated (`DATE_FIELDS`, ±21d) so it doesn't false-flag as a conflict.

## nj_records (live) — key facts before you touch it
- Statewide `maps.nj.gov` Cadastral MOD-IV layer, ONE endpoint for all counties,
  queried **per municipality** from `nj_municipalities.json` (the `ZIP5` field is
  dirty — never filter by it server-side; it's kept only best-effort per row).
- Paginate with `resultOffset` + `orderByFields=OBJECTID` (indexed → fast +
  stable; ordering by the `DEED_DATE` string was ~12× slower).
- Filters: `PROP_CLASS='2'` (residential), drop SR1A non-usable codes 01–33 and
  sub-`--min-price` nominal deeds, `DEED_DATE` bounded both ends as a string range.
- **~1-yr data lag** (assessment data): recent sales come from `listing_scrape`.
- Holds the latest sale per parcel → a home sold twice in the window shows once;
  SR1A annual files would give full multi-sale history if needed later.

## Two grains — the whole layout follows from this
Every dataset here is one of exactly two things, and the directory says which:

| grain | where | what | built by |
|-------|-------|------|----------|
| **sale-grain** | top level: `sales.csv`, `market.csv`, `_provenance.json`, `history/` | one row per **transaction**, scraped | `aggregate.py` |
| **town-grain** | **`layers/`** (`seabra/`, `trader_joes/`, `wawa/`, `transit/`, `education/`, `geo/`) | one row per **town** — an attribute of a *place* | curated; joined at share time by `build_share.py` |

**`aggregate.py` never reads `layers/`.** Layers are joined in at *share* time, not
*scrape* time. New dataset? If it describes a town it goes in `layers/`; if it
describes a sale it goes in the scrape. Read [`layers/README.md`](layers/README.md)
— it holds the contract (keyed on `town`; ships as its own file in `share/`; never
merged into a sales file; never a filter).

Top-level `zips.json` / `nj_municipalities.json` / `sources.json` are **config**
(what to scrape), not data — that's why they stay out of `layers/`.

`state/` is **machine bookkeeping**, not data: `state.json` (fetch cursors — which
zip pulled when) and `provenance.json` (every source's value for every merged
field). Committed, because the repo is the DB — but nobody opens them to answer a
question, so they don't sit in the root looking like peers of `sales.csv`. So the
root reads as four things: **code, config, data, machinery.**

## Amenities — `seabra/`, `trader_joes/`, `wawa/`

Three store layers now, one contract and one maths (`nearest_store()` in
`build_share.py` serves all three). **Two Seabra assumptions turned out to be facts
about Seabra, not rules** — read those notes before copying the pattern again.

### `layers/wawa/wawa.json`
31 stores, supplied 2026-07-16. Ships as `share/wawa.csv` + `share/wawa_by_town.csv`
(`nearest_wawa_mi`, plus a `beyond_supplied_radius` flag).

- ⚠️ **The supplied list was pre-filtered to ~5mi of the target set — so it is NOT
  all NJ Wawas, and is incomplete by construction for distant towns.** 9 of 53 towns
  compute beyond 5mi (Long Valley 13.1, Glen Rock 9.2, Chester 9.0, Franklin Lakes
  9.0, Bedminster 8.5 …); for those, the real nearest Wawa may not be in the file.
  Both the CSV and the page flag it. **A big `nearest_wawa_mi` means "none close in
  our data", never "none nearby."**
- **The supplied `near_target_towns` field was DISCARDED, not stored.** It was a
  pre-baked ~5mi town match, and checked against real geocodes **26 of its pairs
  broke its own rule** (Elizabeth "near" Springfield at 7.2mi; Linden-East "near"
  Woodbridge at 6.9mi). Distance is computed from coordinates like every other layer.
  *A pre-baked answer shipped alongside data is not data — never trust one you can
  compute yourself.*
- **Geocoding needed a fallback**: 26/31 rooftop via Census, but Census cannot resolve
  route-style addresses (`16 Route 46`), so 3 fell back to OSM Nominatim by address and
  2 (Pine Brook, Mountain Lakes) to a brand+town POI lookup. `geocode_precision` is on
  every row; `osm_poi` points are approximate.

### `layers/trader_joes/trader_joes.json`
11 North Jersey stores, supplied 2026-07-16, all 11 geocoded **rooftop** by the same
key-less Census geocoder. Ships as `share/trader_joes.csv` (the store points) +
`share/trader_joes_by_town.csv` (`nearest_tj_mi` per town).

- **Only `status: open` stores count toward a distance.** West Orange (#592) is
  `coming_soon` and is excluded — a store that has not opened cannot be the nearest
  store to a house you buy today. It stays in the layer, flagged, so the record is
  complete and a rebuild picks it up automatically when the status flips. West Orange
  the *town* therefore measures 4.7mi to **Millburn**, not ~0 to the unbuilt one in
  its own town.
- ⚠️ **Unlike Seabra, four stores sit INSIDE target towns** — Westfield (the 07090
  anchor, 0.3mi), Denville, Florham Park, and coming-soon West Orange. The Seabra
  note below says "the stores sit outside the target towns... a zero-match equality
  join means you did it wrong." **That is a fact about Seabra, not a rule about
  amenities.** It is still a distance join; for four towns the honest answer just
  happens to be "it's in town."
- Range across the 53 towns: **0.3mi (Westfield) → 18.1mi**, median 4.6mi.
- North Jersey only, as supplied — a town near an unlisted southern store would read
  as further from a TJ than it is.

### `layers/seabra/seabra.json`
11 Seabra groceries, geocoded (US Census geocoder, key-less/cloud-safe; 10 rooftop,
Elizabeth fell back to its ZCTA centroid — no Census address point exists for it).
`build_share.py` measures straight-line miles from each town's zip centroid
(`layers/geo/zip_centroids.json`) to the nearest store.

**Each amenity ships as its OWN files — never as columns on a sales file.**
Seabra → `share/seabra.csv` (the store points) + `share/seabra_by_town.csv` (nearest
store per town), joinable to `by_town.csv` on `town` by whoever wants it. This
mirrors `transit.csv`. It was briefly built as extra columns *inside* `by_town.csv`
and that was wrong: it fuses a town attribute into a sales rollup, so the two can no
longer be read, versioned, or dropped independently. Don't do it again.

- **It is a NICE-TO-HAVE, never a filter.** It must not exclude or rank out a town
  or a listing, and `share/README.md` (the analyst system prompt) says so in
  caveat 5. Don't "improve" it into a score.
- The stores sit **outside** the target towns by design — this is a *distance* join,
  never a town/zip equality join. A zero-match equality join means you did it wrong.
- Straight-line, **not drive time** (~1.3–1.5× in this area), and **town-to-store,
  not house-to-store** — identical for every house in a town.

## Independence
Self-contained routine (root [`../CLAUDE.md`](../CLAUDE.md)). Keep changes inside
this folder. `zips.json` was **seeded from** `house-hunt/criteria.json` but this
routine owns it — do **not** import or read house-hunt's files; the two may
diverge. The fetch→dedupe→CSV shape is a shared *pattern*, not shared *code*.

## Shape of the work
- `aggregate.py` is the one entrypoint and is **deterministic** given the same
  raw pulls: fetch each source → `raw/<src>.json` → merge → write CSVs.
- **Merge = per-field authority** (`sources.json:field_authority`), NOT 2-of-3
  consensus — the layers are complementary, not three views of one field. Every
  source value is kept in `_provenance.json`; disagreements (beyond
  `conflict_tolerance`) are named in the row's `conflicts` column. Never silently
  drop a value.
- **Best-effort / nullable:** never drop a sale for missing amenities.
- **Dedupe is TWO layers, and the second one matters.** `merge_sales` groups on an
  exact `(address_norm, zip, sold_month)` key — which silently missed ~459 sales
  (1.7%) that the deed and the MLS spelled differently (`21 TISBURY VILLAGE` vs
  `21 Tisbury Ct`, `15 COUNTRY MEADOW LN` vs `15 Country Meadows Ln`), inflating
  every count. `coalesce_sales` is the safety net: it runs over the FULL row set
  (new + already-committed) so it repairs history too, in two sweeps —
  `address_key` + price within 1%, then the blunter `address_key_loose` (unit ids
  and directionals stripped) gated on an EXACT price match. Both sweeps also
  require the rows come from **different sources**: one source listing a street
  twice in a month is two houses (`27 Knoll Rd`, `914 Knoll Rd`), not a dupe.
  `python3 aggregate.py --dedupe-only` re-runs it over `sales.csv` with no fetch.
- **Idempotent + additive:** a run re-reads the existing CSVs and merges into
  them, so re-runs hydrate in batches. The repo is the DB — commit the CSVs +
  `history/` + `state.json`; `raw/` is gitignored.
- Adding a source = write `fetch_<src>` returning sale-grain (or zip-month)
  dicts in the contract above `fetch_nj_records`, set its layer `status` to
  `live` in `sources.json`, add it to `field_authority`. No merge changes.

## Where it runs
- `redfin_dc` + `nj_records` are **cloud-safe** (public gov/S3 data).
- `listing_scrape` 403s datacenter IPs → **local only** (residential IP), same
  constraint as house-hunt `FETCH.md`. So a fully-hydrated `sales.csv` needs a
  local run; the trend + records layers could later run in the cloud routine.

## Security (this repo is PUBLIC)
Same rules as root CLAUDE.md: never commit a secret; stage only this routine's
own files (`market.csv sales.csv _provenance.json state.json history/`), never
`git add -A`. There are no secrets in this routine today (all sources are
key-less public data); if a paid API key is added later it lives as an env var
on the routine, referenced by name only.

## Known rough edges (spike)
- `address_key_loose` (dedupe sweep 2) drops unit ids, so two different units in
  one building collide on the key. They're held apart ONLY by the exact-price +
  cross-source guard. Two units of one condo selling for the identical price in the
  same month, one recorded by each source, would fuse wrongly. Not observed, but
  it's the sharpest edge in there — tighten the guard before trusting condo counts.
- Redfin S3 URL is hardcoded (env-overridable); if it 404s, the path moved.
- `sold_date` conflict flags even a ±2-day gap between a deed record and a
  listing's "sold" mark — informative but noisy; add a date tolerance if it bites.
- `section_of` towns (Colonia, Basking Ridge, Towaco) subset the parent township
  by the dirty `ZIP5`, so a few section sales with a wrong zip may be missed and a
  few non-section sales with `ZIP5`=the section zip may sneak in. Acceptable for
  aggregation; revisit if a section needs to be exact.
- `nj_municipalities.json` MUN_NAME strings were verified live 2026-07-11; if a
  fetch returns 0 rows, re-probe that county's distinct MUN_NAME values.
- No `job.json`/schedule yet — run manually while it's a spike. `nj_records` +
  `redfin_dc` are cloud-safe and could later be scheduled; `listing_scrape` can't.
