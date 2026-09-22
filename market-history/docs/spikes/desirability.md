# SPIKE — "Where in town": sold vs. for sale, and make it load fast

**Status: BUILT 2026-09-22.** Most of this note is now shipped, not proposed — see
"What got built" below. The **Decided** markers still stand and aren't meant to be
re-litigated; the rest is kept because it records *why* the thing is shaped this way.

> Keep this short and plain. It's a working note, not a design doc.
> Internal tool, just for us. It looks different from the other pages — fine,
> not worth fixing.

## What it is

`desirability.html` — a map that scores small patches *within* one town on price,
road noise, flood risk and what's nearby. Copied in from a one-off artifact
2026-09-22, linked from `index.html` as "Where in town."

It takes about a minute to open a town, and its sale list is 42 hand-pasted Colonia
addresses with no connection to our data.

---

## What got built

| | |
|---|---|
| `layers/geo/fetch_address_coords.py` | 3,409 addresses geocoded, 97% matched, match quality stored |
| `layers/osm/fetch_osm_context.py` | roads (incl. rail), parks, land use, schools baked per town |
| `layers/housing/fetch_assisted.py` | 925 NJ HUD assisted-housing properties, 91,104 units |
| `offer/build_desirability.py` | emits `desirability.js` — 2,112 sold, 190 for sale, 3.3 MB |
| `offer/desirability.html` | rewritten to draw the baked file and nothing else |
| `offer/serve.py`, `favourites.js`, `favourites.html` | favourites: star locally, commit, read anywhere |

Cold load went from about a minute to under four seconds, and the page now makes exactly
one network request — its own data file.

**Still open:** the shortlist pins (the favourites file now exists, so the input is
there); rail in the road factor; and whether a "fronts a through road" flag is worth
having at all — see the measurement below.

### What the road measurement actually said

Built `offer/road_effect.py` to test the assumption rather than code it in. Pooled across
the three towns, houses within 30 m of a through road sell **-1.7%** against a control
120-600 m away, and **+0.9%** on $/sqft. Essentially nothing: the raw gap is mostly house
size, not location.

Individual roads are a different story, and they are all over the place — Morris Ave
(NJ 124) -61%, Newark-Pompton Turnpike -37%, Ratzer Rd -23%, while Pines Lake Drive West
is **+86%** because it is lakefront. So a blanket "on a main road" penalty is not
supported by our own data. *Which* road is what matters, which argues for showing the
road and its measured effect rather than adding a factor.

## What the numbers actually mean

The town is chopped into hexagons — about 140 m across in Colonia and Springfield,
225 m in Wayne (bigger town, fewer cells). Each one gets five scores from 0 to 100,
where **100 is always the good end**, and those five get blended into the single
number the colors show.

Cells sitting on top of a shopping centre, factory, golf course, cemetery, school
grounds or a large park aren't scored at all — they're drawn gray and left out of
the rankings, since nobody lives there.

### The five factors

**Housing value — 35% of the score.** What nearby houses sold for. Every sale within
2 km pulls on the cell, but pulls *much* harder when close: weight falls off with the
square of distance, so a sale 200 m away counts roughly 25× one a kilometre out.
Prices are averaged in logs, so it's a typical price rather than one mansion
dragging the block up. Where few sales are nearby the number gets pulled toward the
town's own median — deliberately, so an empty corner reads "average" instead of
inventing a figure from one sale. The cell popup tells you how many sales were within
800 m; under three and it's mostly leaning on the median.
*Soft spot:* this is raw price, **not adjusted for house size**, so a street of big
houses scores high for being big.

**Major-road exposure — 20%.** How much highway and traffic noise reaches you.
Measured off three tiers, with the worst one winning: highways and trunk roads hurt
fully within 80 m and fade to nothing by 450 m; primary arterials hurt within 25 m,
fading by 200 m, at 60% strength; secondary roads within 20 m, fading by 120 m, at
35%. So 100 means no significant road near you, 0 means you're essentially on one.
*Soft spot:* distance only. It can't tell a sunken, walled highway from an
at-grade one.

