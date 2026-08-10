#!/usr/bin/env python3
"""Adult EDUCATIONAL ATTAINMENT per ZIP, from the ACS 5-year summary file.

    python3 layers/education/fetch_education.py           # refresh from the newest release
    python3 layers/education/fetch_education.py --year 2024   # pin a release
    python3 layers/education/fetch_education.py --check    # probe only, write nothing

Refreshes the ACS measures in layers/education/education_rates.csv. This layer used to be
HAND-MAINTAINED — a supplied one-off file — which meant the December ACS release only
landed if somebody remembered. Now it re-derives itself.

WHAT IT REFRESHES, AND WHAT IT LEAVES ALONE. Only the three ACS measures move:
`high_school_graduate_or_higher_pct_age_25_plus`, `bachelors_degree_or_higher_pct_age_25_plus`
and `population_age_25_plus` (plus the period/url stamps). The GEOGRAPHY columns —
primary municipality/county, land shares, spanned lists — come from the 2020 ZCTA
relationship files and are STATIC until the 2030 census, so they are preserved verbatim
rather than recomputed. Same instinct as fetch_income.py preserving hand-written notes:
never let a refresh throw away curation it cannot rebuild.

WHY THE FLAT FILE AND NOT THE API. api.census.gov rejects un-keyed requests. The
table-based summary file is the same data as a static download, needs no key, and is what
SOURCE.txt already cites — so this stays key-less and cloud-safe.

SOURCE. ACS 5-year, table B15003 (Educational Attainment for the Population 25 Years and
Over), pipe-delimited, one row per geography. ZCTAs use the GEO_ID form `860Z200US<zip>`:
  https://www2.census.gov/programs-surveys/acs/summary_file/<YEAR>/table-based-SF/data/5YRData/acsdt5y<YEAR>-b15003.dat

  E001            = population 25+                (the denominator)
  E017..E025      = high-school diploma or higher  (diploma, GED, some college,
                    associate's, bachelor's, master's, professional, doctorate)
  E022..E025      = bachelor's or higher

CAVEAT THAT MUST RIDE WITH THE NUMBER. A ZCTA is not a town — it is a mail-delivery area
that can straddle municipal lines — and this measures the NEIGHBOURS, not the schools.
It correlates with household income at r=+0.87 and with median sold price at r=+0.76, so
using it as a school metric scores a town's wealth twice and calls it education.
layers/schools/ is the actual test-result file. See that layer's SOURCE.txt.
"""
import argparse
import csv
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "education_rates.csv")

SRC = ("https://www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/"
       "data/5YRData/acsdt5y{year}-b15003.dat")
GEO_SRC = ("https://www.census.gov/geographies/reference-files/time-series/geo/"
           "relationship-files.2020.html")
ZCTA_PREFIX = "860Z200US"

HS_PLUS = range(17, 26)      # E017..E025 — diploma or better
BACH_PLUS = range(22, 26)    # E022..E025 — bachelor's or better

# The release we know exists. `--year auto` (the default) probes forward from here, so the
# next December release is picked up without a code change.
KNOWN_YEAR = 2024


def probe(year):
    """True if that ACS release is published."""
    req = urllib.request.Request(SRC.format(year=year), method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


def newest_year():
    year = KNOWN_YEAR
    while probe(year + 1):
        year += 1
        if year > KNOWN_YEAR + 10:      # runaway guard
            break
    return year


def load_acs(year):
    """zip -> (hs_plus_pct, bachelors_plus_pct, pop_25_plus)."""
    raw = os.path.join(HERE, f"acsdt5y{year}-b15003.dat")   # gitignored transient (~30 MB)
    if not os.path.exists(raw):
        url = SRC.format(year=year)
        print(f"downloading ACS B15003 {year} (~30 MB)\n  {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(raw, "wb") as fh:
            fh.write(r.read())

    out = {}
    with open(raw) as f:
        header = f.readline().rstrip("\n").split("|")
        idx = {name: i for i, name in enumerate(header)}
        try:
            cols = {n: idx[f"B15003_E{n:03d}"] for n in range(1, 26)}
        except KeyError as e:
            raise SystemExit(f"!! B15003 layout changed — missing {e}. Re-check the source.")

        for line in f:
            parts = line.rstrip("\n").split("|")
            if not parts[0].startswith(ZCTA_PREFIX):
                continue
            try:
                vals = {n: int(parts[cols[n]]) for n in range(1, 26)}
            except (ValueError, IndexError):
                continue
            total = vals[1]
            if total <= 0:                # 4 NJ ZCTAs have a zero denominator
                continue
            hs = sum(vals[n] for n in HS_PLUS)
            ba = sum(vals[n] for n in BACH_PLUS)
            out[parts[0][len(ZCTA_PREFIX):]] = (round(hs / total * 100, 1),
                                                round(ba / total * 100, 1), total)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="auto", help="ACS release year, or 'auto' (default)")
    ap.add_argument("--check", action="store_true", help="probe + compare, write nothing")
    args = ap.parse_args()

    year = newest_year() if args.year == "auto" else int(args.year)
    print(f"ACS release: {year}" + ("  (newest published)" if args.year == "auto" else ""))
    if year == KNOWN_YEAR:
        print("  no newer release than the one already in the file — numbers should not move")

    acs = load_acs(year)
    if not acs:
        raise SystemExit("!! B15003 returned no ZCTA rows — refusing to overwrite the layer.")
    print(f"  parsed {len(acs):,} ZCTAs nationwide")

    with open(OUT, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        cols = list(rows[0].keys())

    period = f"{year - 4}-{year} ACS 5-year"
    moved, missing, unchanged = [], [], 0
    for r in rows:
        z = r["zip_code"].strip()
        got = acs.get(z)
        if not got:
            missing.append(z)
            continue
        hs, ba, pop = got
        old_ba = r["bachelors_degree_or_higher_pct_age_25_plus"]
        if old_ba not in ("", None) and abs(float(old_ba) - ba) >= 0.05:
            moved.append((z, r["primary_municipality"], float(old_ba), ba))
        else:
            unchanged += 1
        r["high_school_graduate_or_higher_pct_age_25_plus"] = f"{hs:.1f}"
        r["bachelors_degree_or_higher_pct_age_25_plus"] = f"{ba:.1f}"
        r["population_age_25_plus"] = str(pop)
        r["education_period"] = period
        r["education_source_url"] = SRC.format(year=year)
        r["geography_source_url"] = GEO_SRC

    print(f"  {len(rows)} rows | {unchanged} unchanged | {len(moved)} moved | "
          f"{len(missing)} with no ACS row")
    for z, town, old, new in moved[:12]:
        print(f"     {z} {town:<22} bachelors+ {old:>5.1f} -> {new:>5.1f}")
    if len(moved) > 12:
        print(f"     ... and {len(moved) - 12} more")

    if args.check:
        print("--check: nothing written")
        return
    if missing and len(missing) > len(rows) * 0.2:
        raise SystemExit(f"!! {len(missing)} of {len(rows)} zips had no ACS row — "
                         "that smells like a layout change, not missing data. Not writing.")

    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, OUT)
    print(f"wrote {os.path.relpath(OUT)} — {len(rows)} ZCTAs, {period}")


if __name__ == "__main__":
    main()
