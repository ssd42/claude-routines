#!/usr/bin/env python3
"""Lat/lon per ADDRESS, from the US Census batch geocoder.

    python3 layers/geo/fetch_address_coords.py --towns Colonia Springfield Wayne
    python3 layers/geo/fetch_address_coords.py --limit 200        # smoke test
    python3 layers/geo/fetch_address_coords.py                    # every town, slow

`sales.csv` has no coordinates -- MOD-IV and the sold scrape both report an address and
nothing geographic. Anything that asks "what is NEAR this house" therefore needs a
lookup, and that is what this builds: `address_coords.json`, keyed by address, written
once and committed.

WHY A SEPARATE FILE and not two new columns on sales.csv:
  - a geocode is DERIVED, not scraped. sales.csv carries `conflicts`/`_sources` and a
    provenance record of what each source said; a coordinate has no disagreement to
    resolve, so it does not belong in that merge. `aggregate.py` stays purely scrape.
  - the repo is the DB. sales.csv is rewritten every hydration -- two more columns
    across 50k rows is a large diff every single run. This file changes only when a
    genuinely new address appears.
  - it is ADDRESS-grain, not sale-grain. A house that sold in 2023 and again in 2026 is
    two rows and one location; key on the address and both rows get it for one lookup.

FREE SEED: `listings.csv` already carries lat/lon for ~96% of its rows (the listing
scrape reports them). Those addresses are taken straight from it -- no request made.

MATCH QUALITY IS NOT OPTIONAL. The batch endpoint returns Match/Non_Match and
Exact/Non_Exact, and we keep it. A geocoder that cannot find an address will happily
hand back something coarse; if that lands here unmarked, every unmatched house in a
town plots on one spot and the map quietly lies about a whole neighborhood. Non_Match
is recorded as a miss, never as a coordinate.

Batch, not one-at-a-time: the batch endpoint takes up to 10,000 addresses per POST and
answers in one round trip. 3,000 addresses is ~20 seconds instead of ~40 minutes.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
SALES = os.path.join(ROOT, "sales.csv")
LISTINGS = os.path.join(ROOT, "listings.csv")
OUT = os.path.join(HERE, "address_coords.json")

BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CHUNK = 1000            # well under the 10k ceiling; keeps a failed POST cheap to redo
BENCHMARK = "Public_AR_Current"


def key(address, town):
    """The join key. Whitespace and case only -- no cleverness, so it stays reversible."""
    return f"{' '.join(address.split()).lower()}|{town.strip().lower()}"


def read_rows(path, towns):
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("address") or not r.get("town"):
                continue
            if towns and r["town"] not in towns:
                continue
            yield r


def seed_from_listings(towns):
    """Addresses the listing scrape already geocoded for us. Free, no request."""
    out = {}
    for r in read_rows(LISTINGS, towns):
        if r.get("lat") and r.get("lon"):
            try:
                out[key(r["address"], r["town"])] = {
                    "lat": round(float(r["lat"]), 6),
                    "lon": round(float(r["lon"]), 6),
                    "match": "listing",       # the source reported it; we did not derive it
                    "src": "listings.csv",
                }
            except ValueError:
                pass
    return out


def post_batch(rows):
    """rows = [(id, street, city, state, zip)] -> {id: (lat, lon, quality)}.

    The response is headerless CSV:
      id, input, Match|Tie|No_Match, Exact|Non_Exact, matched, "lon,lat", tigerid, side
    """
    body, boundary = [], uuid.uuid4().hex
    payload = "".join(
        f"{i},{st},{city},{state},{zp}\n" for i, st, city, state, zp in rows
    ).encode()

    def part(name, value):
        body.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    body.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; '
        f'filename="a.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
    )
    body.append(payload + b"\r\n")
    part("benchmark", BENCHMARK)
    body.append(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        BATCH, data=b"".join(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        text = r.read().decode("utf-8", "replace")

    out = {}
    for rec in csv.reader(text.splitlines()):
        if len(rec) < 6 or rec[2] != "Match":
            continue                                  # No_Match / Tie -> a miss, not a guess
        try:
            lon, lat = (float(x) for x in rec[5].split(","))
        except (ValueError, IndexError):
            continue
        out[rec[0]] = (round(lat, 6), round(lon, 6), rec[3])   # Exact | Non_Exact
    return out


def main():
    ap = argparse.ArgumentParser()
    # Default to the towns the desirability map covers, NOT every town: unscoped this is
    # ~45k unknown addresses. Pass --towns explicitly (or --towns with no values) to widen.
    ap.add_argument("--towns", nargs="*", default=["Colonia", "Springfield", "Wayne"],
                    help="only these towns (default: the three desirability towns)")
    ap.add_argument("--limit", type=int, help="only this many new addresses (smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="report the work, fetch nothing")
    args = ap.parse_args()
    towns = set(args.towns) if args.towns else None       # empty list => every town

    coords = json.load(open(OUT)) if os.path.exists(OUT) else {}
    before = len(coords)

    seeded = 0
    for k, v in seed_from_listings(towns).items():
        if k not in coords:
            coords[k] = v
            seeded += 1

    wanted, meta = {}, {}
    for r in read_rows(SALES, towns):
        k = key(r["address"], r["town"])
        if k not in coords and k not in wanted:
            wanted[k] = (r["address"], r["town"], r.get("zip") or "")
    for r in read_rows(LISTINGS, towns):          # the ~4% the scrape missed
        k = key(r["address"], r["town"])
        if k not in coords and k not in wanted:
            wanted[k] = (r["address"], r["town"], r.get("zip") or "")

    todo = list(wanted)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{before} already known; {seeded} seeded free from listings.csv; "
          f"{len(wanted)} still unknown -> fetching {len(todo)}")
    if args.dry_run or not todo:
        if not args.dry_run:
            json.dump(coords, open(OUT, "w"), indent=0, sort_keys=True)
        return

    ok = miss = 0
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start : start + CHUNK]
        rows = []
        for n, k in enumerate(chunk):
            addr, town, zp = wanted[k]
            # commas would break the CSV the endpoint parses; strip, don't quote
            rows.append((str(n), addr.replace(",", " "), town, "NJ", zp))
            meta[str(n)] = k
        try:
            got = post_batch(rows)
        except Exception as e:
            print(f"  ! batch {start//CHUNK + 1} failed: {e}", file=sys.stderr)
            continue
        for n, (lat, lon, quality) in got.items():
            coords[meta[n]] = {"lat": lat, "lon": lon, "match": quality,
                               "src": "census_batch"}
        ok += len(got)
        miss += len(chunk) - len(got)
        json.dump(coords, open(OUT, "w"), indent=0, sort_keys=True)     # checkpoint
        print(f"  {min(start + CHUNK, len(todo))}/{len(todo)}  "
              f"({ok} matched, {miss} unmatched)")
        time.sleep(1)                              # be gentle to a public gov service

    json.dump(coords, open(OUT, "w"), indent=0, sort_keys=True)
    exact = sum(1 for v in coords.values() if v["match"] == "Exact")
    print(f"\n{len(coords)} addresses located ({len(coords) - before} new this run)")
    print(f"  {ok} matched, {miss} unmatched this run")
    print(f"  {exact} exact, {len(coords) - exact} interpolated or listing-reported")


if __name__ == "__main__":
    main()
