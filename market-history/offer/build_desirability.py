#!/usr/bin/env python3
"""Emit offer/desirability.js -- everything the "Where in town" map draws.

    python3 offer/build_desirability.py
    python3 offer/build_desirability.py --towns Colonia

The map used to fetch its own boundaries (Census), flood zones (FEMA) and sale
locations (geocoder, one address at a time) from the open internet on every visit,
which is why opening a town took about a minute. All of it is already in this repo, so
this script bakes it into one file and the page just draws what it is handed -- the
same arrangement as data.js / sold.js / listings.js.

WHAT GOES IN, AND WHY

sold -- SINGLE-FAMILY ONLY, three years, time-adjusted.
  Single-family because condos stack. 445 Morris Ave in Springfield is 24 sales at one
  coordinate and 1360 Hamburg Tpke in Wayne is 13; the map weights nearby sales by
  1/distance^2, so a stack like that would dominate every cell around it and the colors
  would be measuring "there is a condo building here", not what a house is worth.

  Three years rather than twelve months because thin coverage is this map's real
  weakness -- a cell with fewer than ~3 sales within 800 m falls back to the town median
  and stops saying anything. Three years roughly triples the density.

  Time-adjusted because a 2023 price and a 2026 price are not the same money, and
  mixing them makes the map measure *when* as much as *where*. Older sales are carried
  forward to the latest month on the town's own median-price trend, which is what an
  appraiser does with an older comp (Fannie Mae has required exactly this since March
  2025, and names price indices as an acceptable basis). The trend is deliberately
  TOWN-level: deriving it from the same neighborhoods being scored would let the map
  explain itself.

forSale -- what is listed now, all property types, NOT time-adjusted and NOT fed into
  the colors. An asking price is a hope; letting it move the map would make an
  over-priced street look good. It is a layer you switch on to see what is available.
  These come free -- listings.csv already carries lat/lon from the scrape.

  `status == "active"` in listings.csv is NOT "you can buy it" -- it covers FOR_SALE,
  PENDING and CONTINGENT alike, and in these three towns that is 198 / 81 / 18. A third
  of "active" already has an accepted offer. The mls_status rides along on every row so
  the page can do what market.html does: show genuinely-available by default, grey the
  rest, never mix them silently.

frontage -- computed per HOUSE, not per cell. A 140 m hexagon can only say "this
  neighbourhood has a through road in it"; whether a particular house fronts that road is
  a different question, and we have exact coordinates for every sold and listed house, so
  we answer it directly. Short distance bands, unlike the cell's road factor: a highway
  carries 450 m because of noise, but a local through road hurts because you back out of
  your driveway into it, and that stops mattering within a house or two.

boundary / flood / stores / assisted -- straight from layers/. Nothing is fetched at run
  time. `assisted` is HUD's government-assisted housing (see layers/housing/): shown as a
  map layer, NOT scored. It is there so you can see what is near a house, not so the page
  can rank neighbourhoods by who lives in them.

NOT INCLUDED, and worth knowing why:
  - layers/schools/school_ratings.csv is ZIP-grain district deciles with no school
    coordinates, so it cannot vary within a town. It says nothing about which street to
    buy on. School POSITIONS still have to come from OSM, as they do today.
  - transit, tax, appreciation, income, education are all town-grain for the same
    reason. They belong to map.html, which compares towns.
"""
import argparse
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir)
SALES = os.path.join(ROOT, "sales.csv")
LISTINGS = os.path.join(ROOT, "listings.csv")
COORDS = os.path.join(ROOT, "layers", "geo", "address_coords.json")
BOUNDARIES = os.path.join(ROOT, "layers", "geo", "town_boundaries.geojson")
FLOOD = os.path.join(ROOT, "layers", "flood", "flood_zones.geojson")
ASSISTED = os.path.join(ROOT, "layers", "housing", "assisted.geojson")
BY_TOWN_MONTH = os.path.join(ROOT, "share", "by_town_month.csv")
OSM = os.path.join(ROOT, "layers", "osm")
STORES = {
    "wawa": os.path.join(ROOT, "layers", "wawa", "wawa.json"),
    "tj": os.path.join(ROOT, "layers", "trader_joes", "trader_joes.json"),
    "seabra": os.path.join(ROOT, "layers", "seabra", "seabra.json"),
}
OUT_DIR = os.path.join(HERE, "desirability")     # one file per town, fetched on demand
OUT_INDEX = os.path.join(HERE, "desirability-index.js")


def slug(town):
    return town.lower().replace(" ", "-")


