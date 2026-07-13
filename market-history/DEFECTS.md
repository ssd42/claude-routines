# Known data defects — `sales.csv`

A registry of rows we know are **wrong**, so a future re-scrape can be checked
against it. Nothing here is fixed in the data; this is the list of what to fix
and how we'd know it worked.

**Scan:** `python3 analysis/defects.py` → writes one CSV of offending rows per
check into `analysis/defects/<date>/`, plus `_summary.csv`. Re-run after any
re-scrape and diff the summary: a defect that drops to 0 is fixed, one that grows
is a regression.

**Latest scan — 2026-07-13 (post-fix), 38,025 rows. 0.5% of rows fail a check**
(was 10.3%). The re-scrape + `validate.py` landed; defects 1 and 2 are **fixed**.

| check | sev | before | after | status |
|-------|-----|-------:|------:|--------|
| [`list_date_after_sold_date`](#1-list_date_after_sold_date) | HIGH | 1,696 | **0** | **FIXED** ✅ |
| [`list_date_is_batch_sentinel`](#2-list_date_is_batch_sentinel) | HIGH | 166 | **0** | **FIXED** ✅ |
| [`days_on_market_disagrees`](#3-days_on_market_disagrees) | MED | 1,969 | **38** | was mostly a false alarm — see below |
| [`sold_vs_ask_extreme`](#4-sold_vs_ask_extreme) | MED | 152 | 152 | known, mitigated (source-side) |
| [`sqft` is single-sourced](#5-sqft-is-single-sourced--there-is-no-second-opinion) | HIGH | n/a | — | **structural — unscannable** |
| `ask_pct_without_list_price` | HIGH | 0 | 0 | clean ✅ |
| `no_sold_price` | HIGH | 0 | 0 | clean ✅ |
| `no_sold_date` | HIGH | 0 | 0 | clean ✅ |

### What the fix was

`list_date` is a **record-ingestion timestamp**, not a listing date. Realtor.com
stamps every property in a bulk-refresh batch with the refresh time — 463 rows
across 51 towns all carried `2024-08-04 14:51:57`, identical to the second.

`aggregate.py` now catches it two ways (impossible date; timestamp reused across
properties) and **rebuilds from `days_on_mls` where that survives, nulls otherwise,
flags always**. `validate.py` repeats the repair over the **whole committed set** —
which matters, because `aggregate.py` is additive: a row it doesn't re-fetch is
carried over verbatim, so 36 corrupt rows survived the re-scrape untouched and only
pass 2 could reach them. **That is the self-healing property: a fix reaches three
years of history offline, with no network call.**

### One number went UP before it went down — the registry working

The first post-fix scan showed `days_on_market_disagrees` *rising*, 1,969 → 2,110.
Cause: **`sold_date` has two definitions.** `field_authority` prefers the deed's
RECORDING date, while `days_on_market` is measured against the MLS CLOSING date, and
the two differ by days. On a deed-merged row the subtraction *cannot* close — the
check was flagging a definition, not a defect. Both scanners now apply the deed
tolerance (±21d, matching `DATE_FIELDS` in `aggregate.py`) and the true count is **38**.

### What the re-scrape also recovered

- **`pending_date` — 0% → 48%.** The **offer-accepted date**, which the scraper was
  fetching and the merge was silently discarding (it wasn't in `field_authority`).
  This is the field every "when should we bid" question actually needs; `sold_date`
  trails it by a ~41-day escrow. Measured: **15 days list → under contract, 41 days
  contract → close.**
- **Garage on deed rows — 5% → 11%.** `_parse_bldg_desc` only recognised `AG`
  (attached) and dropped `DG` (detached) entirely. Across 2,400 parcels `DG` appeared
  127 times against `AG`'s 123 — it was the **most common garage in the data** and
  every one was recorded as "no information."
- **Invented sqft removed.** `BLDG_DESC` carries no square footage (zero of 2,400
  parcels), but the old regex matched digits out of the structure code and produced 49
  "houses" of 4, 6, 22 and 35 square feet. Deed-row `sqft` is now NULL, which is true.
- **`bldg_desc` stored verbatim (29%).** The string the garage parser reads. The bug
  above was only findable by going back to the network; now the next parser fix
  re-applies to history offline.

---

## 1. `list_date_after_sold_date`

**1,696 rows (4.46%). The house was "listed" after it sold.**

Every one of these rows comes from `listing_scrape` (848 scrape-only, 848 merged
with a deed record). No other source contributes a `list_date`, so this is a
Realtor.com/HomeHarvest defect, not a merge defect.

### It is not a relist — it's a batch artifact

The obvious theory is that the scrape returned a *relisting* date for a house that
sold and went back on the market. That theory is wrong, and the data says so:

- **The addresses never repeat.** 0 of 1,696 appear twice in `sales.csv`. A relist
  would mean two sales of one house; there is only ever one.
- **The bad dates are shared by hundreds of unrelated houses.** 463 of these rows
  — spread across **51 different towns** — carry the identical `list_date` of
  `2024-08-04`. Another 165 rows across 46 towns share `2024-03-13`. A real listing
  date is nearly unique to a house; for comparison, the 22,843 healthy list-dated
  rows spread over 1,279 distinct dates.
- **`days_on_market` is blank on essentially all of them** (11 of 1,696 have it).

So the scraper is substituting a **fixed placeholder date** — most likely the date
of the scrape batch — into rows where the true listing date was unavailable. These
are not dates. They are nulls wearing a date's clothes.

**Proven-bogus values so far** (a date is "proven bogus" when ≥20 rows carry it and
>50% of them sold before it):

`2024-01-02` · `2024-03-13` · `2024-03-31` · `2024-08-04` · `2024-08-11` ·
`2024-08-30` · `2025-01-31` · `2025-07-23` · `2025-09-19` · `2026-03-30` ·
`2026-04-19`

### Impact
Any `list → close`, time-on-market, or "when did this hit the market" figure is
wrong for these rows. **Sold-vs-ask is NOT affected** — `list_price` looks
genuine; only the *date* is junk.

### Proposed fix
In `aggregate.py`, when a `listing_scrape` row has `list_date > sold_date`, **null
the `list_date`** (and `days_on_market`, already blank) rather than carrying it.
Blank is honest; a wrong date is not. Keep `list_price` / `sold_vs_ask_*`.

Better, upstream: work out what HomeHarvest field is actually being read and
whether a real `list_date` is available on those listings at all. If the fix lands,
this check should drop to **0**.

### Interim rule for analysis
**Exclude these rows from anything that uses `list_date`.** `analysis/seasonality.py`
does this via `--exclude-defects` (on by default). Sold-vs-ask work can keep them.

---

## 2. `list_date_is_batch_sentinel`

**166 rows (0.44%). The dangerous one.**

These rows carry one of the **same proven-bogus dates** as defect #1 — but their
`sold_date` happens to fall *after* the placeholder, so nothing looks wrong. They
pass every sanity check and they are still holding a fabricated date.

Example: `2024-08-04` is a placeholder appearing on 466 rows; 463 sold before it
and get caught, **3 sold after it and sail through**. `2024-03-13` hides 41 such
rows; `2025-07-23` hides 27.

This is why defect #1's count understates the problem. The true population of rows
with a fabricated `list_date` is **1,696 + 166 = 1,862**, and only the first 1,696
are self-evident.

### Open question — how much bigger is this really?
Several dates carry 60–75 rows across 30+ towns with **zero** impossible rows
(`2024-05-15`, `2025-05-14`, `2025-09-10`, `2024-05-29`, `2026-04-15`). Those are
either **more placeholders** whose date happens to precede every sale, or just
**genuinely busy listing Thursdays** across 53 towns. **From this data alone the
two are indistinguishable** — and guessing would be worse than admitting it.

Resolving it needs one of:
- a **re-scrape**: a real `list_date` is stable across runs; a batch placeholder
  moves to the new run's date. Scrape twice and diff — the ones that move are fake.
- reading HomeHarvest's field semantics to find what's actually being populated.

Until then, treat any high-frequency `list_date` with suspicion.

### Proposed fix
Same as #1 — nulling on the scrape side kills both at once.

---

## 3. `days_on_market_disagrees`

**1,969 rows (5.18%).** `days_on_market` differs from `sold_date − list_date` by
more than 3 days.

`days_on_market` is otherwise a **pure restatement** of that subtraction — across
the healthy 20,956 rows it matches to within 1 day 85.9% of the time and within 3
days 90.6% of the time, with identical medians (63) and means (75.0).

**This is worth internalising: `days_on_market` is list-to-CLOSING, not
list-to-contract.** It does not tell you when the offer was accepted. Not a single
row shows the 30–60 day leftover an escrow period would produce. **The offer date
is not in this dataset in any form.**

Most of these 1,969 rows overlap defect #1 (a corrupt `list_date` makes the
subtraction disagree by construction). Fixing `list_date` should shrink this
substantially. Whatever survives is a genuine third-party disagreement worth a look.

### Proposed fix
Re-check after #1 lands. If a residue remains, decide which of the three fields is
authoritative and derive the other — don't carry two contradictory numbers.

---

## 4. `sold_vs_ask_extreme`

**152 rows (0.40%).** `|sold_vs_ask_pct| > 50%`, reaching +980%.

Nominal or placeholder **list prices** (a $1 or $10 list against a real sold price).
Not a bug we introduced — it's in the source.

**Already mitigated, not open:** every rollup's `mean_` column excludes them
(`outliers_excluded_from_mean` counts them), and `share/README.md` tells the analyst
to prefer medians. Tracked here only so the count stays visible.

### Proposed fix
None needed. If it ever grows sharply, the source changed.

---

## 5. `sqft` is single-sourced — there is no second opinion

**Not a corrupt value: a missing cross-check.** Unlike 1–4 this isn't a row-level
defect, so `analysis/defects.py` can't scan for it. It is a **structural** gap, and
it is the one most likely to make a downstream tool confidently wrong.

`sqft` is carried by **`listing_scrape` only** — present on ~50% of MLS-sourced rows
and **1% of deed-sourced rows** (42 of 7,291 deed-only rows). So:

- The **`conflicts` column can never fire on `sqft` in any useful way.** It flags
  exactly **10 rows of 38,015** — not because the sources agree, but because the
  second source almost never has a value to disagree *with*.
- Any figure keyed on size — every $/sqft comp, the whole `offer/` tool — rests on a
  number **nothing corroborates**.

**Live example.** 93 Gaywood Ave, Colonia (Block 499.02, Lot 11): the MLS says
**1,108 sqft**; the MOD-IV tax card says **1,188**. A 7% gap, and we are structurally
incapable of noticing it. The house is a 1944 Cape whose listing advertises a
second-floor primary suite while `BLDG_DESC` reads `1S S F` — *one story* — so the
true living area is likely above **both** recorded numbers.

### Why `aggregate.py` isn't wrong, exactly

The comment at `aggregate.py:378` — *"BLDG_DESC does NOT contain square footage"* — is
**correct for the endpoint we query**. Verified live against
`Framework/Cadastral/MapServer/0`: 46 fields, and not one is a living area
(`BLDG_DESC`, `LAND_DESC`, `CALC_ACRE`, `BLDG_CLASS` … no `SQ_FT` / `SFLA`).

**But MOD-IV does carry it — in a different file.** The living area sits in the MOD-IV
**assessment (SR1A / MOD4 property) file**, not the GIS cadastral layer. That's where
NJParcels gets the 1,188.

### Proposed fix
Add the MOD-IV tax file as a **fourth source** in `sources.json`, joined on `PAMS_PIN`
(already present on every deed row). That gives an independent `sqft` on most of the
~39% of rows with a deed record — which makes `conflicts` meaningful on `sqft`, grows
the 18% comp universe, and gives `offer/` a real second opinion instead of a
disclaimer. See [`offer/FOLLOWUPS.md`](offer/FOLLOWUPS.md) #1.

**How we'd know it worked:** a new check, `sqft_disagrees` (|MLS − tax| > 5%), goes
from *unmeasurable* to a real number. Today it cannot even be computed.

---

## Adding a check

Append to `CHECKS` in `analysis/defects.py`. A check is
`(id, severity, description, fn)` where `fn(rows)` returns the defective rows.
Most wrap a row predicate in `each(...)`; a check that needs to see the whole set
first — like `list_date_is_batch_sentinel`, which must learn which dates are bogus
before it can judge a row — takes `rows` directly.
