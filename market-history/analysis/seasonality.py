#!/usr/bin/env python3
"""Seasonality analysis — when in the year do homes sell over/under asking, and
when did the homes closing in a given month actually hit the market?

Derived rollup over share/sales.csv (+ zips.json for county). Writes CSVs into
analysis/<date>/. Re-runnable: a later run against a re-hydrated sales.csv just
writes a new dated snapshot beside the old one.

    python3 analysis/seasonality.py                     # snapshot dated today
    python3 analysis/seasonality.py --out 2026-07-13    # name the snapshot
    python3 analysis/seasonality.py --keep-defects      # don't drop corrupt list_dates

Two denominators, and mixing them up is the easiest way to be wrong:
  * ask-based figures (`n`)  -> only sales carrying a list price (~60% of rows;
    deed records have no asking price). Rows outside +/-50% sold-vs-ask are junk
    placeholder list prices and are dropped.
  * listing-lag figures (`n_lag`) -> only sales carrying a TRUSTWORTHY list date.
    `list_date` is corrupt on ~1,862 rows (see ../DEFECTS.md) and those are
    excluded by default.
`sales_all` is the full bucket count including deed-only rows. Never use it as a
denominator for either.
"""
import argparse
import csv
import json
import os
import statistics as st
from collections import Counter, defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.path.join(HERE, os.pardir, "share", "sales.csv")
ZIPS = os.path.join(HERE, os.pardir, "zips.json")

OUTLIER_PCT = 50.0   # beyond this the list price was a placeholder, not an ask
THIN = 10            # below this a bucket is too thin to read as signal
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

ASK_COLS = [
    "sales_all", "n", "median_list_price", "median_sold_price",
    "median_sold_vs_ask_pct", "median_sold_vs_ask_abs",
    "mean_sold_vs_ask_pct", "mean_sold_vs_ask_abs",
    "pct_at_or_under_ask", "median_dom", "thin",
]
LAG_COLS = [
    "sales_all", "n_lag", "median_days_list_to_close",
    "pct_listed_same_month", "pct_listed_1mo_before", "pct_listed_2mo_before",
    "pct_listed_3mo_before", "pct_listed_4mo_or_more_before",
    "pct_fresh", "pct_aged", "thin",
]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def day(v):
    try:
        return date(int(v[:4]), int(v[5:7]), int(v[8:10]))
    except (TypeError, ValueError, IndexError):
        return None


def bogus_list_dates(rows):
    """list_date values that are scrape batch artifacts, not real dates. A date
    qualifies when >=20 rows carry it and most of them SOLD BEFORE IT — impossible
    for a real listing. See ../DEFECTS.md #1 and #2."""
    total, impossible = Counter(), Counter()
    for r in rows:
        ld, sd = day(r["list_date"]), day(r["sold_date"])
        if ld:
            total[r["list_date"]] += 1
            if sd and (sd - ld).days < 0:
                impossible[r["list_date"]] += 1
    return {d for d, n in total.items() if n >= 20 and impossible[d] / n >= 0.50}


def load(keep_defects):
    with open(SHARE, newline="") as fh:
        raw = list(csv.DictReader(fh))
    county = {t["name"]: t["county"] for t in json.load(open(ZIPS))["towns"]}

    bogus = set() if keep_defects else bogus_list_dates(raw)
    sales, totals, dropped = [], defaultdict(int), 0
    for r in raw:
        sd = day(r["sold_date"])
        if not sd:
            continue
        totals[(r["town"], sd.month)] += 1
        ld = day(r["list_date"])
        # a list_date is trustworthy only if it is not a known batch artifact and
        # the house did not "list" after it sold
        if ld and not keep_defects and (r["list_date"] in bogus or (sd - ld).days < 0):
            ld, dropped = None, dropped + 1
        pct, lp, sp = num(r["sold_vs_ask_pct"]), num(r["list_price"]), num(r["sold_price"])
        askable = (pct is not None and abs(pct) <= OUTLIER_PCT
                   and lp is not None and sp is not None)
        sales.append({
            "town": r["town"], "county": county.get(r["town"], ""),
            "month": sd.month, "year": sd.year, "sold_date": sd, "list_date": ld,
            "askable": askable, "pct": pct if askable else None,
            "abs": num(r["sold_vs_ask_abs"]), "sold": sp, "list": lp,
            "dom": num(r["days_on_market"]),
        })
    return sales, totals, bogus, dropped


def ask_row(bucket, sales_all):
    """Ask-based summary. Only sales with a usable list price count."""
    v = [s for s in bucket if s["askable"]]
    if not v:
        return None
    pcts = [s["pct"] for s in v]
    absol = [s["abs"] for s in v if s["abs"] is not None]
    doms = [s["dom"] for s in v if s["dom"] is not None]
    return {
        "sales_all": sales_all, "n": len(v),
        "median_list_price": round(st.median(s["list"] for s in v)),
        "median_sold_price": round(st.median(s["sold"] for s in v)),
        "median_sold_vs_ask_pct": round(st.median(pcts), 2),
        "median_sold_vs_ask_abs": round(st.median(absol)) if absol else "",
        "mean_sold_vs_ask_pct": round(st.mean(pcts), 2),
        "mean_sold_vs_ask_abs": round(st.mean(absol)) if absol else "",
        "pct_at_or_under_ask": round(sum(1 for p in pcts if p <= 0) / len(pcts) * 100, 1),
        "median_dom": round(st.median(doms)) if doms else "",
        "thin": "yes" if len(v) < THIN else "",
    }


