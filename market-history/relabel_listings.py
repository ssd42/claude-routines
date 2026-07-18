#!/usr/bin/env python3
"""Re-label each listing's TOWN from its coordinates, not its ZIP.

WHY. `listings.py` stamps a listing's town by looking its ZIP up in zips.json — but a
ZIP is a USPS mail route, not a municipality, and the two are many-to-many. ZIP 08812
is mapped to Green Brook, so every 08812 listing — including the ones physically in
Dunellen — was labelled "Green Brook". Same story wherever a ZIP is shared (07006 = the
three Caldwells, 07960 = Morristown / Morris Township). See SPIKE-town-resolution.md.

WHAT. A house's coordinates fall inside exactly one town boundary. This tests each
listing's (lat, lon) against layers/geo/town_boundaries.geojson (the same polygons the
map page uses) and rewrites `town` to the polygon it lands in. CDP polygons (the 10
"section" towns — Basking Ridge, Colonia, Gillette …) are tested BEFORE municipalities,
because a section sits inside a township and is the more specific answer.

HONEST ABOUT WHAT IT CAN'T DO. Our polygon set covers only our ~63 target towns. A house
in a town we don't track (a real Dunellen house) lands in NO polygon — so we can't
rename it to "Dunellen" (we have no Dunellen shape), but we CAN stop asserting it's Green
Brook: it keeps its old ZIP label flagged `town_source=zip`, no longer `polygon`-confirmed.
A `town_source` column records how each row was resolved; nothing is dropped, and the old
value is kept in state/town_relabel.json so this is fully reversible.

Re-runnable: it re-resolves from coordinates every run, so it repairs history and can be
run again after each `listings.py` scrape without depending on the scraper knowing about
`town_source`. Pure point-in-polygon — no network, stdlib only.

    python3 relabel_listings.py            # rewrite listings.csv + write the audit sidecar
    python3 relabel_listings.py --dry-run  # report what WOULD change, touch nothing
"""
import argparse
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LISTINGS = os.path.join(HERE, "listings.csv")
BOUNDARIES = os.path.join(HERE, "layers", "geo", "town_boundaries.geojson")
AUDIT = os.path.join(HERE, "state", "town_relabel.json")


def _ring_area(ring):
    """Shoelace area of a ring, in degrees² — only ever compared, never used as a real
    area, so the units don't matter. Used to break polygon overlaps by specificity."""
    a = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def load_polygons():
    """Return [(town, kind, ring, bbox, area)]. Each ring is the outer ring [[lon,lat],…].

    We carry area because our polygons OVERLAP: a borough entirely surrounded by a
    township (Metuchen inside Edison) sits inside both their polygons, since the township
    shape was never hole-punched. The correct answer is always the SMALLER area — the
    borough, or a CDP inside its township — so resolve() picks the smallest container, not
    the first. That one rule subsumes the map's "CDP before muni" precedence."""
    gj = json.load(open(BOUNDARIES))
    polys = []
    for f in gj["features"]:
        ring = f["geometry"]["coordinates"][0]          # all features are simple Polygons
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        polys.append((f["properties"]["town"], f["properties"].get("kind", "muni"),
                      ring, (min(xs), min(ys), max(xs), max(ys)), _ring_area(ring)))
    return polys


def in_ring(lon, lat, ring):
    """Ray-casting point-in-polygon on one ring. GeoJSON coords are [lon, lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and \
           lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def resolve(lat, lon, polys):
    """The SMALLEST-area town polygon containing this point (so a surrounded borough beats
    the township around it), or None when the point is outside every target town."""
    best, best_area = None, None
    for town, _kind, ring, (x0, y0, x1, y1), area in polys:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and in_ring(lon, lat, ring):
            if best_area is None or area < best_area:
                best, best_area = town, area
    return best


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    polys = load_polygons()
    with open(LISTINGS, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames)
        rows = list(reader)
    if "town_source" not in cols:
        cols.insert(cols.index("town") + 1, "town_source")   # sits next to the value it explains

    audit = {}
    tally = {"polygon_agree": 0, "polygon_corrected": 0, "outside": 0, "nocoord": 0}
    corrections = []          # (old -> new) samples, the actual fixes
    outside_by_zip = {}       # ZIP -> count, so a big shared-ZIP gap is visible

    for r in rows:
        old = r["town"]
        lat, lon = num(r.get("lat")), num(r.get("lon"))
        if lat is None or lon is None:
            r["town_source"] = "nocoord"
            tally["nocoord"] += 1
            continue
        hit = resolve(lat, lon, polys)
        if hit is None:
            r["town_source"] = "zip"                          # keep old label, no longer asserted
            tally["outside"] += 1
            outside_by_zip[r["zip"]] = outside_by_zip.get(r["zip"], 0) + 1
            continue
        r["town_source"] = "polygon"
        if hit == old:
            tally["polygon_agree"] += 1
        else:
            tally["polygon_corrected"] += 1
            corrections.append((old, hit, r["zip"]))
            audit[r["property_key"]] = {"old": old, "new": hit, "zip": r["zip"]}
            r["town"] = hit

    # ---- report ----
    n = len(rows)
    print(f"listings           {n}")
    print(f"  polygon-confirmed  {tally['polygon_agree']:>5}  (coords agree with the ZIP label)")
    print(f"  CORRECTED          {tally['polygon_corrected']:>5}  (coords disagree — town rewritten)")
    print(f"  outside all towns  {tally['outside']:>5}  (kept ZIP label, flagged town_source=zip)")
    print(f"  no coordinates     {tally['nocoord']:>5}  (kept ZIP label, flagged town_source=nocoord)")
    if corrections:
        from collections import Counter
        moved = Counter((o, nw) for o, nw, _z in corrections)
        print("\n  biggest relabels (old -> new: count):")
        for (o, nw), c in moved.most_common(12):
            print(f"    {o:>18} -> {nw:<18} {c}")
    if outside_by_zip:
        print("\n  ZIPs with houses outside every target polygon (likely a non-target town,")
        print("  e.g. Dunellen in 08812) — these keep their ZIP label but are no longer asserted:")
        for z, c in sorted(outside_by_zip.items(), key=lambda x: -x[1])[:10]:
            print(f"    {z}: {c}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    with open(LISTINGS, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    json.dump({"corrected": audit, "tally": tally}, open(AUDIT, "w"), indent=1)
    print(f"\nwrote listings.csv (+ town_source) and {os.path.relpath(AUDIT, HERE)} "
          f"({len(audit)} reversible corrections)")


if __name__ == "__main__":
    main()
