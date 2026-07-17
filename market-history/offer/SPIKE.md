# SPIKE — "Offer Advisor": a single-page tool for pricing an offer

**Status:** proposal, v2. Nothing built.

**Ask:** type an address + asking price → get a suggested number, informed by
(a) **comparable homes** in that town (similar sqft / beds / baths) and (b) how homes
in that town historically close **above/below ask** in a given month, with a **month
slider** to see the offer move. Plus nearest Seabra and a typical train time.

**v2 changes:** comps are **in** — measured, and they earn their keep. But the
tolerance has to be looser than ±10%, and the comp filter and the month **must never
be applied to the same number.** That constraint is what makes the slider work.

---

## 1. Two estimators, deliberately kept apart

The measurements below (§2, §3) point to one structure, and it's the core of this spike:

| | **Level** — "what is this house?" | **Seasonal factor** — "what does the market do to an ask *now*?" |
|---|---|---|
| answers | what comparable homes actually sold for | how much over/under ask homes close, this month |
| filtered by | town + sqft±15% + beds±1 + baths±1 | town + closing month |
| **pooled across** | **all months** | **all house types** |
| sample size | n ≈ 13–30 | n ≈ 14–30 |
| source | `sales.csv` comp query | `by_town_month_of_year.csv` |
| drives | the "comps suggest ~$694K" line | **the slider** |

**They are never intersected.** Comps ∩ month = n≈1 (§3) — that's the whole reason the
naive version of this fails. Seasonality is a *market-wide* effect: it applies to the
3-bed ranch and the 5-bed colonial alike, so we measure it on the big all-houses bucket
and apply it to your specific house. The level is *house-specific*, so we measure it on
the comp set and pool every month to keep n alive.

Splitting them this way is what lets **both** numbers rest on 15–30 real sales instead
of one number resting on 1.

---

## 2. Comps: yes, but ±10% is too tight

I ran your exact spec against `sales.csv`. First, the universe:

| filter | rows | |
|---|---:|---|
| all sales | 38,015 | |
| has usable `sqft` | 14,097 | 37% |
| **+ beds & baths** | 7,106 | 19% |
| **+ a real list price** | **6,917** | **18%** ← the comp universe |

So a comp query runs against **18% of the data**, not 100%. Median town has 93 such
rows across three years; **10 of 53 towns have under 50.**

Now your ±10% / same-beds rule, on real houses:

| query | strict `sqft±10%`, beds exact | relaxed `sqft±15%`, beds±1, baths±1 |
|---|---:|---:|
| Clark, 1800sqft 3/2 | **6 comps** → $446/sqft | **22 comps** → $386/sqft |
| Cranford, 1600sqft 3/1.5 | **4 comps** → $484/sqft | **13 comps** → $449/sqft |
| Westfield, 2400sqft 4/2.5 | **8 comps** → $389/sqft | **20 comps** → $454/sqft |
| Boonton, 1500sqft 3/2 | **7 comps** → $368/sqft | **13 comps** → $372/sqft |

**Strict gives 4–8 comps over three years — and you can see it's noise, because
loosening the filter moves the answer more than it should.** Clark strict implies
$803K; Clark relaxed implies $694K. A $109K swing from a tolerance tweak means the
$803K was six houses' worth of luck, not a signal. Same story in Cranford ($774K →
$718K).

**Recommendation: default to relaxed (sqft±15%, beds±1, baths±1), n≈13–30**, with the
tolerance exposed as a control so you can tighten it and *watch n collapse* — seeing
the sample size fall to 6 is the most honest thing the UI can show you.

### The comp filter genuinely adds signal — this is the argument for building it

Comps aren't just a thinner version of the town average. They land somewhere different:

| | comp $/sqft | town-wide $/sqft | gap |
|---|---:|---:|---:|
| Clark 1800 3/2 | $386 | $351 | **+10%** |
| Boonton 1500 3/2 | $372 | $313 | **+19%** |
| Cranford 1600 3/1.5 | $449 | $382 | **+18%** |
| Westfield 2400 4/2.5 | $454 | $454 | 0% |

Smaller/mid homes carry a materially higher $/sqft than their town's blended average —
so a town-average valuation would **under**value them by 10–19%. That's the case for
doing comps at all. (Westfield landing at zero is a coincidence of that query, not a
rule.)

**Always output a band, never a point.** Clark's relaxed comps run **p25–p75 = $331–$444
/sqft** → on 1800 sqft that's **$596K–$800K**, median $694K. That band *is* the finding:
the spread is wide because condition, kitchen, and block aren't in our data and never
will be. A single "$694K" hides that; the band tells the truth.

---

## 3. Why the slider can't touch the comps

Clark, 1800sqft 3/2, strict comps, **broken out by closing month**:

```
  Apr 1 · Jun 1 · Sep 1 · Nov 1 · Dec 2       ← 6 comps, spread over 5 months
```

**One comp per month.** Slice the comp set by month and the slider is dragging a number
built from a single house. That's not a weak estimate, it's a random one — and it would
jump around wildly as you drag, *looking* like seasonality while actually being noise.

