#!/usr/bin/env python3
"""Roads, land use, parks and schools per town, from OpenStreetMap. Committed.

    python3 layers/osm/fetch_osm_context.py                     # the three map towns
    python3 layers/osm/fetch_osm_context.py --towns Colonia

Writes layers/osm/<town>.geojson -- the only geometry the desirability map needs that
we do not already hold. Everything else it draws (boundaries, flood zones, sale
locations) is in the repo, so once this is committed the page makes NO network call at
all and opens instantly.

WHY BAKE IT rather than fetch in the browser: Overpass is a free, shared, volunteer
service. It queues under load, the page tried four mirrors in series with a 120-second
timeout each, and a slow first mirror meant sitting there. It is also the one dependency
that can be down when we want to look at a house. The geometry changes on the scale of
months; refetch when a road gets built.

GRAIN: this is NOT a layers/ "layer" in the town-grain sense -- it is per-town geometry,
the same kind of support infrastructure as layers/geo/. It ships no column to share/ and
build_share.py does not read it.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
BOUNDARIES = os.path.join(ROOT, "layers", "geo", "town_boundaries.geojson")

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
TOWNS = ["Colonia", "Springfield", "Wayne"]
PAD = 0.015          # ~1.5 km beyond the boundary: a highway just outside still matters

QUERY = """[out:json][timeout:180];
way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified)$"](%(bb)s);out geom;
(way["landuse"~"^(commercial|retail|industrial|cemetery)$"](%(bb)s);
 rel["landuse"~"^(commercial|retail|industrial)$"](%(bb)s);
 way["leisure"~"^(park|golf_course|nature_reserve|playground|pitch|recreation_ground)$"](%(bb)s);
 rel["leisure"~"^(park|golf_course|nature_reserve)$"](%(bb)s);
 way["amenity"~"^(school|university|college)$"](%(bb)s);
 node["amenity"="school"](%(bb)s);
 rel["amenity"~"^(school|university|college)$"](%(bb)s);
 way["railway"~"^(rail|light_rail)$"](%(bb)s);
 way["waterway"~"^(river|stream)$"](%(bb)s););out geom;"""

KEEP = ("highway", "landuse", "leisure", "amenity", "name", "ref", "access", "railway",
        "waterway", "service", "usage", "lanes", "maxspeed")

# WHY tertiary and unclassified are in the query:
#   New Dover Rd is the main road through Colonia and OSM does not call it primary or
#   secondary, so the first version of this file did not contain it at all and the map
#   scored houses on it as though nothing were there. The middle tiers are where a
#   town's real through-roads live. `lanes` and `maxspeed` come along because they are
#   evidence about a road that does not depend on a mapper's choice of class.


def bbox(geom, pad=PAD):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)

    walk(geom["coordinates"])
    return min(ys) - pad, min(xs) - pad, max(ys) + pad, max(xs) + pad


def overpass(query):
    last = None
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(
                ep, data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.load(r)
        except Exception as e:
            print(f"    {ep.split('/')[2]}: {e}", file=sys.stderr)
            last = e
            time.sleep(2)
    raise SystemExit(f"every Overpass mirror failed: {last}")


def to_features(data):
    """Overpass elements -> GeoJSON. Ways closed and tagged as an area become polygons;
    everything else stays a line or a point. Relations are kept as their outer ways,
    which is enough for a distance measurement."""
    AREA = ("landuse", "leisure", "amenity")
    out = []
    for el in data.get("elements", []):
        tags = {k: v for k, v in (el.get("tags") or {}).items() if k in KEEP}
        if not tags:
            continue
        if el["type"] == "node":
            geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way":
            c = [[p["lon"], p["lat"]] for p in el.get("geometry") or []]
            if len(c) < 2:
                continue
            closed = len(c) > 3 and c[0] == c[-1]
            geom = ({"type": "Polygon", "coordinates": [c]}
                    if closed and any(k in tags for k in AREA) and "highway" not in tags
                    else {"type": "LineString", "coordinates": c})
        else:                                   # relation
            rings = [[[p["lon"], p["lat"]] for p in m.get("geometry") or []]
                     for m in el.get("members", [])
                     if m.get("type") == "way" and m.get("role") != "inner"]
            rings = [r for r in rings if len(r) > 3 and r[0] == r[-1]]
            if not rings:
                continue
            geom = {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
        out.append({"type": "Feature", "geometry": geom, "properties": tags})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--towns", nargs="*", default=TOWNS)
    args = ap.parse_args()

    bnds = {f["properties"]["town"]: f
            for f in json.load(open(BOUNDARIES))["features"]}

    for town in args.towns:
        if town not in bnds:
            print(f"! no boundary for {town}, skipping")
            continue
        s, w, n, e = bbox(bnds[town]["geometry"])
        print(f"{town}: querying Overpass for {s:.3f},{w:.3f},{n:.3f},{e:.3f}")
        data = overpass(QUERY % {"bb": f"{s},{w},{n},{e}"})
        feats = to_features(data)
        path = os.path.join(HERE, f"{town.lower().replace(' ', '-')}.geojson")
        with open(path, "w") as f:
            json.dump({"type": "FeatureCollection", "features": feats},
                      f, separators=(",", ":"))
        kinds = {}
        for ft in feats:
            p = ft["properties"]
            k = ("road" if p.get("highway") else "rail" if p.get("railway")
                 else "water" if p.get("waterway") else "school" if p.get("amenity")
                 else p.get("landuse") or p.get("leisure") or "other")
            kinds[k] = kinds.get(k, 0) + 1
        print(f"  {len(feats)} features, {os.path.getsize(path)/1e6:.1f} MB  "
              + ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())))
        time.sleep(3)                            # be gentle to a free shared service


if __name__ == "__main__":
    main()
