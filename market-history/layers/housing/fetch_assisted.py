#!/usr/bin/env python3
"""Government-assisted housing properties in NJ, from HUD. Committed.

    python3 layers/housing/fetch_assisted.py
    python3 layers/housing/fetch_assisted.py --state NY

Writes layers/housing/assisted.geojson -- one point per property, with the unit count
and how many of those units are income-restricted.

THREE HUD LAYERS, because no single one is complete:
  LIHTC       Low-Income Housing Tax Credit properties. The big one: the tax credit is
              how most affordable housing in America actually gets built. ~1,045 in NJ.
  PUBLIC      Public housing developments run by a local housing authority.
  ASSISTED    Multifamily properties with project-based Section 8 -- privately owned,
              federally subsidised rent.

All three are public ArcGIS services: no key, no login, cloud-safe, same shape as the
FEMA call in layers/flood/fetch_flood.py.

WHAT THIS DOES NOT COVER, and it matters in New Jersey. Under the Mount Laurel doctrine
every NJ municipality owes a fair share of affordable housing, and towns overwhelmingly
meet it through INCLUSIONARY ZONING -- a developer builds 200 market-rate apartments and
deed-restricts 30 of them. Those units sit inside an ordinary building with no federal
subsidy, so they appear in none of the layers below. The only record is the town's
Housing Element & Fair Share Plan and the Fair Share Housing Center settlements, which
are documents, not a feed. So: this finds standalone assisted PROPERTIES well, and finds
scattered set-aside UNITS not at all. Do not read an empty map as "there is none here".

DEDUPE. HUD lists a property once per funding allocation, so Siena Village in Wayne
appears three times and Second Westfield twice. Left alone you would triple-count units.
Rows are collapsed on rounded coordinate + address, keeping the largest unit count seen.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assisted.geojson")
PAGE = 1000                     # every one of these services caps a response here

SOURCES = [
    {"kind": "lihtc", "label": "LIHTC (tax-credit)",
     "url": "https://egis.hud.gov/arcgis/rest/services/gotit/LIHTCProperties/MapServer/0",
     "state_field": "STD_ST", "fields": "PROJECT,STD_ADDR,STD_CITY,STD_ZIP5,N_UNITS,LI_UNITS",
     "map": {"name": "PROJECT", "addr": "STD_ADDR", "city": "STD_CITY",
             "zip": "STD_ZIP5", "units": "N_UNITS", "low": "LI_UNITS"}},
    {"kind": "public", "label": "Public housing development",
     "url": "https://egis.hud.gov/arcgis/rest/services/gotit/PublicHousing/MapServer/2",
     "state_field": "STD_ST", "fields": "PROJECT_NAME,STD_ADDR,STD_CITY,STD_ZIP5,TOTAL_UNITS,ACC_UNITS",
     "map": {"name": "PROJECT_NAME", "addr": "STD_ADDR", "city": "STD_CITY",
             "zip": "STD_ZIP5", "units": "TOTAL_UNITS", "low": "ACC_UNITS"}},
    {"kind": "section8", "label": "Multifamily assisted (Section 8)",
     "url": "https://egis.hud.gov/arcgis/rest/services/gotit/MultifamilyProperties/MapServer/0",
     "state_field": "STD_ST", "fields": "PROPERTY_NAME_TEXT,STD_ADDR,STD_CITY,STD_ZIP5,TOTAL_UNIT_COUNT,TOTAL_ASSISTED_UNIT_COUNT",
     "map": {"name": "PROPERTY_NAME_TEXT", "addr": "STD_ADDR", "city": "STD_CITY",
             "zip": "STD_ZIP5", "units": "TOTAL_UNIT_COUNT", "low": "TOTAL_ASSISTED_UNIT_COUNT"}},
]


def get(url, params, timeout=60):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{q}", timeout=timeout) as r:
        return json.load(r)


def field_names(url):
    try:
        return {f["name"] for f in get(url, {"f": "json"}, 30).get("fields", [])}
    except Exception as e:
        print(f"    could not read schema: {e}", file=sys.stderr)
        return set()


def fetch(src, state):
    """Every row for one state, paged. Returns [] and says so rather than raising, so one
    dead layer does not lose the other two."""
    have = field_names(src["url"])
    if not have:
        return []
    wanted = [f for f in src["fields"].split(",") if f in have]
    missing = [f for f in src["fields"].split(",") if f not in have]
    if missing:
        print(f"    note: this layer has no {', '.join(missing)} — those stay blank")
    if src["state_field"] not in have:
        print(f"    ! no {src['state_field']} field; skipping", file=sys.stderr)
        return []

    rows, offset = [], 0
    while True:
        try:
            d = get(src["url"] + "/query", {
                "where": f"{src['state_field']}='{state}'",
                "outFields": ",".join(wanted) or "*",
                "returnGeometry": "true", "outSR": "4326",
                "resultOffset": offset, "resultRecordCount": PAGE, "f": "json"})
        except Exception as e:
            print(f"    ! request failed at offset {offset}: {e}", file=sys.stderr)
            break
        if "error" in d:
            print(f"    ! {d['error'].get('message')}", file=sys.stderr)
            break
        fs = d.get("features", [])
        if "features" not in d:                    # metadata, not a result set
            print(f"    ! unexpected response (no 'features' key)", file=sys.stderr)
            break
        rows += fs
        if len(fs) < PAGE:
            break
        offset += len(fs)
        time.sleep(0.4)
    return rows


def num(v):
    try:
        n = int(float(v))
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="NJ")
    args = ap.parse_args()

    merged = {}
    for src in SOURCES:
        print(f"{src['label']}…")
        rows = fetch(src, args.state)
        print(f"  {len(rows)} rows")
        m = src["map"]
        for f in rows:
            g, a = f.get("geometry") or {}, f.get("attributes") or {}
            x, y = g.get("x"), g.get("y")
            if not x or not y:
                continue
            addr = (a.get(m["addr"]) or "").strip().lower()
            key = (round(y, 5), round(x, 5), addr)
            units = num(a.get(m["units"]))
            low = num(a.get(m["low"])) if m["low"] else None
            cur = merged.get(key)
            if cur:
                # same property, another funding allocation: keep the biggest counts
                cur["units"] = max(cur["units"] or 0, units or 0) or None
                cur["low"] = max(cur["low"] or 0, low or 0) or None
                if src["kind"] not in cur["kinds"]:
                    cur["kinds"].append(src["kind"])
                continue
            merged[key] = {"lat": round(y, 6), "lon": round(x, 6),
                           "name": (a.get(m["name"]) or "").strip().title() or None,
                           "addr": (a.get(m["addr"]) or "").strip().title() or None,
                           "city": (a.get(m["city"]) or "").strip().title() or None,
                           "zip": str(a.get(m["zip"]) or "").strip() or None,
                           "units": units, "low": low, "kinds": [src["kind"]]}
        time.sleep(0.5)

    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
              "properties": {k: v[k] for k in
                             ("name", "addr", "city", "zip", "units", "low", "kinds")}}
             for v in merged.values()]
    with open(OUT, "w") as f:
        json.dump({"type": "FeatureCollection", "state": args.state,
                   "features": feats}, f, separators=(",", ":"))
    tot = sum(x["properties"]["units"] or 0 for x in feats)
    print(f"\n{len(feats)} distinct properties in {args.state}, {tot:,} units total")
    print(f"wrote {os.path.relpath(OUT)} ({os.path.getsize(OUT)/1e3:.0f} KB)")


if __name__ == "__main__":
    main()