def area_km2(geom):
    """Shoelace on a local flat projection. Only used to pick a cell size, so approximate
    is fine -- Wayne is five times Colonia and no rounding changes that."""
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])
    lats = [c[1] for p in polys for ring in p for c in ring]
    k = math.cos(math.radians(sum(lats) / len(lats)))
    total = 0.0
    for p in polys:
        ring, acc = p[0], 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0] * 111.32 * k, ring[i][1] * 110.54
            x2, y2 = ring[i + 1][0] * 111.32 * k, ring[i + 1][1] * 110.54
            acc += x1 * y2 - x2 * y1
        total += abs(acc) / 2
    return total

TOWNS = ["Colonia", "Springfield", "Wayne", "Westfield", "Cranford",
         "Scotch Plains", "Montclair", "Clark", "Basking Ridge", "Watchung",
         "Cedar Grove", "Fanwood", "Garwood", "Gillette", "Verona",
         "West Orange"]
SINGLE_FAMILY = "Single Family"
SMOOTH = 5              # months in the centred rolling median for the price trend
CLAMP = (0.70, 1.60)    # a thin month must not invent a 2x adjustment
BUFFER_DEG = 0.02       # ~2 km of slack when clipping layers to a town


def key(address, town):
    return f"{' '.join(address.split()).lower()}|{town.strip().lower()}"


def load_coords():
    if not os.path.exists(COORDS):
        sys.exit("no layers/geo/address_coords.json -- run "
                 "layers/geo/fetch_address_coords.py first")
    return json.load(open(COORDS))


def price_index(towns):
    """town -> {month: factor} carrying that month's money forward to the latest month.

    Monthly medians in one small town are noisy, so the series is smoothed with a
    centred rolling median before any ratio is taken.
    """
    series = defaultdict(dict)
    with open(BY_TOWN_MONTH, newline="") as f:
        for r in csv.DictReader(f):
            if r["town"] not in towns or not r.get("median_sold_price"):
                continue
            try:
                series[r["town"]][r["month"]] = float(r["median_sold_price"])
            except ValueError:
                pass

    index = {}
    for town, raw in series.items():
        months = sorted(raw)
        if len(months) < SMOOTH:
            print(f"  ! {town}: only {len(months)} months of trend, leaving prices as-is")
            index[town] = {}
            continue
        half, smoothed = SMOOTH // 2, {}
        for i, m in enumerate(months):
            window = [raw[x] for x in months[max(0, i - half): i + half + 1]]
            smoothed[m] = statistics.median(window)
        latest = smoothed[months[-1]]
        index[town] = {
            m: min(CLAMP[1], max(CLAMP[0], latest / v))
            for m, v in smoothed.items() if v > 0
        }
    return index


def bbox_of(geom):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)

    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def clip(features, box):
    """Features whose own bbox overlaps the town's. Cheap, and good enough --
    the page does the real point-in-polygon work."""
    w, s, e, n = box
    out = []
    for f in features:
        if not f.get("geometry"):
            continue
        fw, fs, fe, fn = bbox_of(f["geometry"])
        if fe >= w - BUFFER_DEG and fw <= e + BUFFER_DEG \
           and fn >= s - BUFFER_DEG and fs <= n + BUFFER_DEG:
            out.append(f)
    return out


# ---- road frontage, per house -------------------------------------------------------
# "On a busy road" is a fact about a HOUSE, not about a 140 m hexagon. The cell colour
# can only ever say "this neighbourhood has a through road in it"; whether YOUR house
# fronts it is a different question, and we have the exact coordinates to answer it.
#
# The tiers are separate from the cell's road factor on purpose. A highway hurts from
# 450 m away because of noise; a local through road hurts because you back out of your
# driveway into it, which stops mattering within a house or two. Short bands, not cones.
FRONTAGE = [                       # (osm classes, full penalty within m, gone by m, weight)
    (("motorway", "trunk"),  40, 400, 1.00),
    (("primary",),           25, 150, 0.80),
    (("secondary",),         20, 110, 0.55),
    (("tertiary",),          18,  80, 0.35),
    (("unclassified",),      15,  60, 0.20),
]
ROUTE_PREFIXES = ("CR ", "NJ ", "US ", "I ")


