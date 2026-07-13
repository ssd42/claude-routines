#!/usr/bin/env python3
"""Build share/ — a self-contained bundle of market-history data for upload to
Claude Projects (or anywhere else it needs to travel).

Copies the raw sale-grain CSV and derives three rollups so a reader can answer
town / month / season questions without parsing 26k rows.

    python3 build_share.py

Rewrites share/ from scratch each run. Deterministic given the same sales.csv.
"""
import csv
import re
import json
import math
import shutil
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
SALES = HERE / "sales.csv"
ZIPS = HERE / "zips.json"
TRANSIT = HERE / "transit.json"
SEABRA = HERE / "poi_seabra.json"
CENTROIDS = HERE / "zip_centroids.json"
SHARE = HERE / "share"

# market.csv is deliberately NOT shipped: the redfin_dc layer has never pulled, so
# the file is a header and zero rows. Shipping an empty "market trends" CSV invites
# a reader to hallucinate around it. Add it here once it actually has data.

SEASONS = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}

# sold_vs_ask_pct has a few junk extremes (nominal/placeholder list prices:
# min -81%, max +980%). Medians shrug these off; means do not. Anything outside
# this band is excluded from the *mean* columns only, and counted in outliers.
SANE_PCT = (-50.0, 50.0)


def num(row, field):
    """Parse a numeric cell, or None if blank/unparseable."""
    v = row.get(field, "")
    if v in ("", None):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def stats(values):
    """median / mean / n for a list of floats, with outliers held out of the mean."""
    if not values:
        return {"n": 0, "median": "", "mean": "", "outliers": 0}
    sane = [v for v in values if SANE_PCT[0] <= v <= SANE_PCT[1]]
    return {
        "n": len(values),
        "median": round(statistics.median(values), 2),
        "mean": round(statistics.mean(sane), 2) if sane else "",
        "outliers": len(values) - len(sane),
    }


def money(values):
    return round(statistics.median(values)) if values else ""


def haversine_mi(a, b):
    """Straight-line miles between two (lat, lon) pairs."""
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.7613 * math.asin(math.sqrt(h))


def nearest_seabra(town_zips, stores, centroids):
    """Closest Seabra to a town, measured from each of its zip centroids.

    A town is a polygon, not a point, so we take the *minimum* over its zips —
    for multi-zip towns (Edison, Long Hill) that's the corner of town nearest a
    store, which is the honest answer to "could I swing by one".

    Returns (miles, store_name, store_town) or (None, None, None) if the town has
    no centroid — never a guess.
    """
    pts = [centroids[z] for z in town_zips if z in centroids]
    if not pts or not stores:
        return None, None, None
    best = min(
        ((haversine_mi(p, (s["lat"], s["lon"])), s) for p in pts for s in stores),
        key=lambda t: t[0],
    )
    return round(best[0], 1), best[1]["name"], best[1]["town"]