def lag_row(bucket, sales_all):
    """Listing-lag summary: of the homes that CLOSED in this bucket, how long had
    they been on the market? 'fresh' = listed the same or previous month; 'aged' =
    listed 2+ months before closing. Only rows with a trustworthy list_date count."""
    v = [s for s in bucket if s["list_date"]]
    if not v:
        return None
    lags = Counter()
    for s in v:
        ld, sd = s["list_date"], s["sold_date"]
        lags[min((sd.year - ld.year) * 12 + (sd.month - ld.month), 4)] += 1
    n = len(v)
    p = lambda k: round(lags[k] / n * 100, 1)
    fresh = (lags[0] + lags[1]) / n * 100
    return {
        "sales_all": sales_all, "n_lag": n,
        "median_days_list_to_close": round(st.median((s["sold_date"] - s["list_date"]).days
                                                     for s in v)),
        "pct_listed_same_month": p(0), "pct_listed_1mo_before": p(1),
        "pct_listed_2mo_before": p(2), "pct_listed_3mo_before": p(3),
        "pct_listed_4mo_or_more_before": p(4),
        "pct_fresh": round(fresh, 1), "pct_aged": round(100 - fresh, 1),
        "thin": "yes" if n < THIN else "",
    }


def write(path, keys, cols, rows):
    rows = [(k, r) for k, r in rows if r]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(keys + cols)
        for key, row in rows:
            w.writerow(list(key) + [row[c] for c in cols])
    print("  %-32s %4d rows" % (os.path.basename(path), len(rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="snapshot dir name (default: today)")
    ap.add_argument("--keep-defects", action="store_true",
                    help="keep corrupt list_dates (default: drop them)")
    args = ap.parse_args()

    stamp = args.out or date.today().isoformat()
    outdir = os.path.join(HERE, stamp)
    os.makedirs(outdir, exist_ok=True)

    sales, totals, bogus, dropped = load(args.keep_defects)
    askable = sum(1 for s in sales if s["askable"])
    dated = sum(1 for s in sales if s["list_date"])
    print("share/sales.csv -> %d sales" % len(sales))
    print("  with a usable list price (ask-based work): %d" % askable)
    print("  with a trustworthy list_date (lag work):   %d" % dated)
    if not args.keep_defects:
        print("  dropped %d rows with a corrupt list_date (%d bogus batch dates; see DEFECTS.md)"
              % (dropped, len(bogus)))
    print("\nwriting analysis/%s/" % stamp)

    def bucket(fn):
        out = defaultdict(list)
        for s in sales:
            out[fn(s)].append(s)
        return out

    by_month = bucket(lambda s: s["month"])
    all_by_month = defaultdict(int)
    for (town, month), c in totals.items():
        all_by_month[month] += c

    # 1. the headline seasonal curve — all towns pooled
    write(os.path.join(outdir, "seasonality_all_towns.csv"), ["month", "month_num"],
          ASK_COLS,
          [((MONTHS[m - 1], m), ask_row(by_month[m], all_by_month[m])) for m in range(1, 13)])

    # 2. same, split by year — is the effect stable, or is 2025 softer?
    by_my = bucket(lambda s: (s["month"], s["year"]))
    write(os.path.join(outdir, "seasonality_by_year.csv"), ["month", "month_num", "year"],
          ASK_COLS,
          [((MONTHS[m - 1], m, y), ask_row(v, len(v))) for (m, y), v in sorted(by_my.items())])

    # 3. per-town seasonal curve, pooled across years
    by_tm = bucket(lambda s: (s["county"], s["town"], s["month"]))
    write(os.path.join(outdir, "by_town_month_of_year.csv"),
          ["county", "town", "month", "month_num"], ASK_COLS,
          [((c, t, MONTHS[m - 1], m), ask_row(v, totals[(t, m)]))
           for (c, t, m), v in sorted(by_tm.items())])

    # 4. per-county seasonal curve
    by_cm = bucket(lambda s: (s["county"], s["month"]))
    cty_all = defaultdict(int)
    cty_of = {s["town"]: s["county"] for s in sales}
    for (town, month), c in totals.items():
        cty_all[(cty_of.get(town, ""), month)] += c
    write(os.path.join(outdir, "by_county_month_of_year.csv"),
          ["county", "month", "month_num"], ASK_COLS,
          [((c, MONTHS[m - 1], m), ask_row(v, cty_all[(c, m)]))
           for (c, m), v in sorted(by_cm.items())])

    # 5. LISTING LAG — of the homes closing in month X, when did they hit market?
    #    This is the "is January cheap, or is January just leftovers?" file.
    write(os.path.join(outdir, "listing_lag_by_town_month.csv"),
          ["county", "town", "close_month", "month_num"], LAG_COLS,
          [((c, t, MONTHS[m - 1], m), lag_row(v, totals[(t, m)]))
           for (c, t, m), v in sorted(by_tm.items())])
    write(os.path.join(outdir, "listing_lag_all_towns.csv"), ["close_month", "month_num"],
          LAG_COLS,
          [((MONTHS[m - 1], m), lag_row(by_month[m], all_by_month[m])) for m in range(1, 13)])


if __name__ == "__main__":
    main()
