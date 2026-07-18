# SPIKE — the Map page (`map.html`)

**Status:** proposal, **v2 after a CTO review**. Nothing built.

**What the review changed:** the headline feature ("what town am I in") runs on a
geolocation lookup, and our geo dataset is 63 *points* that can't answer it — 5 towns
collapse onto 2 shared points and centroids sit ~1 mi off-center. Town **boundary
polygons** are therefore the *foundation* of this page, not the step-6 "upgrade" v1
proposed. They are fetchable (Census TIGERweb, ~18 KB/town raw → a couple hundred KB
simplified for all 63), so this is a real dependency, not a blocker. The build order and
the "where am I" design below are rewritten around that.

**Ask:** a map of our NJ towns, framed to the four corners of the set. Flip between
overlays — crime, flood, income, schools, appreciation, the lot. Pick one town and the
map fits to it. A **"where am I"** button so that, riding shotgun while your girlfriend
drives you around towns, you can glance down and see what's going on where you are.

That last sentence is the real spec. This is a **phone-in-a-car** page first, a desktop
page second.

---

## The stack, and the two rules it breaks

**Leaflet + OpenStreetMap tiles.** Leaflet is the small, standard map library; OSM tiles
are free. Together they're the obvious choice.

But every page so far has been **self-contained and offline-capable**. This one can't be:

1. **Tiles come from a server.** The map is external requests by nature. Fine on the
   deployed `https` site; it just means `map.html` isn't a double-click-and-works file
   the way the others are. Leaflet itself we'd **vendor (inline)** so at least the code
   is self-contained; the tiles are the only unavoidable network dependency.
2. **"Where am I" needs `https`.** Browser geolocation is **blocked on `file://`** — so
   the car use case *only works on the deployed URL* (`ssd42.github.io/...`), never a
   local file. That's not a limitation to fix; it's the reason this page lives on the
   deployed site and you open it from a bookmark in the car.

---

## The foundation: boundaries, because points can't tell you where you are

The headline spec is the passenger-seat *"what town am I in."* That is a
`point-in-polygon` question, and **we have no polygons** — 63 zip **centroids** (points),
and `nj_municipalities.json` is scraper config (town/county/zip lists, no geometry).

Nearest-centroid — the shortcut v1 reached for — **does not work**, measured:

- **Median gap between neighboring town centroids is 2.0 mi**, and a centroid sits a
  mile-plus from the town edge. Driving Cranford → Westfield, nearest-centroid flips to
  Westfield while you're still in Cranford, and says so with a confident card.
- **Five towns collapse onto two shared points.** `07006` is Caldwell *and* North
  Caldwell *and* West Caldwell; `07960` is Morristown *and* Morris Township. Nearest-
  centroid there isn't wrong, it's **undefined** — the same point can never distinguish
  Morristown from Morris Township.

So a map that names the wrong town — the exact "pretty lie" the closing section warns
about — is what nearest-centroid ships. **The fix is boundaries, and it is the same fix
for three separate problems at once:**

1. `point-in-polygon` gives the **correct** town for "where am I".
2. It fills a real **choropleth** instead of ambiguous dots.
3. It resolves the **bubble-placement** mess below.

**Boundaries are a real dependency, and they're gettable.** Probed Census TIGERweb: one
NJ municipality returns an 18 KB polygon (475 vertices); simplified hard (we don't need
coastline detail), all 63 towns is a couple hundred KB baked as GeoJSON. NJGIN is the
NJ-official alternative. **This is step 1, not step 6.**

### Why even "bubbles at centroids" is broken on day zero

The v1 fallback — a circle per town at its centroid — fails for the same reason before
any boundary work:

- **Shared-zip towns render as coincident bubbles.** The three Caldwells stack on one
  pixel; you cannot click "West Caldwell", it's buried under two other circles.
- **Multi-zip towns have no defined location.** Edison has three zips
  (`08820 / 08817 / 08837`), Montclair two — *which* centroid is the bubble? Undefined.

Even a bubble map needs one non-colliding, defined point per town, which today it lacks
for 7 of 63 towns. Bubbles-without-boundaries is not "the cheap version that ships first";
it's a broken version. Do boundaries first and the bubble question disappears.

## What can be a point vs an area

| data | how it maps | have it? |
|---|---|---|
| income, schools, appreciation, tier, commute, median price | **area** (town) → choropleth, once boundaries land | ✅ all keyed on town |
| crime | area (town) | ⏳ not built (see HS spike) |
| **flood zones** | **tile overlay, straight from FEMA** | ✅ |
| for-sale listings | **points** (price / HS / flood per house) | ✅ lat/lon on ~100% |
| Seabra / Trader Joe's / Wawa | **points** | ✅ geocoded |
| **sold houses** | **can't** — no coordinates | ❌ (deed records) |

Sold houses being unmappable is the one real gap, and it's the same missing-coordinates
wall as everywhere else. The `sold.html` search already covers that need.

---

## The overlays, each with the caveat it must carry

Every one of these already has a hard-won caveat elsewhere in the project. The map must
carry them, not launder them into authoritative-looking colour.

- **Income** — ACS, wide margins of error (±$15–25k). A $5k gap between two towns isn't
  real. *Area statistic, never a quality ranking.*
- **Schools** — DOE district decile, a **district proxy on a zip**; two houses on a street
  can feed different schools.
- **Appreciation** — measured for 20 towns, **borrowed regional for 43** (mark them).
- **Crime** — if built: noisy, bias-prone, and probably a wealth proxy. *Never a
  standalone "safety" colour.*