def main():
    rows = list(csv.DictReader(SALES.open()))
    print(f"read {len(rows):,} sales from {SALES.name}")

    # road miles from the Westfield (07090) anchor — makes "closest town I can
    # afford" a single sort instead of a lookup the reader has to do by hand.
    zips = json.loads(ZIPS.read_text())
    dist = {t["name"]: t["dist_mi"] for t in zips["towns"]}
    missing = {r["town"] for r in rows} - set(dist)
    if missing:
        print(f"  ! no dist_mi for: {', '.join(sorted(missing))}")

    # nearest Seabra per town — a NICE-TO-HAVE amenity signal, never a filter.
    # Straight-line from the town's zip centroid(s) to the geocoded stores. The
    # stores all sit outside the target towns, so this is a distance join, not an
    # equality join (see poi_seabra.json).
    stores = [s for s in json.loads(SEABRA.read_text())["locations"] if s.get("lat")]
    centroids = {z: (c["lat"], c["lon"])
                 for z, c in json.loads(CENTROIDS.read_text())["zips"].items()}
    seabra = {
        t["name"]: nearest_seabra(t["zips"], stores, centroids) for t in zips["towns"]
    }
    no_cent = [n for n, v in seabra.items() if v[0] is None]
    if no_cent:
        print(f"  ! no zip centroid, nearest_seabra blank for: {', '.join(sorted(no_cent))}")

    SHARE.mkdir(exist_ok=True)

    # 1. raw sale-grain data, copied verbatim
    shutil.copy2(SALES, SHARE / "sales.csv")
    print(f"  wrote share/sales.csv ({len(rows):,} rows)")

    # bucket every sale by the grains we roll up on
    by_town = defaultdict(list)
    by_town_month = defaultdict(list)
    by_town_season = defaultdict(list)
    for r in rows:
        town, sold = r["town"], r["sold_date"]
        by_town[town].append(r)
        if sold:
            by_town_month[(town, sold[:7])].append(r)
            by_town_season[(town, SEASONS[int(sold[5:7])])].append(r)

    def summarize(group):
        """Shared column set for every rollup grain."""
        ask = [p for p in (num(r, "sold_vs_ask_pct") for r in group) if p is not None]
        sold = [p for p in (num(r, "sold_price") for r in group) if p is not None]
        lst = [p for p in (num(r, "list_price") for r in group) if p is not None]
        dom = [p for p in (num(r, "days_on_market") for r in group) if p is not None]
        a = stats(ask)
        at_or_under = sum(
            1 for r in group
            if num(r, "sold_price") is not None
            and num(r, "list_price") is not None
            and num(r, "sold_price") <= num(r, "list_price")
        )
        return {
            "sales": len(group),
            "sales_with_list_price": len(lst),
            "median_sold_price": money(sold),
            "median_list_price": money(lst),
            "median_sold_vs_ask_pct": a["median"],
            "mean_sold_vs_ask_pct": a["mean"],
            "median_dom": round(statistics.median(dom)) if dom else "",
            "pct_at_or_under_ask": (
                round(100 * at_or_under / len(lst), 1) if lst else ""
            ),
            "outliers_excluded_from_mean": a["outliers"],
        }

    COLS = [
        "sales", "sales_with_list_price", "median_sold_price", "median_list_price",
        "median_sold_vs_ask_pct", "mean_sold_vs_ask_pct", "median_dom",
        "pct_at_or_under_ask", "outliers_excluded_from_mean",
    ]

    # 2. one row per town — sorted closest-to-Westfield first.
    #    SALES ONLY. Amenity layers (transit, seabra) stay in their own files and
    #    are joined on `town` by whoever wants them — see the note above seabra.csv.
    with (SHARE / "by_town.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["town", "dist_mi_from_westfield"] + COLS)
        w.writeheader()
        for town in sorted(by_town, key=lambda t: (dist.get(t, 999), t)):
            w.writerow({
                "town": town,
                "dist_mi_from_westfield": dist.get(town, ""),
                **summarize(by_town[town]),
            })
    print(f"  wrote share/by_town.csv ({len(by_town)} towns)")

    # 3. one row per (town, month)
    with (SHARE / "by_town_month.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["town", "month", "dist_mi_from_westfield"] + COLS)
        w.writeheader()
        for town, month in sorted(by_town_month):
            w.writerow({
                "town": town, "month": month,
                "dist_mi_from_westfield": dist.get(town, ""),
                **summarize(by_town_month[(town, month)]),
            })
    print(f"  wrote share/by_town_month.csv ({len(by_town_month)} town-months)")

    # 4. one row per (town, season) — seasons pooled across all years
    order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
    with (SHARE / "by_town_season.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["town", "season", "dist_mi_from_westfield"] + COLS)
        w.writeheader()
        for town, season in sorted(by_town_season, key=lambda k: (k[0], order[k[1]])):
            w.writerow({
                "town": town, "season": season,
                "dist_mi_from_westfield": dist.get(town, ""),
                **summarize(by_town_season[(town, season)]),
            })
    print(f"  wrote share/by_town_season.csv ({len(by_town_season)} town-seasons)")

    # 5. transit — REFERENCE data, kept in its own file so it can never be mistaken
    #    for a scraped sale. `best_transit_minutes` is derived: the faster of rail
    #    and bus, which is the number a commuter actually cares about.
    transit = json.loads(TRANSIT.read_text())["towns"]
    tcols = [
        "town", "dist_mi_from_westfield", "has_train_station", "station_name",
        "rail_line", "direct_train_to_manhattan", "train_transfer_at",
        "train_minutes_to_manhattan", "nearest_station_if_none",
        "has_bus_to_port_authority", "bus_route", "bus_minutes_to_port_authority",
        "best_transit_minutes", "best_transit_mode", "confidence", "notes",
    ]
    with (SHARE / "transit.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, tcols)
        w.writeheader()
        for t in sorted(transit, key=lambda t: (dist.get(t["town"], 999), t["town"])):
            tr, bs = t["train_minutes_to_manhattan"], t["bus_minutes_to_port_authority"]
            best, mode = None, None
            if tr is not None and (bs is None or tr <= bs):
                best, mode = tr, "train"
            elif bs is not None:
                best, mode = bs, "bus"
            row = {c: t.get(c) for c in tcols}
            row["dist_mi_from_westfield"] = dist.get(t["town"], "")
            row["best_transit_minutes"] = best if best is not None else ""
            row["best_transit_mode"] = mode or ""
            # None -> empty cell, so a null never reads as a 0 or a False
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})
    missing_t = {r["town"] for r in rows} - {t["town"] for t in transit}
    if missing_t:
        print(f"  ! no transit row for: {', '.join(sorted(missing_t))}")
    print(f"  wrote share/transit.csv ({len(transit)} towns)")

    # 6. seabra — a STANDALONE amenity layer, exactly like transit: its own files,
    #    joinable to the sales rollups on `town` by anyone who wants it, but never
    #    fused into them. A Seabra distance is a fact about a TOWN, not about a sale,
    #    so it has no business being a column in by_town.csv. Two files:
    #      seabra.csv         — the 11 store points (the raw source)
    #      seabra_by_town.csv — derived: nearest store to each town
    scols = ["name", "brand", "town", "zip", "address", "lat", "lon", "geocode_precision"]
    with (SHARE / "seabra.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, scols)
        w.writeheader()
        for s in json.loads(SEABRA.read_text())["locations"]:
            w.writerow({c: s.get(c, "") for c in scols})
    print(f"  wrote share/seabra.csv ({len(stores)} geocoded stores)")

    with (SHARE / "seabra_by_town.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f, ["town", "dist_mi_from_westfield", "nearest_seabra_mi",
                "nearest_seabra_store", "nearest_seabra_store_town"]
        )
        w.writeheader()
        for town in sorted(seabra, key=lambda t: (dist.get(t, 999), t)):
            mi, store, stown = seabra[town]
            w.writerow({
                "town": town,
                "dist_mi_from_westfield": dist.get(town, ""),
                "nearest_seabra_mi": "" if mi is None else mi,
                "nearest_seabra_store": store or "",
                "nearest_seabra_store_town": stown or "",
            })
    print(f"  wrote share/seabra_by_town.csv ({len(seabra)} towns)")

    # 7. README drift guard. The README doubles as the SYSTEM PROMPT for whatever
    #    LLM reads this bundle, so a stale count there is not cosmetic — it once
    #    told the model "Cranford is not in this dataset" a scrape after Cranford
    #    landed, i.e. it instructed a refusal of a question the data could answer.
    #    Prose rots; the CSVs don't. Shout when they disagree.
    readme = SHARE / "README.md"
    if readme.exists():
        text = readme.read_text()
        drift = []
        if f"{len(rows):,} sales" not in text:
            drift.append(f"sales count is now {len(rows):,}")
        if f"**{len(by_town)} towns**" not in text:
            drift.append(f"town count is now {len(by_town)}")
        for t in sorted(by_town):
            # a town named as ABSENT that is in fact present => a wrongful refusal
            if re.search(rf"\b{re.escape(t)}\b[^.\n]*\bnot\b[^.\n]*\b(here|in the data|in this dataset)\b",
                         text, re.I):
                drift.append(f"README says {t!r} is absent, but it HAS sales")
        if drift:
            print("\n  !! README.md is STALE — it is the system prompt, fix it:")
            for d in drift:
                print(f"     - {d}")

    sold_dates = [r["sold_date"] for r in rows if r["sold_date"]]
    print(f"\nshare/ built — coverage {min(sold_dates)} → {max(sold_dates)}, "
          f"{len(by_town)} towns, generated {date.today()}")


if __name__ == "__main__":
    main()
