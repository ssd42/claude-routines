#!/usr/bin/env python3
"""ONE command that refreshes everything, in the right order, with the guards.

    python3 hydrate.py --check      # what is stale? prints a table, changes nothing
    python3 hydrate.py              # refresh whatever is stale, then rebuild
    python3 hydrate.py --force      # refresh everything regardless of age
    python3 hydrate.py --only sales listings   # just these steps

WHY THIS EXISTS. RUNBOOK.md lists the commands but leaves the judgement to a human:
which zips are stale, whether a layer is due, what a failed pull did to the files. Doing
that by hand went wrong three times in one sitting — a dropped network wrote "every house
left the market", a rebuild baked today's date onto twelve-day-old sales, and the layer
fetchers were simply forgotten because they are on a different clock. All three were
avoidable. So the order, the freshness rules and the guards live here, in code.

THE ORDER IS NOT NEGOTIABLE — each step reads what the one before it wrote:

    sales+listings -> trends -> on-market -> layers -> share -> analysis -> pages

Skip a step and nothing errors; the pages just quietly show older numbers than the data.

THE GUARDS, AND WHAT EACH ONE IS FOR
  * network check before every batch — a mid-run DNS failure used to look like "the
    source returned nothing", and aggregate.py rightly refuses to treat that as data.
  * listings rollback — listings.py has NO empty-guard of its own. It marks anything it
    did not see as gone, so a failed scrape once flipped all 4,190 active listings to
    `gone` in one pass AND EXITED 0. Here the active count is compared before/after and
    the file is restored if it collapses. This is the sharpest edge in the routine.
  * forward-only warning — the on-market scrape spots a relist by comparing against the
    last run. A skipped run is a relist nobody can ever recover. It says so, loudly.

FRESHNESS IS PER SOURCE, because they publish on different clocks. Redfin's trend file
runs ~2 months behind by nature — that is the publisher, not a failed fetch, and chasing
it is wasted effort. The layers move yearly or monthly. Only the scrapes are daily-ish.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# step -> (what it is, how many days before it counts as stale)
STALE_AFTER = {
    "sales":     ("sold sales + sold listings", 3),
    "trends":    ("Redfin market trends",       7),
    "listings":  ("houses on the market NOW",   3),
    "layers":    ("town-grain layers",         30),
}

LAYERS = [                      # (label, script, days before due)
    ("geo",          "layers/geo/fetch_boundaries.py",             180),
    ("income",       "layers/income/fetch_income.py",              365),
    ("tax",          "layers/tax/fetch_tax.py",                    365),
    ("appreciation", "layers/appreciation/fetch_appreciation.py",   30),
    ("schools",      "layers/schools/fetch_schools.py",            180),
    ("education",    "layers/education/fetch_education.py",        180),
    ("flood_polys",  "layers/flood/fetch_flood_polygons.py",       365),
    ("flood_points", "layers/flood/fetch_flood.py",                 30),
]

DERIVED = [("share", "build_share.py"),
           ("analysis", "analysis/seasonality.py"),
           ("pages", "offer/build_data.py")]

BATCH = 8                       # zips per batch — kinder to the listing site
PROBE = "https://maps.nj.gov/arcgis/rest/services?f=json"


def run(script, *args):
    return subprocess.run([sys.executable, script, *args], cwd=HERE).returncode


def online(tries=10, wait=60):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(PROBE, timeout=15) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        print("  !! network down — waiting", wait, "s")
        time.sleep(wait)
    return False


def zips():
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("zips", "zip"):
                    out.extend([v] if isinstance(v, str) else v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(json.load(open(os.path.join(HERE, "zips.json"))))
    return sorted(set(out))


def age(d):
    """days since an ISO date string, or None."""
    if not d:
        return None
    try:
        return (date.today() - datetime.strptime(d[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def freshness():
    """-> {step: (as_of, days_old)} straight from the files, never from memory."""
    st = json.load(open(os.path.join(HERE, "state", "state.json")))

    def oldest(src):
        v = [x.get("last_fetched") for x in st.get(src, {}).values() if x.get("last_fetched")]
        return min(v) if v else None

    with open(os.path.join(HERE, "listings.csv")) as f:
        seen = max((r["last_seen"] for r in csv.DictReader(f)), default=None)

    out = {"sales": oldest("nj_records"), "trends": oldest("redfin_dc"), "listings": seen}
    newest_layer = max((os.path.getmtime(os.path.join(HERE, s))
                        for _, s, _ in LAYERS if os.path.exists(os.path.join(HERE, s))),
                       default=0)
    out["layers"] = (date.fromtimestamp(newest_layer).isoformat() if newest_layer else None)
    return {k: (v, age(v)) for k, v in out.items()}


def report():
    print(f"\n{'step':<12}{'what':<30}{'as of':<13}{'age':>6}   state")
    print("-" * 78)
    for step, (label, limit) in STALE_AFTER.items():
        asof, old = freshness()[step]
        if old is None:
            state = "UNKNOWN"
        elif old > limit:
            state = f"STALE (>{limit}d)"
        else:
            state = "ok"
        print(f"{step:<12}{label:<30}{asof or '?':<13}{(str(old) + 'd') if old is not None else '?':>6}   {state}")
    print("\nRedfin trends lag ~2 months AT SOURCE — a recent fetch still shows an older\n"
          "period_end. That is the publisher, not a stale pull.\n")


def hydrate_sales(force):
    zl = zips()
    print(f"\n=== sold sales + sold listings — {len(zl)} zips in batches of {BATCH} ===")
    print("    (both sources in ONE command on purpose — they only cross-link that way)")
    bad = 0
    for i in range(0, len(zl), BATCH):
        batch = zl[i:i + BATCH]
        if not online():
            print("!! aborting: network down"); return False
        print(f"  batch {i // BATCH + 1}: {' '.join(batch)}")
        if run("aggregate.py", "--source", "nj_records", "listing_scrape", "--zip", *batch):
            bad += 1
    print(f"  batches that failed: {bad}")
    return bad == 0


def hydrate_trends():
    print("\n=== market trends ===")
    for attempt in (1, 2, 3):
        if online() and run("aggregate.py", "--source", "redfin_dc") == 0:
            return True
        print(f"  attempt {attempt} failed")
    return False


def hydrate_listings():
    """The dangerous one. Back up, run, verify, restore if it collapsed."""
    print("\n=== houses on the market NOW (local only — the site blocks datacenter IPs) ===")
    print("    FORWARD-ONLY: a skipped run is a relist nobody can ever recover.")
    src = os.path.join(HERE, "listings.csv")
    rel = os.path.join(HERE, "state", "town_relabel.json")
    bak, rbak = src + ".bak", rel + ".bak"

    def active():
        with open(src) as f:
            return sum(1 for r in csv.DictReader(f) if r["status"] == "active")

    before = active()
    shutil.copy2(src, bak); shutil.copy2(rel, rbak)
    if not online():
        print("!! skipping: network down"); return False
    run("listings.py")
    after = active()
    print(f"  active {before} -> {after}")
    if after < before * 0.75:
        print(f"  !! ROLLBACK — active collapsed past the 25% floor. A scrape that returns\n"
              f"     nothing is a FAILED SCRAPE, not an empty market. Restoring.")
        shutil.copy2(bak, src); shutil.copy2(rbak, rel)
        os.remove(bak); os.remove(rbak)
        return False
    os.remove(bak); os.remove(rbak)
    return True


def hydrate_layers(force):
    print("\n=== town-grain layers (own clocks — a sales rehydrate tells them nothing) ===")
    ok = True
    for label, script, limit in LAYERS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            print(f"  {label:<14} MISSING {script}"); ok = False; continue
        old = (date.today() - date.fromtimestamp(os.path.getmtime(path))).days
        if not force and old < limit:
            print(f"  {label:<14} skip — refreshed {old}d ago, due every {limit}d")
            continue
        print(f"  {label:<14} running")
        if run(script):
            print(f"  {label:<14} FAILED"); ok = False
    return ok


def rebuild():
    print("\n=== rebuild everything derived ===")
    ok = True
    for label, script in DERIVED:
        print(f"  {label}")
        if run(script):
            print(f"  {label} FAILED"); ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report freshness, change nothing")
    ap.add_argument("--force", action="store_true", help="run every step regardless of age")
    ap.add_argument("--only", nargs="*", default=None,
                    help="subset: sales trends listings layers derived")
    args = ap.parse_args()

    report()
    if args.check:
        return

    fresh = freshness()
    want = args.only or [s for s, (_, limit) in STALE_AFTER.items()
                         if args.force or fresh[s][1] is None or fresh[s][1] > limit]
    if args.only is None and not want:
        print("nothing stale. --force to run anyway.\n")
        want = []
    if want:
        print(f"running: {', '.join(want)}")

    results = {}
    if "sales" in want:
        results["sales"] = hydrate_sales(args.force)
    if "trends" in want:
        results["trends"] = hydrate_trends()
    if "listings" in want:
        results["listings"] = hydrate_listings()
    if "layers" in want:
        results["layers"] = hydrate_layers(args.force)
    # derived ALWAYS runs when anything upstream moved — a page built on stale
    # sales still stamps itself with today's date, which reads as fresh and is not.
    if want or "derived" in (args.only or []):
        results["derived"] = rebuild()

    print("\n=== result ===")
    for k, v in results.items():
        print(f"  {k:<10} {'ok' if v else 'FAILED'}")
    report()
    print("commit: git add market-history/{sales,market,listings}.csv share state history analysis\n"
          "        (never `git add -A` — this repo is PUBLIC)\n")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
