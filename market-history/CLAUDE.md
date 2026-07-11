# market-history — agent notes

Aggregate 3 years of NJ sold + market data across free sources, dedupe, and emit
CSVs. See [`README.md`](README.md) for layers, merge rule, and run commands.
**Status: SPIKE** — `redfin_dc` + `nj_records` are live; `listing_scrape` is the
last stub. The point is purely to *hydrate a clean dataset*, not to decide or
dashboard anything.

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
