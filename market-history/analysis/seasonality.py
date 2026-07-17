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
SEASON = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
          6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}

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
        # The price is agreed when the OFFER IS ACCEPTED, not when the deal closes.
        # `pending_date` is that event, recovered by the 2026-07-13 re-scrape (79% of
        # askable rows). Bucketing by sold_date smears the seasonal signal across the
        # ~41-day escrow -- see the contract-month rollups in main().
        pd_ = day(r.get("pending_date"))
        sales.append({
            "town": r["town"], "county": county.get(r["town"], ""),
            "month": sd.month, "year": sd.year, "sold_date": sd, "list_date": ld,
            "pending_date": pd_, "contract_month": pd_.month if pd_ else None,
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

    # 3b. THE CONTRACT-MONTH CURVE — the same question, asked correctly.
    #
    # Everything above buckets a sale by the month it CLOSED. But the price is struck
    # when the offer is accepted, and escrow runs a median 41 days after that, so a
    # closing-month bucket blurs the seasonal signal across six weeks. Bucketing on
    # `pending_date` instead sharpens the peak-to-trough swing from 4.88pp to 6.00pp
    # and moves the cheapest month from January to DECEMBER.
    #
    # It is also the only actionable version: you choose when you make an offer. You
    # do not choose when the deal closes.
    #
    # Written TWICE -- over the full window, and over the last two years only. A
    # consumer that lets the user say "recent sales only" needs a seasonal curve on the
    # same footing, or panel A and panel B are quietly answering about different eras.
    # The recent cut is thinner by construction; its `thin` flags earn their keep.
    #
    # Denominator note: `n` here counts only sales carrying BOTH a usable ask and a
    # pending_date (79% of askable rows) -- a different, smaller base than `n` above.
    newest = max(s["year"] for s in sales)
    WINDOWS = [("", None), ("_recent", {newest - 1, newest})]

    for suffix, keep_years in WINDOWS:
        contract = [s for s in sales if s["contract_month"]
                    and (keep_years is None or s["year"] in keep_years)]
        c_totals = defaultdict(int)
        for s in contract:
            c_totals[(s["town"], s["contract_month"])] += 1

        def cbucket(fn, rows=contract):
            out = defaultdict(list)
            for s in rows:
                out[fn(s)].append(s)
            return out

        c_by_month = cbucket(lambda s: s["contract_month"])
        c_all = defaultdict(int)
        for (town, m), c in c_totals.items():
            c_all[m] += c
        write(os.path.join(outdir, "contract_month_all_towns%s.csv" % suffix),
              ["month", "month_num"], ASK_COLS,
              [((MONTHS[m - 1], m), ask_row(c_by_month[m], c_all[m])) for m in range(1, 13)])

        c_by_tm = cbucket(lambda s: (s["county"], s["town"], s["contract_month"]))
        write(os.path.join(outdir, "by_town_contract_month%s.csv" % suffix),
              ["county", "town", "month", "month_num"], ASK_COLS,
              [((c, t, MONTHS[m - 1], m), ask_row(v, c_totals[(t, m)]))
               for (c, t, m), v in sorted(c_by_tm.items())])

        # contract-SEASON, so a consumer's thin-month fallback stays in one grain.
        # (share/by_town_season.csv exists but buckets on the CLOSING date; falling back
        # from a contract month into a closing season would quietly change the question.)
        c_by_ts = cbucket(lambda s: (s["town"], SEASON[s["contract_month"]]))
        s_totals = defaultdict(int)
        for s in contract:
            s_totals[(s["town"], SEASON[s["contract_month"]])] += 1
        write(os.path.join(outdir, "by_town_contract_season%s.csv" % suffix),
              ["town", "season"], ASK_COLS,
              [((t, se), ask_row(v, s_totals[(t, se)])) for (t, se), v in sorted(c_by_ts.items())])

        # contract-grain, all year — the last rung of that same ladder.
        c_by_t = cbucket(lambda s: s["town"])
        write(os.path.join(outdir, "by_town_contract_all%s.csv" % suffix), ["town"], ASK_COLS,
              [((t,), ask_row(v, len(v))) for t, v in sorted(c_by_t.items())])

        # the LEVEL anchor for this window: every askable sale, contract-date or not.
        # (The contract subset is biased hot -- +4.76% vs +2.45% over ask -- so the
        # magnitude must come from the full sample and only the SHAPE from the subset.)
        lvl_rows = [s for s in sales if keep_years is None or s["year"] in keep_years]
        lvl = cbucket(lambda s: s["town"], lvl_rows)
        write(os.path.join(outdir, "by_town_level%s.csv" % suffix), ["town"], ASK_COLS,
              [((t,), ask_row(v, len(v))) for t, v in sorted(lvl.items())])

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
