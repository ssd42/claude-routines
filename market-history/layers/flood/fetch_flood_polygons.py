#!/usr/bin/env python3
"""FEMA high-risk flood ZONE POLYGONS for our map area, as GeoJSON.

    python3 layers/flood/fetch_flood_polygons.py

Writes layers/flood/flood_zones.geojson -- the Special Flood Hazard Areas (the 1%-annual
"100-year" zones: A/AE/AH/AO/AR/V/VE) intersecting our towns' bounding box, simplified.

WHY NOT FEMA'S TILE OVERLAY. FEMA's NFHL MapServer layer 28 has minScale ~1:36k, so it
only renders when zoomed in past ~z14. On a glance-map that opens state-wide, toggling it
does nothing visible. So we pull the polygons ONCE and draw them ourselves at every zoom,
styled to read (translucent blue), lazy-loaded by the map only when the flood toggle is
first used.

Paged with resultOffset (FEMA caps a response at 2000 features). Simplified server-side
via maxAllowableOffset to keep the file small.
"""
import json
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "flood_zones.geojson")
LAYER = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# our towns' bounding box (from zip centroids) plus a margin
BBOX = (-74.85, 40.45, -74.05, 41.08)
PAGE = 2000


def page(offset):
    q = urllib.parse.urlencode({
        "where": "SFHA_TF='T'",                       # Special Flood Hazard Area only
        "geometry": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}",
        "geometryType": "esriGeometryEnvelope", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE", "returnGeometry": "true", "outSR": "4326",
        "maxAllowableOffset": "0.0006", "geometryPrecision": "5",
        "f": "geojson", "resultRecordCount": PAGE, "resultOffset": offset,
    })
    with urllib.request.urlopen(f"{LAYER}?{q}", timeout=120) as r:
        return json.load(r)


def main():
    feats, offset = [], 0
    while True:
        g = page(offset)
        got = g.get("features", [])
        feats.extend(got)
        print(f"  offset {offset}: +{len(got)}  (total {len(feats)})")
        if len(got) < PAGE and not g.get("exceededTransferLimit"):
            break
        offset += PAGE
        if offset > 20000:                            # safety stop
            break

    # keep only what the map needs: geometry + zone; drop the rest
    slim = [{"type": "Feature",
             "properties": {"z": f["properties"].get("FLD_ZONE")},
             "geometry": f["geometry"]}
            for f in feats if f.get("geometry")]
    json.dump({"type": "FeatureCollection", "features": slim},
              open(OUT, "w"), separators=(",", ":"))
    from collections import Counter
    kb = os.path.getsize(OUT) / 1024
    print(f"\nwrote flood_zones.geojson  {kb:.0f} KB")
    print(f"  {len(slim)} SFHA polygons  {dict(Counter(f['properties']['z'] for f in slim))}")


if __name__ == "__main__":
    main()