- **Flood** — FEMA is mid-remap; a zone is a point-in-polygon fact, not a guarantee.
- **Prices / HS** — a town *average* hides the spread that the per-house pages exist to show.

---

## The interactions

- **Fit to all** on load — bounds to the four corners of the 63 towns (trivial: we have
  the extent already, N 41.01 / S 40.51 / W −74.78 / E −74.13).
- **Pick a town** → the map flies to it and (choropleth version) highlights its shape.
- **Where am I** → geolocation, drop a "you are here" dot, and show a card for **the town
  the point falls inside** — `point-in-polygon` against the baked boundaries, NOT nearest
  centroid. Income, schools, appreciation, flood, tier at a glance. This is the passenger-
  seat payoff, and it is only correct with boundaries.
  ⚠️ **Geolocation is a permission and a signal, both of which fail in a car.** It can be
  denied, revoked, or lost between towns. Needs an explicit fallback: last-known point, or
  a manual "I'm near ___" pick. Not a button that silently does nothing.
- **Tap a bubble / town** → the same card. Tap a listing point → its price + HS, with a
  link into the analyser.
- **Overlay switcher** — big touch targets, one active overlay at a time (two colour
  scales at once is unreadable).

---

## Why it has to be built mobile-first, not adapted

It's used **in a moving car, one-handed, on cellular, in sunlight.** That dictates:
big tap targets, a legend that's readable at a glance, high-contrast colour ramps,
a payload that loads on a phone signal, and a re-centre button that's always reachable
by thumb. A desktop map squeezed onto a phone would fail exactly when you need it.

---

## The honest hard parts

- **Boundaries** are a real sourcing + simplify + payload job — but the foundation, not a
  sidestep (see above). ~200 KB simplified. There is no correct-enough version without them.
- **Colour done right is most of the work.** Six overlays each need a legible, colour-blind-
  safe ramp with sensible breaks, and the caveats have to ride *with* the colour so a wide-
  margin income map doesn't read as gospel. (This is exactly what the `dataviz` skill is
  for — I'd use it.)
- **Live listings rot ~2%/day** — the same staleness stamp as the market page applies.
- **Geolocation accuracy** in a car is ~10–50 m and lags; near a town line the point may
  fall in the neighbour. With real polygons that's an honest edge case; without them it's
  the whole feature broken (see The foundation).

---

## Build order (reordered — boundaries first)

1. **Boundaries.** Fetch NJ municipal polygons (TIGERweb/NJGIN), simplify, bake as
   GeoJSON. The prerequisite for the correct town lookup AND the choropleth AND
   non-colliding towns. ~200 KB. Everything else depends on this.
2. **Leaflet + OSM, fit to the 63 towns, one choropleth overlay** (appreciation — we own
   it). Proves the stack end to end, with real filled towns from step 1.
3. **The overlay switcher** across the town metrics we already have (income, schools,
   appreciation, tier, commute, price).
4. **"Where am I" + point-in-polygon town card + geolocation fallback.** The car feature,
   correct because of step 1. Needs the deployed https site.
5. **Listing points — from a LEAN map payload, clustered.** Not `listings.js` (4.0 MB, and
   most of it — `tx`, `img`, description — is dead weight on a dot). Ship a stripped
   points file and cluster; 4 MB over cellular in a car is the actual failure mode.
6. **FEMA flood tile overlay** — real polygons straight from FEMA (probed: the MapServer
   returns 200), no boundaries of ours needed.
7. **Crime** — only if the HS-spike correlation gate clears it.

Steps 1–4 are the real, correct page. Skipping step 1 is what makes it a liability.

## Freshness: three clocks on one screen, one honest "as of"

This page mixes three data lifecycles the first draft never reconciled:

| layer | freshness |
|---|---|
| town metrics (`data.js`), boundaries | baked, effectively stale-proof |
| listing points | **rot ~2%/day** — same as the market page |
| OSM + FEMA **tiles** | **live external** — can 404, rate-limit, or change mid-session |

A flood overlay (live FEMA) speckled with listing pins (2 days old) over an income
choropleth (ACS 2020–2024) is **three different "nows" read as one picture.** The page
needs a single "data as of" surface that names all three, and a **loud** failure when a
tile server is down — not a blank overlay on a map that still looks authoritative.

## Open questions

1. ~~Bubbles first, or hold for the choropleth?~~ **Answered by the review: boundaries
   first.** Bubbles-at-centroids is broken for 7 towns and can't locate you; the "cheap
   v1" was a false economy. Boundaries are ~200 KB and fix three problems at once.
2. **Vendor Leaflet, or CDN it?** Vendor (inline) keeps the code self-contained and works
   offline except for tiles; CDN is lighter to maintain. I lean vendor, matching the rest.
3. **One page or a tab on an existing one?** New page — it's a different mode (browse-by-
   place vs. search/score), and it carries a map library the others shouldn't.
4. **Does the map need the sold data at all?** It can't plot sold *points*, but a town's
   colour could come from sold medians. Probably yes for the price overlay.

---

## The thing to hold onto

This page turns every town-level number we've been careful to caveat into **colour**, and
colour is persuasive in a way a flagged table isn't. The discipline that's kept this
project honest — say how much you know, and how old it is — is *harder* to maintain on a
map and *more* important. The legend and the caveat aren't decoration here; they're the
difference between a tool and a pretty lie you'll make a six-figure decision on from the
passenger seat.
