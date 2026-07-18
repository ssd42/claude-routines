#!/usr/bin/env python3
"""Municipal / CDP boundary polygons for our towns, from Census TIGERweb.

    python3 layers/geo/fetch_boundaries.py

Writes layers/geo/town_boundaries.geojson -- one simplified polygon per town, for the
map page (map.html). This is the FOUNDATION of that page, not a nice-to-have: the
"what town am I in" feature is a point-in-polygon test, and centroids can't answer it
(5 of our towns share 2 points; neighbours sit ~2mi apart). See SPIKE-map-page.md.

WHY TWO LAYERS. Several of our "towns" are SECTIONS of a township, not municipalities:
Short Hills + Millburn are both Millburn Twp; Colonia + Woodbridge are Woodbridge Twp;
Stirling/Gillette/Millington are Long Hill Twp. A township has ONE legal boundary, so
those would collapse. But the Census publishes them as CENSUS DESIGNATED PLACES (CDPs,
layer 30) with their own polygons. So we try CDP first (gives a section its own shape),
then fall back to the County Subdivision (layer 22, the legal municipality).

Point-in-polygon precedence at read time must match: test CDPs before municipalities,
because a CDP is the more specific area sitting inside a township.

Simplification is server-side via `maxAllowableOffset` -- no local geometry library
needed, and it keeps each polygon to a few KB instead of ~18.
"""
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
ZIPS = os.path.join(ROOT, "zips.json")
MUNI = os.path.join(ROOT, "nj_municipalities.json")
OUT = os.path.join(HERE, "town_boundaries.geojson")

BASE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
CDP, SUBDIV = 30, 22
NJ = "34"
OFFSET = 0.0007          # ~70m simplification in degrees -- smooth enough, small enough

# our town name -> the name TIGER uses, where they differ
NAME_FIX = {
    "Morris Township": "Morris",     # TIGER county-subdivision NAME is bare
    "West Caldwell": "West Caldwell",
    "Long Hill": "Stirling",         # the township has no CDP; use its main village
    "South Orange": "South Orange Village",
}


def _cxy(rings):
    pts = rings[0]
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)  # lat, lon


def query(layer, name, near):
    """Simplified rings for a BASENAME on a TIGER layer, NJ only.

    `near` = the town's own (lat, lon). NJ has duplicate municipality names across
    counties -- two Springfield Townships, several Washingtons -- so when the name
    matches more than one feature we pick the one whose centroid is NEAREST our town,
    never the largest (largest picked the wrong Springfield, 49mi away).
    """
    q = urllib.parse.urlencode({
        "where": f"BASENAME='{name}' AND STATE='{NJ}'",   # BASENAME is the bare town
        "outFields": "NAME", "returnGeometry": "true", "outSR": "4326",
        "maxAllowableOffset": OFFSET, "f": "json",
    })
    try:
        with urllib.request.urlopen(f"{BASE}/{layer}/query?{q}", timeout=40) as r:
            feats = json.load(r).get("features", [])
    except Exception as e:
        print(f"    ! {name} layer {layer}: {e}")
        return None
    feats = [f for f in feats if f["geometry"].get("rings")]
    if not feats:
        return None

    def dist(f):
        clat, clon = _cxy(f["geometry"]["rings"])
        return (clat - near[0]) ** 2 + (clon - near[1]) ** 2
    return min(feats, key=dist)["geometry"]["rings"]


def main():
    towns = json.load(open(ZIPS))["towns"]
    cent = json.load(open(os.path.join(HERE, "zip_centroids.json")))["zips"]

    feats, cdp_n, sub_n, miss = [], 0, 0, []
    for t in towns:
        name = t["name"]
        tiger = NAME_FIX.get(name, name)
        zc = cent.get(t["zips"][0], {})
        near = (zc.get("lat", 40.7), zc.get("lon", -74.4))

        # Municipality FIRST: a standalone town gets its full legal boundary. A SECTION
        # (Colonia, Short Hills, Basking Ridge...) has no municipality of its own, so it
        # falls to its CDP -- which sits INSIDE the parent township's polygon. At read
        # time we test CDPs before municipalities, so a point in the section resolves to
        # the section and everywhere else in the township resolves to the township.
        rings = query(SUBDIV, tiger, near)
        kind = "muni"
        if not rings:
            rings = query(CDP, tiger, near)
            kind = "cdp"

        if not rings:
            miss.append(name)
            print(f"  MISS  {name}")
            continue
        (cdp_n if kind == "cdp" else globals().__setitem__("_", 0)) if kind == "cdp" else None
        if kind == "cdp":
            cdp_n += 1
        else:
            sub_n += 1
        verts = sum(len(r) for r in rings)
        feats.append({
            "type": "Feature",
            "properties": {"town": name, "kind": kind,
                           "dist": t.get("dist_mi"), "county": t.get("county")},
            "geometry": {"type": "Polygon", "coordinates": rings},
        })
        print(f"  ok   {name:<16} {kind:<4} {verts:>4} verts")
        time.sleep(0.1)

    json.dump({"type": "FeatureCollection", "features": feats}, open(OUT, "w"))
    kb = os.path.getsize(OUT) / 1024
    print(f"\nwrote town_boundaries.geojson  {kb:.0f} KB")
    print(f"  {len(feats)}/{len(towns)} towns  ({cdp_n} CDP, {sub_n} municipality)")
    if miss:
        print(f"  MISSING ({len(miss)}): {', '.join(miss)}  -- resolve by hand")


if __name__ == "__main__":
    main()
