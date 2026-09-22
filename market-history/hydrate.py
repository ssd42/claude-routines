#!/usr/bin/env python3
"""ONE command that refreshes everything, in the right order, with the guards.

    python3 hydrate.py --check      # what is stale? prints a table, changes nothing
    python3 hydrate.py              # refresh whatever is stale, then rebuild
    python3 hydrate.py --force      # refresh everything regardless of age
    python3 hydrate.py --only sales listings   # just these steps
    python3 hydrate.py --town Cranford Garwood # just these towns (sales + on-market)
    python3 hydrate.py --zip 07016 --check     # ...and how stale is just that town?

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

SCOPING TO A FEW TOWNS. A full pull is 74 zips in batches of 8 and takes a while, so
`--town`/`--zip` narrow it to the towns you actually care about today. towns.py does the
resolving, because zip and town are many-to-many BOTH ways — Edison spans three zips, and
07006 covers three towns — so a scope is a superset of what you asked for and says which
neighbours came along. Only `sales` and
`listings` are town-scopable: the trend file is one national download that is filtered
after the fact, and the layers fetch all of our towns per call. Asking to scope those is
an error rather than a no-op, because a "scoped layers refresh" that silently did all of
them is worse than being told no.

THE PAGES' LAST-UPDATED STAMP ONLY MOVES ON A FULL RUN. state/data_asof.json holds the
date of the last complete refresh; a partial does not touch it. So `--town Cranford` gives
Cranford new data without the map claiming all 75 towns are current. The separate
`generated` field stays the real build date, because the seasonal "price it as of now" math
on four pages reads it.

A scoped run judges staleness on the scoped zips, and `--check` does too. Two things make
that honest. Sales already store `last_fetched` per zip, so a narrow pull cannot make the
rest look fresh. On-market freshness used to be the newest `last_seen` in the whole file,
which ANY refresh would push to today and call the step done — it is now the oldest
per-zip newest, so 60 untouched towns still read stale. And `listings.py` no longer ends
spells outside the scope (it used to end all of them; see its header).

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

import towns                     # zip <-> town is many-to-many in BOTH directions

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
    # for the "Where in town" map: both change on the scale of months, not days
    ("assisted",     "layers/housing/fetch_assisted.py",           180),
    ("osm_context",  "layers/osm/fetch_osm_context.py",            180),
]

# (label, script, args). Order matters: coordinates must exist before the desirability
# page is built from them, and sales.csv must already be fresh before we geocode it.
DERIVED = [("share", "build_share.py", []),
           ("analysis", "analysis/seasonality.py", []),
           ("pages", "offer/build_data.py", []),
           ("coords", "layers/geo/fetch_address_coords.py", []),
           ("desirability", "offer/build_desirability.py", [])]

# steps that cannot be narrowed to a town: one national file, and layer fetchers that
# cover all of our towns per call.
NOT_SCOPABLE = ("trends", "layers")

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

    walk(json.load(open(os.path.join(HERE, "config", "zips.json"))))
    return sorted(set(out))


def age(d):
    """days since an ISO date string, or None."""
    if not d:
        return None
    try:
        return (date.today() - datetime.strptime(d[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def freshness(scope=None):
    """-> {step: (as_of, days_old)} straight from the files, never from memory.
    Restricted to `scope`'s zips when given, so a narrowed run is judged on what it
    actually covers."""
    st = json.load(open(os.path.join(HERE, "state", "state.json")))

    def oldest(src):
        v = [x.get("last_fetched") for z, x in st.get(src, {}).items()
             if x.get("last_fetched") and (scope is None or z in scope)]
        return min(v) if v else None

    # PER ZIP, then the oldest of those. The newest `last_seen` in the whole file would
    # be pushed to today by a two-town refresh and report all 74 as current — the exact
    # "fresh date on stale data" failure the rest of this file exists to prevent.
    newest = {}
    with open(os.path.join(HERE, "listings.csv")) as f:
        for r in csv.DictReader(f):
            if scope is None or r["zip"] in scope:
                if r["last_seen"] > newest.get(r["zip"], ""):
                    newest[r["zip"]] = r["last_seen"]
    seen = min(newest.values()) if newest else None

    out = {"sales": oldest("nj_records"), "trends": oldest("redfin_dc"), "listings": seen}
    newest_layer = max((os.path.getmtime(os.path.join(HERE, s))
                        for _, s, _ in LAYERS if os.path.exists(os.path.join(HERE, s))),
                       default=0)
    out["layers"] = (date.fromtimestamp(newest_layer).isoformat() if newest_layer else None)
    return {k: (v, age(v)) for k, v in out.items()}


def report(scope=None):
    if scope:
        print("\n" + scope.describe())
        print("ages below are for those zips only — the other towns are not described here")
    print(f"\n{'step':<12}{'what':<30}{'as of':<13}{'age':>6}   state")
    print("-" * 78)
    fresh = freshness(scope)
    for step, (label, limit) in STALE_AFTER.items():
        asof, old = fresh[step]
        if old is None:
            state = "UNKNOWN"
        elif old > limit:
            state = f"STALE (>{limit}d)"
        else:
            state = "ok"
        note = "  (not town-scoped)" if (scope and step in NOT_SCOPABLE) else ""
        print(f"{step:<12}{label:<30}{asof or '?':<13}"
              f"{(str(old) + 'd') if old is not None else '?':>6}   {state}{note}")
    print("\nRedfin trends lag ~2 months AT SOURCE — a recent fetch still shows an older\n"
          "period_end. That is the publisher, not a stale pull.\n")


def hydrate_sales(force, scope=None):
    zl = list(scope) if scope else zips()
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


def hydrate_listings(scope=None):
    """The dangerous one. Back up, run, verify, restore if it collapsed."""
    print("\n=== houses on the market NOW (local only — the site blocks datacenter IPs) ===")
    print("    FORWARD-ONLY: a skipped run is a relist nobody can ever recover.")
    src = os.path.join(HERE, "listings.csv")
    rel = os.path.join(HERE, "state", "town_relabel.json")
    bak, rbak = src + ".bak", rel + ".bak"

    def active():
        """Counted WITHIN the scope. A scoped run only ever ends spells in its own zips,
        so counting the whole file would bury a collapse under 3,500 untouched rows."""
        with open(src) as f:
            return sum(1 for r in csv.DictReader(f)
                       if r["status"] == "active" and (scope is None or r["zip"] in scope))

    before = active()
    shutil.copy2(src, bak); shutil.copy2(rel, rbak)
    if not online():
        print("!! skipping: network down"); return False
    run("listings.py", *(["--zip", *scope] if scope else []))
    after = active()
    print(f"  active in scope {before} -> {after}")
    # The 25% floor is a proportion, and a scope can be one town with a dozen listings
    # where noise alone clears it. `after == 0` is the shape a 403 or an empty parse
    # actually takes, so it is a rollback at any size.
    if (before and after == 0) or after < before * 0.75:
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


def stamp_full_run(scope, want):
    """Record today as the dataset's as-of date — ONLY after a full refresh.

    The pages print this as their last-updated stamp (build_data.py -> data_asof()). A
    scoped run rebuilds every derived file too, so without this it would print today over
    ~70 towns whose newest sale is weeks old. A partial leaves the file alone and the stamp
    stands still, which is the honest reading: the DATASET has not moved, only a corner of
    it. It also takes a full SCRAPE, not just --only derived: rebuilding from untouched
    CSVs is not a refresh of anything."""
    if scope is not None:
        print("  as-of stamp unchanged — this was a partial (scoped) run")
        return
    if not {"sales", "listings"} <= set(want):
        print("  as-of stamp unchanged — a full run means sales AND listings")
        return
    path = os.path.join(HERE, "state", "data_asof.json")
    with open(path, "w") as fh:
        json.dump({"full_hydrate": date.today().isoformat(),
                   "_doc": "Date of the last FULL hydrate — every zip. The pages show this "
                           "as their last-updated stamp. hydrate.py writes it only after a "
                           "full sales+listings run; a --town/--zip partial leaves it, so a "
                           "narrow refresh cannot advertise the whole set as current."},
                  fh, indent=2)
    print(f"  as-of stamp -> {date.today().isoformat()} (full run)")


def rebuild():
    print("\n=== rebuild everything derived ===")
    ok = True
    for label, script, args in DERIVED:
        print(f"  {label}")
        if run(script, *args):
            print(f"  {label} FAILED"); ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report freshness, change nothing")
    ap.add_argument("--force", action="store_true", help="run every step regardless of age")
    ap.add_argument("--only", nargs="*", default=None,
                    help="subset: sales trends listings layers derived")
    ap.add_argument("--town", dest="towns", nargs="*",
                    help="narrow sales+listings to these towns (case-insensitive)")
    ap.add_argument("--zip", dest="zips", nargs="*",
                    help="narrow sales+listings to these zips")
    args = ap.parse_args()

    try:
        scope = towns.resolve(zips=args.zips, towns=args.towns)
    except towns.Unknown as e:
        sys.exit(str(e))
    if scope and args.only:
        bad = [s for s in args.only if s in NOT_SCOPABLE]
        if bad:
            sys.exit(f"--only {' '.join(bad)} cannot be combined with --town/--zip: "
                     f"{' and '.join(NOT_SCOPABLE)} are not town-scoped "
                     f"(one national file; layer fetchers cover all towns per call).\n"
                     f"Run them unscoped, or drop them from --only.")

    report(scope)
    if args.check:
        return

    fresh = freshness(scope)
    eligible = [s for s in STALE_AFTER if not (scope and s in NOT_SCOPABLE)]
    want = args.only or [s for s in eligible
                         if args.force or fresh[s][1] is None
                         or fresh[s][1] > STALE_AFTER[s][1]]
    if args.only is None and not want:
        print("nothing stale. --force to run anyway.\n")
        want = []
    if want:
        print(f"running: {', '.join(want)}")
    if scope:
        print("  every other town keeps the data it has — nothing is ended or expired\n"
              "  on its behalf, and --check will still report it stale.")

    results = {}
    if "sales" in want:
        results["sales"] = hydrate_sales(args.force, scope)
    if "trends" in want:
        results["trends"] = hydrate_trends()
    if "listings" in want:
        results["listings"] = hydrate_listings(scope)
    if "layers" in want:
        results["layers"] = hydrate_layers(args.force)
    # derived ALWAYS runs when anything upstream moved — a page built on stale
    # sales still stamps itself with today's date, which reads as fresh and is not.
    if want or "derived" in (args.only or []):
        # before rebuild(): build_data.py reads the stamp while writing the pages
        stamp_full_run(scope, want)
        results["derived"] = rebuild()

    print("\n=== result ===")
    for k, v in results.items():
        print(f"  {k:<10} {'ok' if v else 'FAILED'}")
    report(scope)
    print("commit: git add market-history/{sales,market,listings}.csv share state history analysis\n"
          "        (never `git add -A` — this repo is PUBLIC)\n")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