**Non-residential adjacency — 15%.** How far you are from commercial, retail or
industrial land. Touching it scores 0, and it climbs in a straight line to 100 once
you're 250 m clear. This is the "backs onto the strip mall" penalty.

**Flood — 15%.** Seven points are sampled across each cell and checked against FEMA's
maps. Entirely inside the 1%-a-year flood zone scores 0; entirely inside the milder
0.2% zone scores 55; fully outside any mapped zone scores 100. Partly in, partly out
lands in between. If FEMA doesn't answer, it falls back to distance from the nearest
stream — within 40 m scores 30, within 100 m scores 70 — and the popup labels it a
proxy so you know it's the weaker measure.

**Amenities — 15%.** Really just "is there a park and a school near you." Parks are
60% of it: full credit within 150 m, tapering to nothing by 1.2 km. Schools are the
other 40%: full credit within 300 m, tapering by 1.5 km. Private parks are ignored.
*Soft spot:* any school counts equally, good or bad, and nothing else counts at all —
no shops, no station, no groceries.

### The blended score

The five are combined at the weights above, and then — this is the part worth
knowing — the result is converted into a **rank within that town**. A composite of 90
means "better than 90% of the liveable cells in this town," not "90 out of 100 in
some absolute sense." The individual five are absolute; the headline number is a
ranking. It's also why the page refuses to compare colors across towns: a yellow cell
in Wayne and a yellow cell in Colonia both just mean "middling for here."

The words attached to scores: **Highest** 85+, **High** 70+, **Above average** 55+,
**Middle** 40+, **Below average** 20+, **Lowest** under 20. In the breakdowns,
individual factors read **Favorable** at 70+, **Moderate** at 40+, **Unfavorable**
below. The "helped by / held back by" sentence is mechanical — anything at 70+ is
listed as helping, anything under 40 as holding it back.

The weights are sliders you can drag, 0 to 50 each, and everything re-ranks live.

### Deliberately left out

Resident sentiment, crime, and school attendance zones — all set to zero weight. The
reasoning given: sentiment has no location-specific evidence behind it, crime is only
published town-wide, and attendance zones aren't reliably published for all three
towns. Worth revisiting the last one, since it's usually the thing people most want.

---

## The real problem

The artifact was written blind to this repo, so **it rebuilt four things we already
own** — and fetching them live from the internet is exactly why it's slow:

| it downloads every visit | we already have it, committed |
|---|---|
| Town boundaries, from the Census | `layers/geo/town_boundaries.geojson` — 75 towns, 68 KB |
| Flood zones, from FEMA | `layers/flood/flood_zones.geojson` — 8,118 zones |
| Schools, from OpenStreetMap (unrated) | `layers/schools/school_ratings.csv` — *with ratings* |
| Looks up every address, one at a time | see below |

Nothing on the left is better than what's on the right, and the schools are worse —
the artifact counts any school as a school regardless of quality.

**But be careful with the rest of `layers/`.** Most of it is **town-grain**: one value
per town. Commute to Manhattan, tax rate, appreciation, income, education — Colonia has
*one* number for each. Paint that on a within-town map and every hexagon gets the same
color, which tells you nothing about where in Colonia to buy. Those layers exist for
`map.html`, which compares towns, and they belong there.

Only layers with real **point or polygon geometry** work at this scale, because the
distance changes house to house:

- `layers/geo/town_boundaries.geojson` — the boundary itself
- `layers/flood/flood_zones.geojson` — 8,118 polygons, varies street to street
- `layers/schools/school_ratings.csv` — school locations *with* ratings
- `wawa.json`, `trader_joes.json`, `seabra.json` — geocoded store points

**Delete rather than port:** the whole "Checks" tab, and the per-town config behind
it (which highway crosses town, which direction each neighbor lies, which landmarks
to find). That's ~40 lines of hand-written config per town, and it exists to prove
the artifact wasn't making up geography — an artifact problem, not ours. It's also
the single thing that makes covering all our towns impractical. Same for the
browser-side caching and the save/load data file: unnecessary once the data is local.

## The work that touches only this page

Worth separating, because it's the cheapest real improvement here and it breaks nothing.

