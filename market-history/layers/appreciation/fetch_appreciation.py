#!/usr/bin/env python3
"""Per-town home-price APPRECIATION from Zillow's ZHVI, by ZIP.

    python3 layers/appreciation/fetch_appreciation.py

Writes layers/appreciation/appreciation_by_town.csv -- one row per town: the total
appreciation over a fixed ~3-year window, town-specific, from a single consistent source.

WHY. Our internal size-controlled index only clears its quality bar for ~20 towns; the
other 43 borrowed ONE regional average, so the map painted 43 towns the identical value --
a borrowed guess dressed as measurement. Zillow's ZHVI is published monthly per ZIP and
covers all 63 towns' ZIPs, so every town gets a real number from the same method. (It also
sanity-corrects our thin internal reads -- e.g. Summit was +48% internally, +27% here.)
The internal index is untouched and still does its real job: adjusting comps in the analyser.

SOURCE. Zillow Home Value Index (ZHVI), "All Homes, smoothed & seasonally adjusted, by ZIP":
  https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
A ~120 MB CSV, one row per US ZIP, one column per month (2000-01 .. present). Free, key-less.

LOCAL PREP, like listing_scrape / the tax layer: the download is big, so this runs by hand
and commits only the tiny per-town CSV. CI/build read that CSV, never this file.

METHOD. End = the latest month in the file; start = the same month 3 years earlier (matches
the "~3 years, 2023->today" framing already on the page). A town's ZHVI comes from its
ZIP(s); multi-ZIP towns average their ZIPs' appreciation. ZHVI is a smoothed typical-value
index (not a repeat-sales index), so it reads as "typical home value then vs now" -- exactly
the town-level signal the map wants.
"""
import csv
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
ZIPS = os.path.join(ROOT, "zips.json")
OUT = os.path.join(HERE, "appreciation_by_town.csv")
RAW = os.path.join(HERE, "zhvi_zip.csv")   # gitignored transient source (~120 MB)

SRC = ("https://files.zillowstatic.com/research/public_csvs/zhvi/"
       "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv")
WINDOW_YEARS = 3


def main():
    import json

    if not os.path.exists(RAW):
        print(f"downloading ZHVI (~120 MB)\n  {SRC}")
        req = urllib.request.Request(SRC, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(RAW, "wb") as fh:
            fh.write(r.read())

    with open(RAW) as f:
        rd = csv.reader(f)
        hdr = next(rd)
        zi, si = hdr.index("RegionName"), hdr.index("State")
        month_cols = [i for i, h in enumerate(hdr) if h[:2] == "20" and "-" in h]
        end_i = month_cols[-1]
        end_month = hdr[end_i]
        start_prefix = f"{int(end_month[:4]) - WINDOW_YEARS}{end_month[4:7]}"  # e.g. 2023-06
        start_cands = [i for i in month_cols if hdr[i].startswith(start_prefix)]
        start_i = start_cands[0] if start_cands else month_cols[0]
        start_month = hdr[start_i]

        zhvi = {}   # NJ zip -> (start_val, end_val)
        for row in rd:
            if row[si] != "NJ":
                continue
            try:
                s, e = float(row[start_i]), float(row[end_i])
            except ValueError:
                continue
            if s > 0 and e > 0:
                zhvi[row[zi]] = (s, e)

    towns = json.load(open(ZIPS))["towns"]
    rows, miss = [], []
    for t in towns:
        pairs = [zhvi[z] for z in t["zips"] if z in zhvi]
        if not pairs:
            miss.append(t["name"])
            continue
        apprs = [100 * (e / s - 1) for s, e in pairs]
        rows.append({
            "town": t["name"],
            "appr_pct": round(sum(apprs) / len(apprs), 1),
            "zhvi_now": round(sum(e for _s, e in pairs) / len(pairs)),
            "start_month": start_month, "end_month": end_month,
            "n_zips": len(pairs),
        })

    rows.sort(key=lambda x: x["town"])
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote appreciation_by_town.csv  {len(rows)}/{len(towns)} towns")
    print(f"  window: {start_month} -> {end_month} (Zillow ZHVI by ZIP)")
    if miss:
        print(f"  MISSING ({len(miss)}): {', '.join(miss)}")


if __name__ == "__main__":
    main()
