#!/usr/bin/env python3
"""Data-defect scanner for share/sales.csv.

Finds rows that are internally inconsistent or unusable, writes one CSV of
offenders per check, and prints a summary. It FIXES NOTHING — it is a detector.
The point is that a re-run after a re-scrape shows whether a defect got better,
got worse, or is still there.

    python3 analysis/defects.py                     # scan -> analysis/defects/<today>/
    python3 analysis/defects.py --out 2026-07-13    # name the scan

See DEFECTS.md for what each check means and what we think the fix is.

A check is (id, severity, description, fn) where fn(rows) -> the defective rows.
Most look at one row at a time; `list_date_is_batch_sentinel` cannot — it has to
see the whole set to learn which dates are bogus. Hence fn takes `rows`, not `row`.
"""
import argparse
import csv
import os
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SALES = os.path.join(HERE, os.pardir, "share", "sales.csv")

# a list_date is called bogus when most of the rows carrying it sold BEFORE it —
# impossible for a real listing date, so the date is a batch artifact, not a fact
BOGUS_MIN_ROWS = 20
BOGUS_MIN_DEFECT_RATE = 0.50


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


def each(pred):
    """Lift a row predicate into a whole-set check."""
    return lambda rows: [r for r in rows if pred(r)]


def _listed_after_sold(r):
    ld, sd = day(r["list_date"]), day(r["sold_date"])
    return ld is not None and sd is not None and (sd - ld).days < 0


def bogus_list_dates(rows):
    """The list_date values that are batch artifacts rather than real dates."""
    total, impossible = Counter(), Counter()
    for r in rows:
        if r["list_date"]:
            total[r["list_date"]] += 1
            if _listed_after_sold(r):
                impossible[r["list_date"]] += 1
    return {d for d, n in total.items()
            if n >= BOGUS_MIN_ROWS and impossible[d] / n >= BOGUS_MIN_DEFECT_RATE}


def list_date_is_batch_sentinel(rows):
    """Rows carrying a known-bogus list_date whose sold_date happens to fall AFTER
    it — so `list_date_after_sold_date` does not catch them. Silently wrong."""
    bogus = bogus_list_dates(rows)
    return [r for r in rows
            if r["list_date"] in bogus and not _listed_after_sold(r)]


def _dom_disagrees(r):
    """days_on_market should equal sold_date - list_date (+/- 1 for rounding)."""
    ld, sd, dom = day(r["list_date"]), day(r["sold_date"]), num(r["days_on_market"])
    if ld is None or sd is None or dom is None:
        return False
    return abs((sd - ld).days - dom) > 3


def _ask_pct_extreme(r):
    p = num(r["sold_vs_ask_pct"])
    return p is not None and abs(p) > 50


def _no_sold_price(r):
    p = num(r["sold_price"])
    return p is None or p <= 0


CHECKS = [
    ("list_date_after_sold_date", "HIGH",
     "list_date is later than sold_date — the house was 'listed' after it sold. "
     "Impossible. These rows cluster on a handful of dates shared by hundreds of "
     "unrelated houses (463 rows across 51 towns all list_date=2024-08-04), so the "
     "date is a scrape batch artifact, not a relist.",
     each(_listed_after_sold)),

    ("list_date_is_batch_sentinel", "HIGH",
     "Row carries a list_date that is PROVEN bogus (most rows on that date sold "
     "before it) but this row's sold_date happens to fall after it, so the check "
     "above misses it. Same corrupt date, no signal. THIS IS THE DANGEROUS ONE — "
     "it is silently wrong and looks fine.",
     list_date_is_batch_sentinel),

    ("days_on_market_disagrees", "MED",
     "days_on_market differs from (sold_date - list_date) by more than 3 days. The "
     "column is otherwise a pure restatement of that subtraction, so a gap means one "
     "of the three fields is wrong.",
     each(_dom_disagrees)),

    ("sold_vs_ask_extreme", "MED",
     "|sold_vs_ask_pct| > 50%. Nominal/placeholder list prices (the range reaches "
     "+980%). Known, and already excluded from every rollup's mean — tracked here "
     "so the count is visible.",
     each(_ask_pct_extreme)),

    ("ask_pct_without_list_price", "HIGH",
     "sold_vs_ask_pct populated but list_price blank — the percentage has nothing "
     "behind it. Should be impossible; non-zero means the merge is dropping "
     "list_price while keeping its derivative.",
     each(lambda r: num(r["sold_vs_ask_pct"]) is not None and num(r["list_price"]) is None)),

    ("no_sold_price", "HIGH",
     "Missing or non-positive sold_price, which is supposed to be authoritative "
     "and always present.",
     each(_no_sold_price)),

    ("no_sold_date", "HIGH",
     "Missing sold_date. Same contract as sold_price — should never happen.",
     each(lambda r: day(r["sold_date"]) is None)),
]

FIELDS = ["address", "zip", "town", "list_date", "sold_date", "days_on_market",
          "list_price", "sold_price", "sold_vs_ask_pct", "property_type",
          "conflicts", "_sources"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="scan dir name (default: today)")
    args = ap.parse_args()

    stamp = args.out or date.today().isoformat()
    outdir = os.path.join(HERE, "defects", stamp)
    os.makedirs(outdir, exist_ok=True)

    with open(SALES, newline="") as fh:
        rows = list(csv.DictReader(fh))

    bogus = bogus_list_dates(rows)
    print("scanned %d rows of share/sales.csv" % len(rows))
    print("proven-bogus list_date values: %d  %s\n" % (
        len(bogus), ", ".join(sorted(bogus)) or "-"))
    print("%-30s %-5s %7s %7s" % ("check", "sev", "rows", "share"))
    print("-" * 54)

    summary, flagged = [], set()
    for cid, sev, _desc, fn in CHECKS:
        hits = fn(rows)
        print("%-30s %-5s %7d %6.2f%%" % (cid, sev, len(hits), len(hits) / len(rows) * 100))
        summary.append((cid, sev, len(hits)))
        for r in hits:
            flagged.add((r["address"], r["zip"], r["sold_date"]))
        if hits:
            with open(os.path.join(outdir, cid + ".csv"), "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(hits)

    with open(os.path.join(outdir, "_summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "severity", "rows", "total_rows", "pct"])
        for cid, sev, n in summary:
            w.writerow([cid, sev, n, len(rows), round(n / len(rows) * 100, 2)])

    print("-" * 54)
    print("distinct rows flagged by >=1 check: %d / %d (%.1f%%)" % (
        len(flagged), len(rows), len(flagged) / len(rows) * 100))
    print("\nwrote analysis/defects/%s/  — see DEFECTS.md" % stamp)


if __name__ == "__main__":
    main()
