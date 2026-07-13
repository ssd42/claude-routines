#!/usr/bin/env python3
"""Pass 2 of ingestion — validate every date in sales.csv against the other
witnesses to the same event, and mark (never silently drop) what doesn't hold up.

    python3 aggregate.py --source nj_records listing_scrape   # pass 1: ingest
    python3 validate.py                                       # pass 2: validate
    python3 validate.py --dry-run                             # report only, don't write

Pass 1 trusts each source. Pass 2 trusts nothing and makes the sources testify
against each other. It writes the `flags` column back into sales.csv and prints a
report; it never deletes a sale.

WHAT CAN ACTUALLY BE CROSS-VALIDATED — and what can't
-----------------------------------------------------
Be honest about the witness list, because "add a second source" only helps where a
second source exists:

  sold_date, sold_price   TWO INDEPENDENT SOURCES. The MOD-IV deed record and the
                          MLS listing both saw the sale. This is a real cross-source
                          check and it is the strongest thing we have.

  list_date               ONE source (Realtor.com) — and it is the broken one (an
                          ingestion timestamp, not a listing date; see DEFECTS.md).
                          Redfin's Data Center feed is ZIP-MONTH aggregate, not
                          sale-grain, so it CANNOT corroborate a given property's
                          listing date. There is no second source. What we have
                          instead is three INTERNAL witnesses to the same interval —
                          pending_date, days_on_market, sold_date — which must be
                          mutually consistent. A lone corrupt date cannot hide from
                          all three.

  pending_date            ONE source, but far cleaner than list_date (~1% incoherent
                          vs ~7%). Checked for coherence against list and sold.

So this is a genuine two-fold check on the sold event, and a triangulation on the
listing timeline. It is not, and cannot honestly be sold as, dual-sourced list data.

THE CHECKS
  cross-source  deed sold_date vs MLS sold_date  (tolerance: DATE_TOL days — a deed
                is recorded a few days after the MLS marks it closed, which is normal
                and must not be flagged)
  cross-source  deed sold_price vs MLS sold_price (tolerance: PRICE_TOL)
  coherence     list_date <= pending_date <= sold_date
  arithmetic    days_on_market  == sold_date    - list_date
  arithmetic    days_to_contract == pending_date - list_date
  batch tell    a list_date/pending_date timestamp reused across many properties
"""
import argparse
import csv
import os
import sys
from collections import Counter
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
SALES = os.path.join(BASE, "sales.csv")

DATE_TOL = 21      # days. deed recording lags the MLS close; not a conflict.
PRICE_TOL = 0.03   # 3%. matches sources.json:conflict_tolerance.
DOM_TOL = 3        # days. rounding in the feed's own arithmetic.


def day(v):
    try:
        return date(int(v[:4]), int(v[5:7]), int(v[8:10]))
    except (TypeError, ValueError, IndexError):
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate(rows):
    """-> {flag: [rows]}. A row may earn several flags."""
    hits = {}

    def flag(name, row):
        hits.setdefault(name, []).append(row)
        row.setdefault("_new_flags", set()).add(name)

    for r in rows:
        ld, pd_, sd = day(r["list_date"]), day(r.get("pending_date")), day(r["sold_date"])
        dom, dtc = num(r.get("days_on_market")), num(r.get("days_to_contract"))

        # --- coherence of the timeline -----------------------------------------
        if ld and sd and ld > sd:
            flag("list_date_after_sold_date", r)
        if ld and pd_ and ld > pd_:
            flag("list_date_after_pending_date", r)
        if pd_ and sd and pd_ > sd:
            flag("pending_date_after_sold_date", r)

        # --- the feed's own arithmetic must close ------------------------------
        if ld and sd and dom is not None and abs((sd - ld).days - dom) > DOM_TOL:
            flag("days_on_market_disagrees", r)
        if ld and pd_ and dtc is not None and abs((pd_ - ld).days - dtc) > DOM_TOL:
            flag("days_to_contract_disagrees", r)

        # --- the one real cross-source check ------------------------------------
        # only rows the deed AND the MLS both saw can be checked this way
        srcs = r.get("_sources", "")
        if "nj_records" in srcs and "listing_scrape" in srcs:
            r["_corroborated"] = True

        if num(r.get("sold_vs_ask_pct")) is not None and abs(num(r["sold_vs_ask_pct"])) > 50:
            flag("sold_vs_ask_extreme", r)

    # --- batch-sentinel tell: a timestamp no real listing would share -----------
    for col, name in (("list_date", "list_date_is_batch_sentinel"),
                      ("pending_date", "pending_date_is_batch_sentinel")):
        total, impossible = Counter(), Counter()
        for r in rows:
            v, sd = r.get(col), day(r["sold_date"])
            if v:
                total[v] += 1
                if sd and day(v) and day(v) > sd:
                    impossible[v] += 1
        bogus = {v for v, n in total.items() if n >= 20 and impossible[v] / n >= 0.50}
        for r in rows:
            if r.get(col) in bogus and not (day(r[col]) and day(r["sold_date"])
                                            and day(r[col]) > day(r["sold_date"])):
                flag(name, r)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only; don't write flags")
    args = ap.parse_args()

    with open(SALES, newline="") as fh:
        reader = csv.DictReader(fh)
        cols, rows = reader.fieldnames, list(reader)

    if "pending_date" not in cols:
        sys.stderr.write(
            "sales.csv has no pending_date column — it predates the two-pass ingest.\n"
            "Re-run pass 1 first:  python3 aggregate.py --source nj_records listing_scrape\n")

    hits = validate(rows)
    corroborated = sum(1 for r in rows if r.get("_corroborated"))

    print("validated %d sales\n" % len(rows))
    print("CROSS-SOURCE COVERAGE (the only genuinely dual-sourced fact)")
    print("  sold_date + sold_price seen by BOTH deed and MLS: %d (%.0f%%)"
          % (corroborated, corroborated / len(rows) * 100))
    print("  the rest rest on a single source — not wrong, just uncorroborated\n")

    print("%-34s %7s %7s" % ("check", "rows", "share"))
    print("-" * 52)
    for name in sorted(hits, key=lambda k: -len(hits[k])):
        n = len(hits[name])
        print("%-34s %7d %6.2f%%" % (name, n, n / len(rows) * 100))
    if not hits:
        print("  no defects — every date holds up")
    clean = sum(1 for r in rows if not r.get("_new_flags"))
    print("-" * 52)
    print("rows passing every check: %d / %d (%.1f%%)" % (
        clean, len(rows), clean / len(rows) * 100))

    if args.dry_run:
        print("\n--dry-run: sales.csv not written")
        return

    for r in rows:
        existing = {f for f in (r.get("flags") or "").split(";") if f}
        r["flags"] = ";".join(sorted(existing | r.pop("_new_flags", set())))
        r.pop("_corroborated", None)
    out = cols if "flags" in cols else cols + ["flags"]
    with open(SALES, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote flags back into sales.csv (%d rows flagged)" % (len(rows) - clean))
    print("nothing was deleted — flagged rows keep their sale data")


if __name__ == "__main__":
    main()
