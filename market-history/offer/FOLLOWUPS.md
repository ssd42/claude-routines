# offer/ — followups

Ranked. Each one came out of a real house (93 Gaywood Ave, Colonia — asking
$625,000, listed 1,108 sqft) where the tool was confidently wrong, or nearly was.

**Done already:** the *verdict-flips-at* line under the comp band (`flipPoint()` in
`index.html`), which walks sq ft outward until the answer changes and flags it when
that happens within 20%.

---

## 1. Get a second source for `sqft` — the blocker behind everything else

**Sq ft is the most load-bearing input in the tool and we have no way to check it.**

- The MLS (`listing_scrape`) is the **only** source that carries one: it's on 50% of
  MLS-sourced rows and **1% of deed-sourced rows**.
- So `sqft` is single-sourced. `sales.csv` has a `conflicts` column built for exactly
  this — it fires on `sqft` for **10 rows out of 38,015**, not because the sources
  agree but because the second source almost never has a value to disagree *with*.
- At 93 Gaywood the MLS said **1,108** and the tax card said **1,188** — a 7% gap we
  are structurally incapable of noticing.

**Why we can't fix it in `aggregate.py` today.** The comment at `aggregate.py:378`
("BLDG_DESC does not contain square footage") is **correct for the endpoint we
query**. The Framework/Cadastral MapServer layer has 46 fields and *none* of them is
a living area — verified live:

```
OBJECTID, PAMS_PIN, PCLBLOCK, PCLLOT, COUNTY, MUN_NAME, PROP_CLASS, PROP_LOC,
LAND_VAL, IMPRVT_VAL, NET_VALUE, BLDG_DESC, LAND_DESC, CALC_ACRE, BLDG_CLASS,
DEED_DATE, YR_CONSTR, SALE_PRICE, DWELL, ...          # no SQ_FT / SFLA / LIV_AREA
```

**The living area lives in a different file.** NJParcels shows `1188` for this
parcel, sourced from the **MOD-IV assessment (SR1A / MOD4 property) file**, not the
GIS cadastral layer. That file carries building dimensions.

**Do this:** add the MOD-IV tax file as a fourth source in `sources.json`, keyed on
`PAMS_PIN` (already on every deed row). It would give an independent `sqft` on ~all
39% of rows that have a deed record, which:
- lets `conflicts` actually fire on `sqft` and mean something,
- turns the comp universe's 18% coverage into something much larger,
- and gives the offer tool a real second opinion instead of a disclaimer.

This is the single highest-value thing left in `market-history`, not just in `offer/`.

---

## 1b. `pending_date` coverage is uneven, and the per-town contract curve is noisy

Opened by the move to **contract grain** (2026-07-13). The model is right — on identical
rows, bucketing on `pending_date` instead of `sold_date` sharpens the seasonal swing from
**4.88pp to 6.00pp** and moves the cheapest month from January to **December** — but the
sample underneath it is weak in two distinct ways:

**a) The subset is biased.** Only **79%** of askable sales report an offer-accepted date,
and they sold **+4.76%** over ask against **+2.45%** for the rest — a gap that persists
*inside every year* (2026: +4.05pp), so it's a reporting bias, not a market trend.
**Handled**: `build_data.py` takes the *level* from all the town's sales and only the
month-to-month *shape* from the contract subset, so the bias cancels. Verified: mean
rebased factor +4.66% vs mean town level +4.79%.

**b) Coverage is wildly uneven, and thin towns get a noisy shape.** Colonia reports on
**23%** of sales, Edison **13%**, Long Valley **95%**. Colonia's contract-month buckets run
n=4–15, which produces an obviously junk curve (9.28pp swing; "cheapest month = July" on
**7 sales**). The fallback ladder catches the worst — months under 10 coarsen to the
contract *season* — but **`THIN = 10` is too permissive for a *deviation* estimate**: the
buckets that squeak past at n=10–15 still swing 7pp on noise.

**Do this:** raise the floor for the *shape* specifically (n≥20?), or shrink each town's
monthly deviation toward the all-towns pooled curve in proportion to its sample size
(James–Stein style). A town with 7 sales in July should barely move off the regional shape;
today it moves all the way.

---

## 1c. Fill the 378 houses that publish no lot — MOD-IV has it, we already query it

"Unknown" on the market page is really TWO problems, and they need opposite treatment:

* **Lot — small and fixable.** Only **378 of 2,494 single-family listings (15%)** lack
  a lot size. The other "missing" lots are **condos and townhouses, where missing is
  CORRECT** — an attached unit owns no land. So the lot data is already 85% complete
  for actual houses.
  **The 378 are fillable:** NJ MOD-IV carries `CALC_ACRE` on every parcel and
  `aggregate.py` already queries that endpoint per municipality. Join listings to
  parcels on `address_key` (the same key `property_key` is built from) and most of the
  378 should resolve. Watch the pagination — the endpoint caps at 1,000 rows and
  Scotch Plains alone exceeds it, so use `resultOffset` + `orderByFields=OBJECTID` the
  way `fetch_nj_records` does. A probe without pagination matched only 12%, which is a
  paging artifact, not a data limit.

* **House sq ft — big and NOT fixable this way.** **1,710 of 2,494 houses (69%)**
  publish no size, and the cadastral endpoint has **no living-area field at all** (46
  fields, none is sqft — see [`../DEFECTS.md`](../DEFECTS.md) #5). It needs the MOD-IV
  **assessment** file, which is followup #1 above. Same root cause as the analyser's
  single-sourced `sqft`.

**Meanwhile the page ranks rather than drops** (`Closest to my lot`): an unknown sorts
last but never leaves the list, and the row says whether it's "no land" (an attached
home — correct) or "lot not listed" (a gap we could close).

---

## 2. Let sq ft be a range, not a point

Follows directly from #1. You rarely *know* the living area — you know it's "1,108
per the MLS, 1,188 per the tax card, and there's an unrecorded second floor." Take a
low/high and widen the band to match. An honest wide answer beats a precise wrong one.

---

## 3. Catch the story-count contradiction

The tax card says `BLDG_DESC = 1S S F` — **one story**. The listing sells "the primary
bedroom suite on its own **second floor**." That contradiction is *signal*: on a 1944
Cape it's the fingerprint of a **finished attic that never reached the assessor**, which
means the recorded sq ft is low.

We already parse `BLDG_DESC` for garage codes, so the story count is right there. If
the user says "2 floors" and the record says `1S`, say so:

> *Records show 1 story; you've described 2. The sq ft on file may understate this
> house — which would move the verdict.*

---

## 3b. Disamenities we structurally cannot see — rail lines, and the parcel-grain problem

Raised by a real house: **63 Lyons Ave, Woodbridge** has the rail line running behind
its back yard. That is almost certainly suppressing its price, and **we cannot see it
at all** — `sales.csv` carries an address and a zip, **no coordinates**, and the tool
has no geocoder.

Today that disamenity is silently *inside* the comp band: track-adjacent and
quiet-street houses are pooled together, and it is part of **why the band is wide**. We
can't attribute any of the spread to it.

**Buildable, and cheaper than it sounds.** We already geocode with the US Census
geocoder for the Seabra layer (free, key-less, cloud-safe). So:
1. Geocode sale addresses → lat/lon per sale.
2. Take NJ's public rail-centerline GIS → distance-to-track per sale.
3. It becomes both a **comp dimension** and a **callout** ("this house is 80m from the
   NEC; track-adjacent sales in this town run X% below").

**The blocker is grain, not effort.** Distance-to-track is genuinely **parcel**-level,
which does *not* fit the town-grain contract in [`../layers/README.md`](../layers/README.md)
— the same problem as flood risk (#4). **Decide where parcel-grain features live before
building either.** Geocoding the sale rows would unlock both at once, plus school
catchment and anything else that varies within a town.

---

## 4. No flood data anywhere in `market-history`

93 Gaywood is **partially in an AE flood zone** (~1.12% of the parcel, per NJParcels).
We carry nothing on flood risk in any layer. It's public (FEMA NFHL), it's material to
a buyer, and it's a clean town- *or* parcel-grain addition. Note the grain question:
flood risk is genuinely **parcel**-level, so unlike Seabra/transit it does *not* fit the
town-grain layer contract in `layers/README.md` — decide where it lives before building.

---

## 5. Smaller

- **Property type is pooled.** Single Family + Condo + Townhouse + Multi-Family all sit
  in one comp set. Beds/baths/sqft separate them implicitly; an explicit filter would
  thin every bucket ~4×. Revisit when the comp universe is bigger (see #1).
- **`price_changes` is empty on every row**, so we cannot see whether an over-asking
  listing later cut. That's precisely the question a rich ask raises, and we can't
  answer it.
- **The town price index needs ≥10 sales/year** to be town-specific; 7 of 53 towns fall
  back to the regional curve. The page flags this, but more data would shrink it.