`build_share.py` is the only thing that reads the store and school layers, and it
collapses each one to a single number per town — measured from the **zip centroid**. So
"nearest Wawa: 1.2 mi" means 1.2 mi from the middle of 07067, the same answer for every
house in Colonia. Correct for `map.html`. Useless for a map of streets.

The page-local work is to measure from **each hexagon** instead:

- **Rebuild the amenities factor from real points** — per-hexagon distance to Wawa,
  Trader Joe's and Seabra, plus schools weighted by their actual rating rather than
  "any school counts." Nothing else in the repo computes per-hexagon distances, so no
  existing page changes.
- **Read flood zones from `flood_zones.geojson`** instead of calling FEMA live.
- **Read the boundary from `town_boundaries.geojson`** instead of the Census.

`map.html`, `market.html`, `sold.html`, `analyser.html`, `backtest.html`,
`build_share.py` and `aggregate.py` are all untouched. And none of it needs a network
fetch — the data is already committed, so the speed fix and the better amenity score
fall out of the same change.

The two things that *do* reach further: stopping `build_data.py` from dropping lat/lon
(additive, breaks nothing) and the `address_coords` file below.

## The ask: filter sold vs. for sale

**For sale is nearly free.** `listings.csv` already carries lat/lon — 96% of 6,993
rows, including 93 in Colonia, 93 in Springfield, 334 in Wayne. `build_data.py`
simply drops those two columns when it writes `listings.js`. Stop dropping them and
the for-sale layer has coordinates with no new work at all.

**Sold needs geocoding.** `sales.csv` has no coordinates and only ~7% of sold rows
can borrow one from a listing. So that's the one real task: geocode sold addresses
once, offline, and commit the result. Colonia alone has **185 single-family sales in
the last 12 months** against the 42 hardcoded today.

## Where the coordinates should live

Not as new columns on `sales.csv` filled during hydration. A **derived lookup file**,
joined in at build time — `layers/geo/address_coords.json`, next to `zip_centroids.json`,
with a `fetch_address_coords.py` modelled on `layers/flood/fetch_flood.py`.

Why that way:

- **The pattern already exists here.** `flood_cache.json` is keyed by rounded
  coordinates, checkpoints as it runs, and a re-run only fetches points it has never
  seen. This is the same thing with the key flipped to address. And the layers README
  already calls `geo/` "infrastructure, not an amenity" — it exists so other things
  can measure distance. That's precisely this.
- **A geocode isn't a scraped fact.** `sales.csv` carries `conflicts`, `_sources` and
  a full provenance record of what every source said about every field. A coordinate
  has no disagreement to resolve; it's derived. The layers contract already says
  `aggregate.py` stays purely scrape — leave it that way.
- **The repo is the DB, so churn costs.** `sales.csv` is rewritten every hydration.
  Two new columns across 50,555 rows means a large diff in a committed file every run.
  A lookup file changes only when a genuinely new address turns up.
- **It's address-grain, not sale-grain.** A house that sold in 2023 and again in 2026
  is two rows and one location. Key on the address, geocode once, and both rows get
  it — plus `listings.csv` for its missing 4%, plus whatever we build later.

Sizing, which argues for doing the three towns first and the rest whenever:

| | addresses |
|---|---|
| Unique in `sales.csv` | 47,877 |
| Already covered free by a listing's coordinates | 2,388 (5%) |
| Still needing a lookup | **45,489** |
| — of which, in the three map towns | **2,981** |

Seed it free from the 6,503 coordinates `listings.csv` already holds, then geocode
the ~3,000 the map actually needs. The full 45k is a Census batch job (10k per file,
free, no key) that can grind away later without blocking anything.

**Do not skip this:** store the match quality with every coordinate. The Census
geocoder returns rooftop matches, street interpolations, and — when it can't find an
address — something as coarse as a zip centroid. If those fallbacks land in the file
unmarked, every unmatched house in Colonia plots on the same spot and the map quietly
lies about a whole neighborhood. Keep the match type; treat anything below street
interpolation as no coordinate at all.

`build_data.py` then joins coordinates onto the rows it emits, the way
`build_share.py` joins layers in at share time. `aggregate.py` never learns this
exists.

## How far back the sales go: three years, time-adjusted

