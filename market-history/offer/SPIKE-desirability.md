# SPIKE — "Where in town": sold vs. for sale, and make it load fast

**Status:** note only. Nothing built.

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

Nothing on the left is better than what's on the right. Two are worse: the artifact
counts any school as a school regardless of quality, and it knows nothing of Wawa,
Trader Joe's, Seabra or commute times, all of which sit in `layers/` already — which
is most of what a real "amenities" score should be made of.

**Delete rather than port:** the whole "Checks" tab, and the per-town config behind
it (which highway crosses town, which direction each neighbor lies, which landmarks
to find). That's ~40 lines of hand-written config per town, and it exists to prove
the artifact wasn't making up geography — an artifact problem, not ours. It's also
the single thing that makes covering all our towns impractical. Same for the
browser-side caching and the save/load data file: unnecessary once the data is local.

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

## Open question

Cross-town comparison is currently refused — each town is ranked only against itself.
With our data it needn't be. That would make `map.html` "pick the town" and this page
"pick the street," which is a cleaner split than we have now.