def seg_dist_m(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def road_index(osm_features, lat0):
    """Through roads as flat metre-space segments, each carrying its own penalty band."""
    k_lon = 111320 * math.cos(math.radians(lat0))
    out = []
    for f in osm_features:
        p = f["properties"]
        hw = (p.get("highway") or "").replace("_link", "")
        ref = p.get("ref") or ""
        tier = next((t for t in FRONTAGE if hw in t[0]), None)
        if tier is None and any(ref.startswith(x) for x in ROUTE_PREFIXES):
            tier = FRONTAGE[3]                 # a county route is a through road either way
        if tier is None or f["geometry"]["type"] != "LineString":
            continue
        _, full, zero, weight = tier
        name = p.get("name") or ref or f"unnamed {hw or 'road'}"
        if p.get("name") and ref:
            name = f"{p['name']} ({ref})"
        pts = [(x * k_lon, y * 110540) for x, y in f["geometry"]["coordinates"]]
        out.append({"full": full, "zero": zero, "w": weight, "name": name, "pts": pts})
    return out, k_lon


def frontage(lat, lon, roads, k_lon):
    """(score 0-100, road name, metres) for ONE house. 100 = no through road near it.

    Worst offender wins, the same rule the cell's road factor uses, so the two numbers
    move together instead of telling different stories."""
    px, py = lon * k_lon, lat * 110540
    worst, who, howfar = 0.0, None, None
    for r in roads:
        pts = r["pts"]
        # cheap reject: if every vertex is far away on one axis, skip the segment loop
        if min(abs(px - x) for x, _ in pts) > r["zero"] and \
           min(abs(py - y) for _, y in pts) > r["zero"]:
            continue
        best = min(seg_dist_m(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
                   for i in range(len(pts) - 1)) if len(pts) > 1 else float("inf")
        if best >= r["zero"]:
            continue
        hit = r["w"] * (1.0 if best <= r["full"]
                        else 1.0 - (best - r["full"]) / (r["zero"] - r["full"]))
        if hit > worst:
            worst, who, howfar = hit, r["name"], best
    return round(100 * (1 - worst)), who, (round(howfar) if howfar is not None else None)


def load_stores():
    out = []
    for kind, path in STORES.items():
        d = json.load(open(path))
        locs = next((v for v in d.values() if isinstance(v, list) and v
                     and isinstance(v[0], dict)), [])
        for s in locs:
            if s.get("lat") and s.get("lon") and s.get("status", "open") != "coming_soon":
                out.append([round(float(s["lat"]), 5), round(float(s["lon"]), 5), kind])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--towns", nargs="*", default=TOWNS)
    args = ap.parse_args()
    towns = list(args.towns)

    coords = load_coords()
    index_series = price_index(towns)
    stores = load_stores()

    bnds = {f["properties"]["town"]: f
            for f in json.load(open(BOUNDARIES))["features"]
            if f["properties"].get("town") in towns}
    flood_all = json.load(open(FLOOD))["features"]
    assisted_all = (json.load(open(ASSISTED))["features"]
                    if os.path.exists(ASSISTED) else [])

    latest_month = max((m for t in index_series.values() for m in t), default="")
    os.makedirs(OUT_DIR, exist_ok=True)
    index = {"generated": date.today().isoformat(), "asOf": latest_month, "towns": []}

    for town in towns:
        if town not in bnds:
            print(f"  ! no boundary for {town}, skipping")
            continue
        box = bbox_of(bnds[town]["geometry"])

        osm_path = os.path.join(OSM, f"{town.lower().replace(' ', '-')}.geojson")
        if not os.path.exists(osm_path):
            # Skip rather than ship a town with no roads: every road-related score would
            # read "nothing near you", which is worse than the town simply not being
            # offered yet. Run layers/osm/fetch_osm_context.py --towns "<name>".
            print(f"  ! {town}: no baked OSM context, skipping")
            continue
        osm = json.load(open(osm_path))["features"]

        lat0 = (box[1] + box[3]) / 2
        roads_idx, k_lon = road_index(osm, lat0)


        sold, missing, undated = [], 0, 0
        with open(SALES, newline="") as f:
            for r in csv.DictReader(f):
                if r["town"] != town or r.get("property_type") != SINGLE_FAMILY:
                    continue
                if not r.get("sold_price") or not r.get("sold_date"):
                    continue
                c = coords.get(key(r["address"], town))
                if not c:
                    missing += 1
                    continue
                try:
                    price = float(r["sold_price"])
                except ValueError:
                    continue
                month = r["sold_date"][:7]
                factor = index_series.get(town, {}).get(month)
                if factor is None:
                    undated += 1
                    factor = 1.0
                try:
                    sqft = int(float(r["sqft"])) if r.get("sqft") else None
                except ValueError:
                    sqft = None
                try:
                    beds = int(float(r["beds"])) if r.get("beds") else None
                except ValueError:
                    beds = None
                fs, fname, fdist = frontage(c["lat"], c["lon"], roads_idx, k_lon)
                sold.append([c["lat"], c["lon"], round(price * factor),
                             round(price), month, sqft, beds, fs, fname, fdist])

        for_sale = []
        with open(LISTINGS, newline="") as f:
            for r in csv.DictReader(f):
                if r["town"] != town or r["status"] != "active":
                    continue
                if not r.get("lat") or not r.get("lon"):
                    continue
                try:
                    price = float(r.get("last_list_price") or 0)
                except ValueError:
                    continue
                if not price:
                    continue
                for_sale.append([
                    round(float(r["lat"]), 6), round(float(r["lon"]), 6),
                    round(price), r["address"],
                    r.get("beds") or None, r.get("baths") or None,
                    r.get("sqft") or None, r.get("days_on_market") or None,
                    r.get("url") or None, r.get("mls_status") or "FOR_SALE",
                    r.get("zip") or None,      # needed to build a favourite's key
                    *frontage(float(r["lat"]), float(r["lon"]), roads_idx, k_lon),
                ])

        flood = clip(flood_all, box)
        # a 300-unit development just over the line still matters, so keep a wide margin
        assisted = [f for f in assisted_all
                    if box[0] - 0.03 <= f["geometry"]["coordinates"][0] <= box[2] + 0.03
                    and box[1] - 0.02 <= f["geometry"]["coordinates"][1] <= box[3] + 0.02]
        km2 = area_km2(bnds[town]["geometry"])
        # bigger township, bigger hexagon: a 140 m cell over Wayne is ~1,500 cells the
        # browser must score before it can draw anything
        payload = {
            "town": town, "cell": 0.13 if km2 > 30 else 0.08, "asOf": latest_month,
            "boundary": bnds[town]["geometry"],
            "sold": sold,
            "forSale": for_sale,
            "flood": {"type": "FeatureCollection", "features": flood},
            "osm": {"type": "FeatureCollection", "features": osm},
            "assisted": [[f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0],
                          f["properties"]["name"], f["properties"]["units"],
                          f["properties"]["low"], "/".join(f["properties"]["kinds"]),
                          f["properties"]["city"]] for f in assisted],
            "stores": [s for s in stores
                       if box[1] - 0.15 <= s[0] <= box[3] + 0.15
                       and box[0] - 0.2 <= s[1] <= box[2] + 0.2],
        }
        # ONE FILE PER TOWN. You look at one town at a time, so there is no reason to
        # ship the other fourteen: fifteen towns in one bundle is ~20 MB, paid on every
        # visit, to look at one of them.
        tpath = os.path.join(OUT_DIR, f"{slug(town)}.js")
        with open(tpath, "w") as fh:
            fh.write("// GENERATED by build_desirability.py -- do not edit.\n")
            fh.write("window.DESIRABILITY_TOWN = ")
            json.dump(payload, fh, separators=(",", ":"))
            fh.write(";\n")
        index["towns"].append({
            "name": town, "slug": slug(town), "km2": round(km2), "sold": len(sold),
            "forSale": sum(1 for x in for_sale if x[9] == "FOR_SALE"),
            "kb": round(os.path.getsize(tpath) / 1024)})
        fronted = sum(1 for x in sold if x[7] < 100)
        print(f"  {town}: {len(sold)} single-family sales "
              f"({missing} without a coordinate, {undated} without a trend month), "
              f"{sum(1 for x in for_sale if x[9] == 'FOR_SALE')} for sale "
              f"(+{sum(1 for x in for_sale if x[9] != 'FOR_SALE')} under contract), "
              f"{len(flood)} flood polygons, "
              f"{len(osm)} OSM features, {len(assisted)} assisted-housing sites, "
              f"{fronted} sales near a through road")

    with open(OUT_INDEX, "w") as fh:
        fh.write("// GENERATED by build_desirability.py -- do not edit.\n")
        fh.write("window.DESIRABILITY_INDEX = ")
        json.dump(index, fh, separators=(",", ":"))
        fh.write(";\n")
    if index["towns"]:
        big = max(index["towns"], key=lambda t: t["kb"])
        print(f"\n{len(index['towns'])} towns, "
              f"{sum(t['kb'] for t in index['towns'])/1024:.1f} MB total, "
              f"largest {big['kb']/1024:.1f} MB ({big['name']})")
    print(f"prices adjusted to {latest_month}")


if __name__ == "__main__":
    main()