**Decided 2026-09-22.** Use the full three years and adjust older sales to today's
money, rather than windowing to the last 12 months.

The reason is coverage, not volume. Thin data is this map's core weakness — cells with
fewer than three sales within 800 m fall back to the town median and stop saying
anything. Three years roughly triples the density (Colonia: 185 sales → 529). A
12-month window preserves that weakness to avoid a problem that has a standard fix.

And it is genuinely standard. Fannie Mae has **required** time adjustments on
comparable sales since March 2025 — appraisers don't discard older comps, they adjust
them — and names home price indices as an acceptable basis. We already have the index:
`market.csv` and `share/by_town_month.csv` hold the zip-month medians. The academic
side reaches the same place from the other direction; spatiotemporal models exist
precisely because throwing away time wastes data the spatial side needs.

**One caution:** adjust with the **town-level** trend. Never derive the adjustment from
the same cells being scored, or the map starts explaining itself.

Sources: [Fannie Mae — Adjustments to Comparable Sales](https://selling-guide.fanniemae.com/sel/b4-1.3-09/adjustments-comparable-sales) ·
[Fannie Mae — Market Condition Adjustments](https://singlefamily.fanniemae.com/media/40241/display) ·
[Hedonic estimation with the spatiotemporal geostatistical model](https://link.springer.com/article/10.1007/s43071-023-00039-w) ·
[Putting time into space](https://ideas.repec.org/a/eee/regeco/v58y2016icp78-88.html)

## The one thing that would make it instantly better

**Put our own shortlist on it.**

Today you type one address and get the score for the hexagon it falls in. That's
backwards — we already know which houses we care about. Pin them all on the map at
once, each with its score and factor breakdown, and the page stops being "a pretty
gradient of a town" and starts answering *how does this house's location compare to
everything around it.*

One address at a time is a lookup. The shortlist on one map, ranked, is a decision
tool — and it's the cheapest item in this whole note, because the address-check code
already works.

**Two lists, and only one of them needs building.**

*Everything currently for sale in the town* is free — `listings.csv` already has the
coordinates, so it's a layer, not a project.

*Favourites* is the better list, and it is **already spiked and already decided**:
[`persistence.md`](persistence.md) covers starring a house on the laptop and seeing it
on the phone at a viewing, backed by a Cloudflare Worker over Workers KV behind a
random space-id, no login, JSON export in v1. Build against that decision — don't
invent a second mechanism here.

Two things to carry back to that spike rather than solve here:

- **Star from the `market.html` list, without opening the house.** The star belongs on
  the row.
- **A favourite keeps its history after it leaves the market.** This is the part with
  real value: a house you starred, then watched sell, tells you what the places you
  liked actually go for. That's the old house-hunt list→sold watchlist, and nothing in
  `offer/` does it today.

Worth noting what it would *not* have told us: 404 Elm's big risk is the rail line at
~780 ft, and the page scores roads but **not rail**. If we build this, rail belongs in
the road-exposure factor.

## One upgrade only our data makes possible

Because the value factor isn't size-adjusted, it partly measures how big the houses
are rather than how good the location is. We have sqft, and we have a comp engine.
Scoring on $/sqft — or better, on how much each sale beat what our own engine
predicted — isolates the location premium. That's the difference between a pretty map
and one worth arguing with.

## One judgment call

Colors should keep coming from **sold** prices only. An asking price is a hope, not a
fact; letting it move the map makes an overpriced street look good. For sale is a
layer you switch on to see what's available.

## Scope: stay at three towns

Decided 2026-09-22 — keep Colonia, Springfield and Wayne for now. Small scope while
the shape of this is still moving; widening it later is cheap once the page reads our
data, and there's no point paying for 63 towns' worth of coordinates to answer a
question we haven't settled yet.

The consequence to remember: Cranford isn't in it, so the houses we're actually
looking at right now mostly aren't either.

## `map.html` stays as it is

**Decided 2026-09-22.** They're separate thought bubbles for now. No merging this into
the town map, no reworking the town map around it. Consolidation is a real option later
— just not a question being answered yet.

Cross-town comparison stays refused too: each town is ranked only against itself. Our
data would allow otherwise, but it's parked while the scope stays at three towns.
