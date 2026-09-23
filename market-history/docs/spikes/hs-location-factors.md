# SPIKE — four location factors for HS

**Status:** appreciation ✅ and flood ✅ **BUILT & LIVE** (2026-07-18). Crime and noise
still proposed — they need external datasets (see §3, §4).

Four things a serious buyer weighs that HS currently ignores: **flood zone**, **crime**,
**airport/highway/rail noise**, and **town appreciation**.

Per the ask: appreciation shows a visible **average on the pages**; the other three are
**HS inputs only** — they move the score and appear in its click-to-open breakdown, but
they are not standalone displayed metrics.

---

## The unlock they share, and why now

All four are buildable **without the geocoding project I keep deferring**.

- **Flood and noise** are per-house, but our listings already carry `lat`/`lon` on ~100%
  of rows. No address geocoding needed — the point is already there.
- **Crime and appreciation** are town-level, so they need no coordinates at all.

One structural consequence: flood and noise exist only where we have a point, i.e. on
**listings**. Sold rows have no coordinates. That's fine — **HS runs on listings**, so a
listing-only factor is exactly right. The weighted-mean design already drops any factor
we can't compute for a given house, and confidence falls to say so.

---

## 1. Town appreciation — ✅ BUILT (HS w=4 + shown on both pages)

Live: HS factor at weight 4 (small, per the r=+0.61 with price), and shown on the market
and sold pages as "+14% since '23" on each town line, with a `*` where the rate is
borrowed regional rather than measured. 20 towns measured, 43 borrowed. Below is the
original reasoning.

### original spike notes

**We already have it.** The price index built for the analyser is per-town appreciation:
2023 → today, **6.9% (Morristown) to 48.4% (Summit)**, median 16.5%.

**Display (the visible part):** a town's average appreciation, shown on the market page
and the sold page as colour next to the town — "Summit · +48% since 2023".

**As an HS factor (open question — see below):** reward towns whose value is climbing,
because a buyer's equity grows with it.

⚠️ **Two honest limits, both load-bearing:**
- **Only 20 of 63 towns have a *measured* rate**; the other 43 borrow the regional curve
  (the price-index sanity guards refuse a thin or implausible town). So the displayed
  number is real for a third of towns and borrowed for the rest — it must say which, the
  same way the analyser already flags a borrowed index.
- **Appreciation correlates with price at r = +0.61.** It is *not* independent of the
  price factor HS already weights at 30. So if it feeds HS at all, it earns a **small**
  weight — its unique signal is modest, and past appreciation doesn't promise future.

---

## 2. Flood zone — ✅ BUILT (HS w=8, HS-input only)

Live: `layers/flood/fetch_flood.py` queried FEMA per unique listing point (cached in
`flood_cache.json`), and **73 of 3,551 (2.1%)** came back high-risk (63 AE, 10 A). Baked
into `listings.js` as a 1/0/None flag; HS penalises a high-risk zone to 0 on that factor,
minimal scores 1, unknown drops out. Not a displayed column — appears in the HS breakdown
only, as asked. Below is the original reasoning.

### original spike notes

**Source:** FEMA National Flood Hazard Layer (public ArcGIS). Probed it live against a
listing's lat/lon and it returns the zone cleanly — `X` = minimal, `AE`/`A` = the 1%
"100-year" floodplain, `VE` = coastal. No key, cloud-safe.

**As an HS factor:** `AE`/`A`/`VE` = a real penalty — it's mandatory flood insurance
(often thousands a year) plus the risk itself. `X` = neutral. Unknown drops out.

⚠️ **Caveats:** FEMA is mid-remap in parts of NJ, so a zone can change. And a parcel can
be *partly* in a zone — 93 Gaywood is ~1% in an AE zone — so "touches AE" and "the house
sits in AE" are different; the point-in-polygon test answers the second, which is the one
that matters for the structure.

---

## 3. Crime — wanted by every serious buyer, and the trickiest to do honestly

**Source:** NJ UCR / FBI Crime Data Explorer, municipality level, per-capita (raw counts
would just rank big towns).

**As an HS factor:** lower rate = higher score, town-level.

⚠️ **This one needs the most care, and the spike's real job is to flag it:**
- **It probably double-counts.** Crime correlates hard with income, and income correlates
  with our tier (r≈+0.5) and price (w=30). **Measure crime vs tier/price before assigning
  any weight** — if it comes back r≈+0.8, it's the tier wearing a costume and should be
  dropped, exactly as we'd have dropped the ACS education layer.
- **The data is noisy and bias-prone** — reporting rates differ by department, and crime
  statistics can encode enforcement patterns as much as safety. Keep the weight modest and
  never surface it as a standalone "safety score", which is why the ask (HS-input-only, not
  displayed) is the right call.
- **Town-level hides everything within a town** — the same limit as schools.

---

## 4. Airport / highway / rail noise — the most work, the most permanent

**Sources, three of them:** Newark (EWR) DNL noise contours (Port Authority), highway
centerlines (NJDOT GIS), rail centerlines (the layer we referenced for 63 Lyons). Compute
distance-to-nearest for each off the listing's lat/lon.

**As an HS factor:** a penalty that grows the closer a house sits to a highway, an active
rail line, or inside an airport noise contour. Many of these towns sit under EWR approach
paths, so this is not a fringe case here.

**Why it's worth the effort:** noise is **permanent and unpriceable-away** — you can
renovate a kitchen, you cannot move the house off the flight path. It's the disamenity a
buyer most regrets missing, and the one currently hiding *inside* the comp band (a
track-adjacent house and a quiet-street one look identical to us today).

⚠️ **Caveat:** three GIS joins is real work, and "near a highway" needs a sensible
distance curve (80m is grim, 400m is fine). Biggest build of the four.

---

## The display split, concretely

| factor | feeds HS | shown on pages |
|---|:--:|:--:|
| town appreciation | maybe (small weight — see §1) | **yes — an average per town** |
| flood zone | yes | no (breakdown only) |
| crime | yes, *if* it survives the correlation check | no (breakdown only) |
| noise | yes | no (breakdown only) |

"HS-only" doesn't mean hidden — all three still appear when you click a score open, the
same as every other factor. It means no standalone column or metric of their own.

---

## Open questions

1. **Does town appreciation feed HS, or only display?** You said "the average shows on the
   pages" — but is it *also* a scoring factor? Given r=+0.61 with price, if yes it's a
   small weight (~4–5); if display-only, HS is untouched and it's purely colour. I lean
   **display + small weight**, but it's your call.
2. **Weights.** Rough first cut, all inside the existing weighted mean: flood **8**, noise
   **6**, crime **5** *if it survives*, appreciation **4**. Total model weight would rise
   from 138 to ~160, which reshuffles nothing — every factor is already relative.
3. **Crime: build it or not?** It's the one I'd want a go/no-go on after the correlation
   check, not before. If it's a price proxy, dropping it is the honest move.
4. **Order.** Appreciation is done-tomorrow (we own the data). Flood is a day (probed,
   works). Crime is a source + a correlation gate. Noise is the multi-GIS project. I'd
   ship in exactly that order.

---

## The one caution worth keeping

Three of these four are **town-level** (appreciation, crime, and — until we add noise —
much of location). Piling town-level factors into HS quietly makes it a *town* ranking
wearing a house's clothes, which is what the tier factor already is. Flood and noise are
the only two that vary house-to-house. Worth weighting the per-house factors a little
heavier than their town-level cousins, so HS keeps discriminating *within* a town and
doesn't collapse into "nice town = high score".
