#!/usr/bin/env python3
"""Does fronting a through road actually cost you money? Measure it, don't assume it.

    python3 offer/road_effect.py
    python3 offer/road_effect.py --towns Colonia --min-sales 4

The desirability map penalises houses near big roads on a distance curve borrowed from
noise modelling. That curve was written for highways. The thing we actually care about
-- a house ON a busy local road like New Dover Rd -- is a different problem: 0-30 m,
your own driveway, not a 450 m noise cone. Before building a factor for it, check
whether the market agrees it matters, using our own sold prices.

METHOD
  ON       a sale within 30 m of a through road's centreline -- it fronts it
  BUFFER   30-120 m -- the next street over; excluded from both sides, because it is
           neither clearly on the road nor clearly away from it
  CONTROL  120-600 m from every through road -- same neighbourhood, quiet street

  Prices are time-adjusted to the latest month first (same town-level trend the map
  uses), so a 2023 sale and a 2026 sale are comparable. We then compare medians.

  A "through road" is motorway/trunk/primary/secondary/tertiary, or anything carrying a
  route number (CR / NJ / US). The route number matters: a county route is a through
  road by definition -- a county maintains it *because* it carries traffic between
  towns -- which does not depend on a volunteer's choice of OSM class.

WHAT THIS IS NOT: a controlled experiment. Houses on main roads may differ from houses
off them in ways we are not measuring (age, lot, condition). The $/sqft column is a
partial check on the most obvious confound, size, and only 52% of our sales carry sqft.
Read the n column before believing any single street.
"""
import argparse
import csv
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir)
sys.path.insert(0, HERE)
from build_desirability import price_index, key                     # noqa: E402

SALES = os.path.join(ROOT, "sales.csv")
COORDS = os.path.join(ROOT, "layers", "geo", "address_coords.json")
OSM = os.path.join(ROOT, "layers", "osm")
TOWNS = ["Colonia", "Springfield", "Wayne"]
THROUGH = {"motorway", "trunk", "primary", "secondary", "tertiary"}
ON_M, BUF_M, CONTROL_M = 30, 120, 600


def to_m(lon, lat, lat0):
    """Local equirectangular metres. Fine over a few km."""
    return (lon * 111320 * math.cos(math.radians(lat0)), lat * 110540)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def road_name(props):
    n = props.get("name")
    r = props.get("ref")
    if n and r:
        return f"{n} ({r})"
    return n or r or None


def load_roads(town, lat0):
    path = os.path.join(OSM, f"{town.lower().replace(' ', '-')}.geojson")
    if not os.path.exists(path):
        sys.exit(f"no baked OSM for {town} -- run layers/osm/fetch_osm_context.py")
    roads = []
    for f in json.load(open(path))["features"]:
        p = f["properties"]
        hw = (p.get("highway") or "").replace("_link", "")
        ref = p.get("ref") or ""
        is_route = any(ref.startswith(x) for x in ("CR ", "NJ ", "US ", "I "))
        if hw not in THROUGH and not is_route:
            continue
        if f["geometry"]["type"] != "LineString":
            continue
        pts = [to_m(x, y, lat0) for x, y in f["geometry"]["coordinates"]]
        roads.append({"name": road_name(p) or f"unnamed {hw}", "cls": hw or "route",
                      "ref": ref, "pts": pts})
    return roads


def nearest(pt, roads):
    best, who = float("inf"), None
    for r in roads:
        for i in range(len(r["pts"]) - 1):
            (ax, ay), (bx, by) = r["pts"][i], r["pts"][i + 1]
            if min(ax, bx) - best > pt[0] or max(ax, bx) + best < pt[0]:
                continue
            d = seg_dist(pt[0], pt[1], ax, ay, bx, by)
            if d < best:
                best, who = d, r
    return best, who


