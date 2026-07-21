#!/usr/bin/env python3
"""Median household income per ZIP, from the ACS 5-year summary file.

    python3 layers/income/fetch_income.py            # fill in any missing zips
    python3 layers/income/fetch_income.py --all      # refresh every zip

Fills gaps in layers/income/income.csv -- one row per (town, zip) in ../../zips.json.
ADDITIVE by default: existing rows are left exactly as they are, because several carry
hand-written `note` text explaining a quirk, and a blind rewrite would lose it.

WHY A FLAT FILE AND NOT THE API. The Census data API (api.census.gov) now rejects
un-keyed requests -- "A valid key must be included with each data API request." The
table-based SUMMARY FILE is the same data as a static download, needs no key, and is what
the original hand-built income.csv already cites as its source. So this stays key-less and
cloud-safe, unlike listing_scrape.

SOURCE. ACS 2020-2024 5-year, table B19013 (Median Household Income in the Past 12 Months,
2024 inflation-adjusted dollars):
  https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b19013.dat
Pipe-delimited, one row per geography: GEO_ID|B19013_E001|B19013_M001. ZCTAs use the
GEO_ID form `860Z200US<zip>`.

CAVEAT THAT MUST RIDE WITH THE NUMBER. A ZCTA is not a town -- it is a mail-delivery area
that can straddle municipal lines -- and the margin of error on a single ZIP is wide
(commonly +/-$15-25k). Two towns $5k apart are not distinguishable. The pages already say
"ACS, +/-wide"; keep it that way. Negative values (-666666666) are the Census null and are
dropped rather than shipped as a number.
"""
import argparse
import csv
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
ZIPS = os.path.join(ROOT, "zips.json")
OUT = os.path.join(HERE, "income.csv")
RAW = os.path.join(HERE, "acsdt5y2024-b19013.dat")   # gitignored transient source (~18 MB)

SRC = ("https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/"
       "data/5YRData/acsdt5y2024-b19013.dat")
PERIOD, BASIS, TABLE, VAR = ("2020-2024 ACS 5-year", "2024 inflation-adjusted dollars",
                             "B19013", "B19013_E001")
COLS = ["town_order", "town", "zip_order_within_town", "zip_code", "dist_mi",
        "median_household_income_usd", "median_household_income_margin_of_error_usd",
        "shared_zip_in_input", "note", "acs_period", "income_year_basis", "metric",
        "census_table", "census_variable", "source_url"]


def load_acs():
    """zip -> (median_income, margin_of_error), skipping Census nulls."""
    if not os.path.exists(RAW):
        print(f"downloading ACS B19013 (~18 MB)\n  {SRC}")
        req = urllib.request.Request(SRC, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as r, open(RAW, "wb") as fh:
            fh.write(r.read())
    out = {}
    with open(RAW) as f:
        for line in f:
            g, _, rest = line.partition("|")
            if not g.startswith("860Z200US"):
                continue
            est, _, moe = rest.strip().partition("|")
            try:
                e, m = int(est), int(moe)
            except ValueError:
                continue
            if e < 0:                      # -666666666 is the Census "no data" sentinel
                continue
            out[g[len("860Z200US"):]] = (e, m if m >= 0 else "")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="refresh every zip, not just missing")
    args = ap.parse_args()

    existing = []
    if os.path.exists(OUT):
        with open(OUT, newline="", encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    have = {r["zip_code"] for r in existing}

    acs = load_acs()
    towns = json.load(open(ZIPS))["towns"]
    # Key on (town, zip), NOT zip alone. Two DIFFERENT municipalities can share one postal
    # ZIP -- Mendham Borough and Mendham Township both sit on 07945, Haledon and North
    # Haledon both on 07508. Deduping by zip gave the second town no income row at all.
    # Each town gets its row; the shared ones are flagged, because the ACS figure describes
    # the ZCTA and therefore cannot distinguish the two towns sharing it.
    zip_towns = {}
    for t in towns:
        for z in t["zips"]:
            zip_towns.setdefault(z, []).append(t["name"])
    seen, added, missing = set(), [], []
    for ti, t in enumerate(towns, 1):
        for zi, z in enumerate(t["zips"], 1):
            if (t["name"], z) in seen:
                continue
            seen.add((t["name"], z))
            if any(r["town"] == t["name"] and r["zip_code"] == z for r in existing) and not args.all:
                continue
            if z not in acs:
                missing.append(f"{t['name']} ({z})")
                continue
            est, moe = acs[z]
            added.append({
                "town_order": ti, "town": t["name"], "zip_order_within_town": zi,
                "zip_code": z, "dist_mi": t.get("dist_mi", ""),
                "median_household_income_usd": est,
                "median_household_income_margin_of_error_usd": moe,
                "shared_zip_in_input": "yes" if len(zip_towns[z]) > 1 else "no",
                "note": (f"ZIP {z} is shared with {', '.join(n for n in zip_towns[z] if n != t['name'])}"
                         " -- the ACS figure describes the ZCTA and cannot separate them."
                         if len(zip_towns[z]) > 1 else ""),
                "acs_period": PERIOD, "income_year_basis": BASIS,
                "metric": "Median household income",
                "census_table": TABLE, "census_variable": VAR, "source_url": SRC,
            })

    newkeys = {(a["town"], a["zip_code"]) for a in added}
    rows = [r for r in existing if (r["town"], r["zip_code"]) not in newkeys] + added
    rows.sort(key=lambda r: (int(r["town_order"] or 0), int(r["zip_order_within_town"] or 0)))
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, quoting=csv.QUOTE_ALL, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote income.csv  {len(rows)} zips  (+{len(added)} new)")
    if missing:
        print(f"  NO ACS ROW ({len(missing)}): {', '.join(missing)}")


if __name__ == "__main__":
    main()