So: **the slider moves the seasonal factor only**, which is measured on the full town ×
month bucket (Clark: n=13–29 every month, no month thin). Same house, same comps, same
level — only the market's ask-premium changes as you drag. That's a real effect and it
holds up: Clark reads **−0.78% in Jan** (57% of sales at-or-under ask) and **+5.01% in
Aug** (3.7% at-or-under). On a $700K ask that's a genuine **~$40K** swing, and the
slider's whole job is to make it visible.

---

## 4. What the page shows

Three numbers, sourced differently on purpose, and the *comparison between them* is the
actual product:

```
  12 Maple Ave, Clark            Asking: $700,000       1,800 sqft · 3bd · 2ba

  ① COMPS SAY          $694,000        band $596K – $800K
     22 similar Clark homes (sqft±15%, beds±1, baths±1) · all months pooled

  ② THE ASK IS         $700,000        ~in line with comps  ✓
     (if ask sits above the p75 band → "this ask is rich vs. comps")

  ③ SEASONAL FACTOR   ◀───────●──────────────▶   [ SEP ]   ← the slider
     Clark homes closing in Sep: median +0.02% vs ask (n=21)
     47.6% closed at or under ask

     ─────────────────────────────────────────────
     EXPECTED CLOSE   ~$700,100     on this ask, in September
     ─────────────────────────────────────────────

     drag to JAN → −0.78%, 57% at-or-under → ~$694,500   ⬇ $5,600
     drag to AUG → +5.01%,  3.7% at-or-under → ~$735,100   ⬆ $35,000
```

The interesting cell is **②**. Comps and ask are computed independently, so when the ask
lands outside the comp band, that's the tool earning its keep: *"comps say $596–800K,
they're asking $875K — that's above the top of the band."* The seasonal factor is then
applied to **the ask** (the market bids relative to whatever the seller wrote down),
never to the comp figure.

**The slider is the seasonal factor's control, and nothing else's.** Label it that way.

---

## 5. Which month does the slider default to?

Rollups bucket a sale by **`sold_date` — the closing month, not the offer month.** Median
list-to-close is **63 days**, so a July offer most likely *closes* in September.

Default the slider to **today + 63 days** (≈ the projected closing month), and label it
"closing month," not "current month." Show the offer-month figure as a ghost mark on the
slider so the assumption is visible rather than hidden — for July that's +5.67% vs
September's +3.72%, a $13K difference on a $700K ask.