def pct(a, b):
    return (a - b) / b * 100 if b else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--towns", nargs="*", default=TOWNS)
    ap.add_argument("--min-sales", type=int, default=5,
                    help="per-road breakdown needs at least this many ON sales")
    args = ap.parse_args()

    coords = json.load(open(COORDS))
    index = price_index(args.towns)
    pooled = {"on": [], "control": []}

    for town in args.towns:
        rows = []
        with open(SALES, newline="") as f:
            for r in csv.DictReader(f):
                if r["town"] != town or r.get("property_type") != "Single Family":
                    continue
                c = coords.get(key(r["address"], town))
                if not c or not r.get("sold_price") or not r.get("sold_date"):
                    continue
                try:
                    price = float(r["sold_price"])
                except ValueError:
                    continue
                f_ = index.get(town, {}).get(r["sold_date"][:7], 1.0)
                sqft = None
                try:
                    sqft = int(float(r["sqft"])) if r.get("sqft") else None
                except ValueError:
                    pass
                rows.append({"addr": r["address"], "price": price * f_,
                             "sqft": sqft, "lat": c["lat"], "lon": c["lon"]})
        if not rows:
            continue

        lat0 = statistics.mean(r["lat"] for r in rows)
        roads = load_roads(town, lat0)
        on, control, by_road = [], [], {}
        for r in rows:
            d, who = nearest(to_m(r["lon"], r["lat"], lat0), roads)
            r["d"] = d
            if d <= ON_M:
                on.append(r)
                by_road.setdefault(who["name"], []).append(r)
            elif d > BUF_M and d <= CONTROL_M:
                control.append(r)
        pooled["on"] += on
        pooled["control"] += control

        mo, mc = statistics.median(x["price"] for x in on), statistics.median(x["price"] for x in control)
        print(f"\n=== {town} — {len(rows)} single-family sales, {len(roads)} through-road ways")
        print(f"  ON a through road (<={ON_M} m): {len(on):>4}  median {mo:>10,.0f}")
        print(f"  CONTROL ({BUF_M}-{CONTROL_M} m):      {len(control):>4}  median {mc:>10,.0f}")
        print(f"  gap: {pct(mo, mc):+.1f}%")
        so = [x["price"] / x["sqft"] for x in on if x["sqft"]]
        sc = [x["price"] / x["sqft"] for x in control if x["sqft"]]
        if len(so) >= 8 and len(sc) >= 8:
            print(f"  $/sqft where known ({len(so)} vs {len(sc)}): "
                  f"{statistics.median(so):,.0f} vs {statistics.median(sc):,.0f}  "
                  f"({pct(statistics.median(so), statistics.median(sc)):+.1f}%)")

        worst = sorted(((n, v) for n, v in by_road.items() if len(v) >= args.min_sales),
                       key=lambda kv: statistics.median(x["price"] for x in kv[1]))
        if worst:
            print(f"  by road (>= {args.min_sales} sales on it):")
            for n, v in worst:
                med = statistics.median(x["price"] for x in v)
                print(f"     {n[:42]:<44} n={len(v):>3}  median {med:>10,.0f}  "
                      f"{pct(med, mc):+6.1f}% vs control")

    if pooled["on"] and pooled["control"]:
        mo = statistics.median(x["price"] for x in pooled["on"])
        mc = statistics.median(x["price"] for x in pooled["control"])
        print(f"\n=== ALL TOWNS POOLED")
        print(f"  ON {len(pooled['on'])} median {mo:,.0f}   "
              f"CONTROL {len(pooled['control'])} median {mc:,.0f}   gap {pct(mo, mc):+.1f}%")
        so = [x["price"] / x["sqft"] for x in pooled["on"] if x["sqft"]]
        sc = [x["price"] / x["sqft"] for x in pooled["control"] if x["sqft"]]
        if so and sc:
            print(f"  $/sqft ({len(so)} vs {len(sc)}): {statistics.median(so):,.0f} vs "
                  f"{statistics.median(sc):,.0f}  "
                  f"({pct(statistics.median(so), statistics.median(sc)):+.1f}%)")


if __name__ == "__main__":
    main()
