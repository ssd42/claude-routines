#!/usr/bin/env python3
"""Flood zone per listing point, from FEMA's National Flood Hazard Layer.

    python3 layers/flood/fetch_flood.py              # all active listings, cached
    python3 layers/flood/fetch_flood.py --limit 15   # smoke test

FEMA NFHL is a public ArcGIS service (no key, cloud-safe). Layer 28 is the flood
hazard zones. We query it once per UNIQUE listing point and CACHE the result keyed by
rounded lat/lon, so a re-run only fetches points it has never seen -- a listing that
sits where an earlier one did costs nothing.

Why point-query and not a polygon join: the alternative is downloading every flood
polygon for the region and doing point-in-polygon locally, which needs a geometry
library and re-download as FEMA remaps. A cached point query is simpler and each answer
is permanent-ish (a parcel's zone rarely changes).

Zones: X = minimal risk. A / AE / AH / AO = the 1%-annual ("100-year") floodplain,
mandatory flood insurance. V / VE = coastal high-hazard. A blank/no-feature response
means the point fell outside every mapped polygon = effectively X.

This is LISTINGS-only by nature: sold rows carry no coordinates. That is exactly right
-- flood feeds HS, and HS runs on listings.
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LISTINGS = os.path.join(HERE, os.pardir, os.pardir, "listings.csv")
CACHE = os.path.join(HERE, "flood_cache.json")
NFHL = ("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query")

HIGH_RISK = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}   # SFHA — insurance required


def fema_zone(lat, lon):
    """(zone, high_risk_bool) for a point, or (None, None) on a fetch error."""
    q = urllib.parse.urlencode({
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY", "returnGeometry": "false", "f": "json",
    })
    try:
        with urllib.request.urlopen(f"{NFHL}?{q}", timeout=30) as r:
            feats = json.load(r).get("features", [])
    except Exception:
        return None, None
    if not feats:
        return "X", False                       # outside every polygon = minimal risk
    z = (feats[0]["attributes"].get("FLD_ZONE") or "X").strip().upper()
    return z, z in HIGH_RISK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only this many unique points (smoke test)")
    args = ap.parse_args()

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    rows = [r for r in csv.DictReader(open(LISTINGS))
            if r["status"] == "active" and r["lat"] and r["lon"]]
    pts = {}
    for r in rows:
        key = f"{round(float(r['lat']), 5)},{round(float(r['lon']), 5)}"
        pts.setdefault(key, (float(r["lat"]), float(r["lon"])))

    todo = [k for k in pts if k not in cache]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(pts)} unique points; {len(cache)} cached; fetching {len(todo)}")

    ok = fail = 0
    for i, key in enumerate(todo, 1):
        lat, lon = pts[key]
        z, hi = fema_zone(lat, lon)
        if z is None:
            fail += 1
        else:
            cache[key] = {"zone": z, "high": hi}
            ok += 1
        if i % 200 == 0:
            json.dump(cache, open(CACHE, "w"))     # checkpoint
            print(f"  {i}/{len(todo)}  ({ok} ok, {fail} failed)")
        time.sleep(0.08)                           # be gentle to a public gov service

    json.dump(cache, open(CACHE, "w"))
    hi = sum(1 for v in cache.values() if v["high"])
    print(f"\ncached {len(cache)} points  ({ok} new, {fail} failed this run)")
    print(f"  {hi} in a high-risk flood zone (SFHA)  "
          f"{100 * hi / max(len(cache), 1):.1f}%")


if __name__ == "__main__":
    main()