⚠️ `days_on_market` in our data is **list-to-closing, not list-to-contract** (DEFECTS.md
#3 — no row shows the 30–60 day escrow leftover). **The offer-accepted date is not in
this dataset in any form.** So "offer today → close in ~63 days" is our assumption, not
a fact the data proves. Say so under the slider.

---

## 6. Fallbacks — each estimator has its own ladder

Two estimators, two independent ladders. Neither ever falls back across towns.

**Level (comps)** — stop at the first tier with n ≥ 10:
1. town + sqft±15% + beds±1 + baths±1 → 2. town + sqft±25% + beds±1 → 3. town + sqft±25%,
any beds/baths → 4. **refuse**; show only the ask-relative number and say why.

> **Every tier stays anchored to the subject's sq ft — there is deliberately no
> "town-wide average $/sqft" tier.** The first build had one, and the sanity pass caught
> it: a 9,000 sqft house in Boonton fell through to it and confidently answered **$2.8M**,
> by applying a $/sqft blended off the town's typical ~1,500 sqft houses to a house six
> times larger than anything in the sample. Sq ft is the dimension $/sqft is most
> sensitive to, so it is the one the ladder may never relax. If nothing in the town is
> within ±25% of this size, we don't know, and the page says so. `build_data.py`
> **doesn't even export** a town-wide $/sqft — shipping it would just re-arm the mistake.

**Seasonal factor** — stop at the first tier with n ≥ 10:
1. town × month-of-year (**88%** of the 635 buckets clear this) → 2. town × season (98%)
→ 3. town, all-year (100% — 0 thin towns) → 4. refuse.

When the seasonal factor falls back to season or year, **the slider must visibly
coarsen** — snapping to 4 seasonal steps, or locking with "Clark's months are too thin;
using Fall." A slider that keeps sliding smoothly while secretly reading one annual
number is a lie told 12 times.

**Never fall back across towns.** No county tier, no all-NJ tier — that silently answers
a different question. If the town isn't in `by_town.csv`, refuse and offer the nearest
towns we do have.

**Denominators:** every ask-based figure uses `n` (sales with a known list price, ~60%),
never `sales_all`. **Medians only** — `sold_vs_ask_pct` reaches **+980%** on placeholder
list prices; drop anything outside ±50%.

---

## 7. Architecture

The comp query changes this from v1: comps need **row-level** data, not rollups.

```
market-history/offer/
  index.html      # markup + styles + logic, one file
  data.js         # generated: window.OFFER_DATA — comp rows + month curves + town refs
  build_data.py   # regenerates data.js from ../share/ + ../analysis/<date>/
```

⚠️ **A `file://` page cannot `fetch()` a local CSV** (Chrome blocks it cross-origin). Since
the appeal is "double-click and it opens," data must arrive via a `<script>` tag — hence
`data.js` assigning a global, not CSVs read at runtime.

**Payload:** ship the **6,917-row comp universe**, not all 38k, and only 5 fields each
(`town, sqft, beds, baths, sold_price`) — plus the 636 month-curve rows and 53 town
reference rows. Estimate: **~250–350 KB**, fine to inline; a build-step trim (drop the
address, round the numbers) keeps it there. `sales.csv` (5.7 MB) never reaches the
browser. Comp filtering is a single `.filter()` over an array — instant, and it re-runs
live as you drag the tolerance.

**Where it lives:** inside `market-history/`, consuming *that routine's own* `share/` and
`analysis/` outputs — no cross-routine import, no independence-rule violation. It's a
**viewer**, not a scheduled routine: no `job.json`, no cron, no state. Re-run
`build_data.py` after `sales.csv` grows.

---

## 8. Seabra + transit (a town lookup, and only colour)

Both files are already town-grain, so this is a join:

- **Seabra** — `seabra_by_town.csv` → `nearest_seabra_mi`, `nearest_seabra_store`.
  **Straight-line, town-centroid to store** — *not* drive time (real drive ≈ 1.3–1.5× in
  this part of NJ), and **identical for every house in the town.** Label it "nearest
  Seabra to **Clark**," never "to your house."
- **Transit** — `transit.csv` → `best_transit_minutes`, `best_transit_mode`,
  `station_name`, `confidence`, and **`notes` rendered verbatim.** That's where the truth
  is: Westfield and Cranford are Raritan Valley Line, which has **no one-seat peak ride to
  NY Penn** — every peak train changes at Newark Penn. Printing "55 min ✅" and hiding
  that is worse than no tool. For towns with no station the figure **excludes drive/park
  time** (add 10–20 min; more for Roseland, Livingston, South Plainfield, Chester, Long
  Valley).

Both are **colour, never inputs.** They don't move the offer, don't rank the town, don't
gate anything (`share/README.md` caveat 5).

---

## 9. What the page must say out loud

On the page, next to the numbers — not in a README:

1. **Sample size + filter, inline on every figure.** "22 comps," "n=21, Clark × Sep."
2. **Bands, not points.** A bare median reads as a promise.
3. **"Condition is not in this data."** No renovation status, no photos, no block. A
   gut-renovated and a deferred-maintenance house with identical sqft/beds/baths are the
   same row to us. **That is why the band is wide, and the band is the honest answer.**
4. **The comp universe is 18% of sales** — the 82% without sqft/beds/baths aren't
   missing at random, they're mostly deed records.
5. **Data window 2023-07-01 → 2026-07-13.** Outside it, refuse; never project.
6. **The closing-month assumption** (§5), under the slider.
7. **Transit `notes` + `confidence`, verbatim** (§8).

---

## 10. Open questions

1. **Property type.** Everything above pools Single Family + Condo + Townhouse +
   Multi-Family. A condo and a colonial don't behave alike vs. ask — but beds/baths/sqft
   already separate them *implicitly*, and an explicit filter thins the comp set further.
   **Suggest: v1 pools, and says so.**
2. **Should the comp band drive a "walk-away" line?** Tempting to print "don't go above
   $800K (comp p75)." I'd resist in v1 — p75 is a quartile of a 22-house sample, not a
   verdict, and dressing it as advice invites acting on it.
3. **Outlier condition.** Clark's comp $/sqft spans $331–$444. Some of that spread is
   genuinely *condition* (invisible to us) and some is *block*. There's no way to
   separate them with this data. Accept the band; don't try to model it.
4. **`list_date` defects** (1,862 rows, DEFECTS.md #1/#2) — sold-vs-ask is **unaffected**
   (the *price* is genuine, only the *date* is junk), so both estimators are safe. But
   `median_dom` and anything list-date-derived must come from the defect-excluded
   `analysis/` rollups, never recomputed off raw `sales.csv`.

---

## 11. Scope

| step | what |
|---|---|
| 1 | `build_data.py` — comp universe (6,917 × 5 fields) + month curves + town refs → `data.js` |
| 2 | Comp engine: filter, tolerance ladder, median + p25/p75 $/sqft → level band |
| 3 | Seasonal engine: town × month curve + fallback ladder (and slider coarsening) |
| 4 | `index.html` — town/zip autocomplete (no geocoder: resolve on the town/zip token, **never** substring-match the address — `10 Cranford Rd` is a house in *Glen Rock*), ask + sqft/beds/baths inputs, the three-panel output, month slider |
| 5 | Sanity pass: **(a)** Clark $700K @ Jan vs Aug differs ~$40K; **(b)** tightening tolerance to ±10% visibly drops Clark to n=6 and *moves the estimate $109K* — if the UI doesn't make that feel alarming, the UI is wrong; **(c)** a 1-comp query refuses instead of answering |

The data work is mostly done. The risk isn't effort — it's the tool being *confidently
wrong*, which is why §1–§3 are most of this document.
