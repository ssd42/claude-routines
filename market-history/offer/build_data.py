#!/usr/bin/env python3
"""Bake offer/data.js from the market-history exports.

The page is opened straight off the filesystem (double-click index.html), and a
file:// page cannot fetch() a local CSV -- Chrome blocks it cross-origin. So the
data has to arrive through a <script> tag, which file:// does allow: this writes a
single data.js assigning window.OFFER_DATA.

Two estimators, kept deliberately apart (see SPIKE.md):
  * LEVEL    -- comparable homes (town + sqft/beds/baths), pooled across ALL months.
  * SEASONAL -- town x closing-month sold-vs-ask, pooled across ALL house types.
Comps sliced by month give n~1, so they are never intersected.

    python3 offer/build_data.py
    python3 offer/build_data.py --snapshot 2026-07-13
"""
import argparse
import csv
import json
import os
import statistics as st
from collections import defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir)
SHARE = os.path.join(ROOT, "share")
ANALYSIS = os.path.join(ROOT, "analysis")
LISTINGS = os.path.join(ROOT, "listings.csv")
TIERS = os.path.join(ROOT, "tierlist", "tiers.json")

OUTLIER_PCT = 50.0   # beyond this the list price was a placeholder, not an ask
MIN_SQFT = 200       # below this the sqft field is junk, not a tiny house
# A believable price per square foot. Outside this the SQFT is wrong, not the price:
# `sqft = 19998` is a scraper sentinel on 32 rows across many towns (19,998sqft houses
# "selling" at $37/sqft), and it wrecked the price index before this filter existed --
# Maplewood's 2,500+ band read a $54/sqft median for 2023 and the town came out at +369%.
PPSF_MIN, PPSF_MAX = 100, 2000
SANE_INDEX = (0.8, 2.0)   # a 3-year town multiplier outside this is a bug, not a market
THIN = 10            # under this a bucket is too thin to answer from
INDEX_MIN = 10       # sales/year a town needs before it gets its OWN price index
# Shrinkage for the seasonal SHAPE. A town-month deviation built on 29 sales is mostly
# noise; one built on 200 is mostly signal. Weight = n/(n+SHRINK_K), so a bucket pulls
# toward the all-towns curve in proportion to how little it knows. At n=30 a town gets
# ~50% of its own opinion; at n=120, 80%. Without this, Colonia's Fall bucket (n=29,
# from a town with only 23% contract-date coverage) swung the answer from "+3% over ask"
# to "-1.1% under ask" -- a difference a buyer would act on, built on noise.
SHRINK_K = 30
# Property-type FAMILIES. A Chatham single-family runs $629/sqft and a Chatham condo
# $482 -- a 30% gap -- so pooling them makes every condo look underpriced against a
# median that is mostly houses. Harmless as a caveat on the analyser; fatal on a
# SORTED market list, where "best value" surfaces exactly the mismatched rows first.
# Attached homes are grouped (condo/townhouse/co-op are economically alike and the
# split would halve every bucket). Land/mobile/farm get NO family: they are not houses
# and must never be priced against house comps.
FAMILY = {
    "Single Family": "house",
    "Condo": "attached", "Townhouse": "attached", "Coop": "attached",
    "Condo Townhome Rowhome Coop": "attached",
    "Multi-Family": "multi",
}

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring",
           5: "Spring", 6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall",
           10: "Fall", 11: "Fall"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def quartiles(xs):
    """median, p25, p75 of a non-empty list."""
    s = sorted(xs)
    return (st.median(s), s[len(s) // 4], s[(3 * len(s)) // 4])


def latest_snapshot():
    days = [d for d in os.listdir(ANALYSIS) if d[:2] == "20" and
            os.path.isdir(os.path.join(ANALYSIS, d))]
    if not days:
        raise SystemExit("no analysis/<date>/ snapshot found -- run analysis/seasonality.py")
    return sorted(days)[-1]


def read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def build_comps(sales):
    """The comp universe: rows carrying sqft + beds + baths + a believable ask.

    ~18% of sales. The other 82% are mostly deed records, which carry no listing
    detail at all -- so this is emphatically not missing-at-random.
    """
    out = []
    for r in sales:
        sqft, beds, baths = num(r["sqft"]), num(r["beds"]), num(r["baths"])
        sold, pct = num(r["sold_price"]), num(r["sold_vs_ask_pct"])
        if not sqft or sqft < MIN_SQFT or beds is None or baths is None:
            continue
        if not sold or pct is None or abs(pct) > OUTLIER_PCT:
            continue
        if not (PPSF_MIN <= sold / sqft <= PPSF_MAX):
            continue          # the sqft is wrong (sentinel / lot leaked in), not the price
        year = int(r["sold_date"][:4])
        month = int(r["sold_date"][5:7])          # 9th field; the index still keys on year
        # lot rides along as an OPTIONAL 8th field (0 = unknown). It is on 85% of the
        # comp universe -- better coverage than the house sqft everything else leans on
        # -- and the page uses it whenever it's given. It is a FILTER (match like with
        # like), never a blanket adjustment: at a fixed house size the big-lot half sells
        # +4% higher in Colonia and +48% in Basking Ridge, so one global uplift would be
        # false precision. House sqft and lot are each optional; supply either or both.
        lot = num(r["lot_sqft"])
        lot = int(lot) if lot and lot > 500 else 0
        fam = FAMILY.get(r["property_type"] or "")
        if not fam:
            continue          # land / manufactured / unknown -- not a house, not a comp
        out.append([r["town"], int(sqft), beds, baths, int(sold), round(pct, 2), year, lot,
                    month, fam])
    return out


# Size bands. The index MUST be computed inside them: median $/sqft across a whole town
# moves when the MIX of houses sold changes, and small houses carry a far higher $/sqft.
# Scotch Plains' median sale went 2,099 sqft (2023) -> 1,807 (2026), which alone pushed
# its raw median $/sqft up 51% -- a "51% appreciation" that was mostly a mix shift, and
# it was inflating every indexed comp in that town.
SIZE_BANDS = [(200, 1200), (1200, 1800), (1800, 2500), (2500, 100000)]
BAND_MIN = 5         # sales a (town, band, year) cell needs to contribute


def _band(sqft):
    for lo, hi in SIZE_BANDS:
        if lo <= sqft < hi:
            return (lo, hi)
    return None


def price_index(sales):
    """Market drift, so an old sale can contribute at TODAY's price level.

    Two corrections, and both matter:

    1. PER TOWN. Over the same window Green Brook rose 8.5% and Maplewood 54.4%; a single
       regional index applied uniformly is wrong by tens of points at the extremes.
    2. SIZE-CONTROLLED. Within each town the index is measured inside fixed size bands and
       then combined, so a year that happened to sell smaller houses doesn't masquerade as
       a year that got more expensive. Skipping this made Scotch Plains read +51%.

    A town gets its own index when every year clears INDEX_MIN sales AND at least one size
    band carries the whole series; otherwise it borrows the regional curve and is FLAGGED,
    so the page can say the correction is borrowed rather than measured.
    """
    rows = []
    for r in sales:
        sqft, sold = num(r["sqft"]), num(r["sold_price"])
        if not sqft or sqft < MIN_SQFT or not sold or not r["sold_date"]:
            continue
        ppsf = sold / sqft
        if not (PPSF_MIN <= ppsf <= PPSF_MAX):
            continue
        b = _band(sqft)
        if b:
            rows.append((r["town"], int(r["sold_date"][:4]), b, ppsf))

    years = sorted({y for _t, y, _b, _p in rows})
    years = [y for y in years if sum(1 for _t, yy, _b, _p in rows if yy == y) >= 100]
    newest = years[-1]

    def curve(subset):
        """One index per size band, then the median across bands -> mix-proof."""
        cells = defaultdict(list)
        for y, b, p in subset:
            cells[(b, y)].append(p)
        per_band = []
        for b in SIZE_BANDS:
            if not all(len(cells.get((b, y), [])) >= BAND_MIN for y in years):
                continue                      # band can't carry the whole series
            med = {y: st.median(cells[(b, y)]) for y in years}
            per_band.append({y: med[newest] / med[y] for y in years})
        # One band is a coin-flip and two make the median a mean -- either lets a single
        # bad cell set the whole curve. Demand three.
        if len(per_band) < 3:
            return None
        idx = {y: st.median(pb[y] for pb in per_band) for y in years}
        oldest = idx[years[0]]
        if not (SANE_INDEX[0] <= oldest <= SANE_INDEX[1]):
            return None                       # implausible -> refuse, don't ship it
        return {str(y): round(idx[y], 4) for y in years}

    regional = curve([(y, b, p) for _t, y, b, p in rows])
    town_idx = {}
    for town in {t for t, _y, _b, _p in rows}:
        sub = [(y, b, p) for t, y, b, p in rows if t == town]
        if not all(sum(1 for y, _b, _p in sub if y == yy) >= INDEX_MIN for yy in years):
            continue                          # too thin to measure its own drift at all
        c = curve(sub)
        if c:
            town_idx[town] = c
    return regional, town_idx, newest


def _days(sales, a, b):
    """Median days between two date columns, over rows carrying both."""
    out = []
    for r in sales:
        x, y = r.get(a), r.get(b)
        if not x or not y:
            continue
        try:
            d = (date.fromisoformat(y[:10]) - date.fromisoformat(x[:10])).days
        except ValueError:
            continue
        if 0 <= d <= 365:
            out.append(d)
    return round(st.median(out)) if out else None


# The two halves of the timeline, now that pending_date exists: how long a house sits
# before an offer is accepted, and how long escrow then runs. The second one is why
# the seasonal curve had to move off sold_date.
def days_to_contract(sales):
    return _days(sales, "list_date", "pending_date")


def days_contract_to_close(sales):
    return _days(sales, "pending_date", "sold_date")


def ask_row(r, n_key, pct_key, under_key, dom_key):
    """Normalise one rollup row to the shape the page consumes."""
    n = int(num(r[n_key]) or 0)
    return {
        "n": n,
        "pct": num(r[pct_key]),
        "under": num(r[under_key]),
        "dom": num(r[dom_key]),
        "thin": n < THIN,
    }


def bake_listings():
    """listings.csv -> offer/listings.js, for market.html.

    PERISHABLE, and that makes it unlike data.js. `sales.csv` is immutable history;
    this is a claim about the present that rots -- ~46% of the feed is already
    pending. So we ship `fetched` and let the page stamp how old it is, loudly.

    Only ACTIVE spells go out: a spell we watched leave the market is history, not
    inventory. `mls_status` rides along so the page can default to FOR_SALE and grey
    the pendings rather than silently sending you to a house that is spoken for.
    """
    if not os.path.exists(LISTINGS):
        print("  ! no listings.csv -- run `python3 listings.py` (LOCAL ONLY). Skipping.")
        return None
    rows = read(LISTINGS)
    out, seen_runs = [], set()
    for r in rows:
        seen_runs.add(r["last_seen"])
        if r["status"] != "active":
            continue                      # left the market; not on it now
        price = num(r["last_list_price"])
        if not price:
            continue
        # The listing side needs the SAME $/sqft sanity the comp universe has. A
        # Livingston listing claims 9,020 sqft at $828k -- $92/sqft, which the comp
        # universe rejects outright. Outside the band the SQFT is wrong, not the price,
        # so null it and let the house fall back to lot/beds: a coarse honest answer
        # beats a precise one built on a number we know is junk.
        sq = num(r["sqft"])
        if sq and not (PPSF_MIN <= price / sq <= PPSF_MAX):
            sq = None
        p0 = num(r["first_list_price"])
        out.append({
            "a": r["address"], "t": r["town"], "z": r["zip"],
            "p": int(price),
            "bd": num(r["beds"]), "ba": num(r["baths"]),
            "sq": int(sq) if sq else None,
            "lot": int(num(r["lot_sqft"]) or 0) or None,
            "yr": int(num(r["year_built"]) or 0) or None,
            "ty": r["property_type"] or None,
            "st": r["mls_status"] or None,
            "dom": int(num(r["days_on_mls"]) or 0) or None,
            # first_seen is OUR observation and survives a relist reset; days_on_mls
            # does not. listings.py exists precisely because the feed's number lies.
            "seen": r["first_seen"],
            "spell": int(r["spell"]),
            # `price_changed` in listings.csv is ANY move, up or down -- 5 of the 66
            # we have watched were RAISES, and they were all wearing a "price cut" tag.
            # Direction is decided here, once, so the page cannot get it wrong.
            "cut": bool(p0 and price < p0),
            "up": bool(p0 and price > p0),
            "p0": int(p0) if p0 else None,
            "url": r["url"] or None, "img": r["photo"] or None,
            # The listing copy. It is the ONLY place garage / pool / central air /
            # condition live, and HS mines it in the browser rather than here so a
            # pattern fix needs no re-scrape — the same reason listings.csv stores it
            # verbatim (DEFECTS.md's bldg_desc lesson). Lower-cased and trimmed to
            # keep the payload honest: it is ~1 KB per listing otherwise.
            "tx": (r.get("text") or "").lower()[:700] or None,
        })
    fetched = max(seen_runs) if seen_runs else None
    path = os.path.join(HERE, "listings.js")
    with open(path, "w") as fh:
        fh.write("// GENERATED by build_data.py from ../listings.csv -- do not edit.\n")
        fh.write("// PERISHABLE: true only as of `fetched`. Re-run `python3 listings.py`.\n")
        fh.write("window.MARKET = ")
        json.dump({"fetched": fetched, "listings": out}, fh, separators=(",", ":"))
        fh.write(";\n")
    avail = sum(1 for x in out if x["st"] == "FOR_SALE")
    print(f"listings.js  {os.path.getsize(path)/1024:.0f} KB")
    print(f"  {len(out):>5} active listings   (fetched {fetched})")
    print(f"  {avail:>5} available; {len(out)-avail} pending/contingent")
    return fetched


def bake_sold():
    """share/sales.csv -> offer/sold.js, for sold.html.

    Every sale we hold, as compact arrays. All 40k of them, deliberately: a search page
    that only knows the last 18 months cannot answer "what did this street sell for?",
    which is the entire point of the page. Raw it is ~4 MB; GitHub Pages gzips it to
    ~0.8 MB, which is less than the market page already sends. The subset idea would
    have broken the feature it was meant to protect.

    UNLIKE listings.js this cannot rot -- a 2024 sale is still a 2024 sale next year.
    No staleness stamp, just the window.

    Deliberately NOT included: ac_type (6% filled) and pool (no such field). Both only
    ever lived in the listing description and sales.csv never stored it. A filter that
    silently hides 94% of the market is worse than no filter.
    """
    rows, window = [], []
    for r in read(os.path.join(SHARE, "sales.csv")):
        p = num(r["sold_price"])
        d = r["sold_date"]
        if not p or not d:
            continue
        window.append(d)
        lp = num(r["list_price"])
        vs = num(r["sold_vs_ask_pct"])
        rows.append([
            r["address"], r["town"], d, int(p),
            num(r["beds"]), num(r["baths"]),
            int(num(r["sqft"]) or 0) or None,
            int(num(r["lot_sqft"]) or 0) or None,
            int(num(r["year_built"]) or 0) or None,
            r["property_type"] or None,
            int(lp) if lp else None,
            # junk placeholder list prices reach +980%; the rollups drop them and so do we
            round(vs, 1) if (vs is not None and abs(vs) <= OUTLIER_PCT) else None,
        ])
    rows.sort(key=lambda x: x[2], reverse=True)          # newest first, the default view
    path = os.path.join(HERE, "sold.js")
    with open(path, "w") as fh:
        fh.write("// GENERATED by build_data.py from ../share/sales.csv -- do not edit.\n")
        fh.write("// [address, town, sold_date, sold_price, beds, baths, sqft, lot, year,\n")
        fh.write("//  property_type, list_price, sold_vs_ask_pct]\n")
        fh.write("window.SOLD = ")
        json.dump({"window": [min(window), max(window)], "generated": date.today().isoformat(),
                   "rows": rows}, fh, separators=(",", ":"))
        fh.write(";\n")
    kb = os.path.getsize(path) / 1024
    withask = sum(1 for r in rows if r[11] is not None)
    print(f"sold.js  {kb/1024:.1f} MB")
    print(f"  {len(rows):>6,} sales   {min(window)} -> {max(window)}")
    print(f"  {withask:>6,} with a usable asking price ({100*withask/len(rows):.0f}%)")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", help="analysis/<date> to read (default: newest)")
    args = ap.parse_args()
    snap = args.snapshot or latest_snapshot()

    sales = read(os.path.join(SHARE, "sales.csv"))
    # CONTRACT grain, not closing grain. The price is struck when the offer is
    # accepted; escrow then runs a median 41 days. Bucketing by sold_date smeared the
    # seasonal signal across those six weeks -- switching to pending_date sharpens the
    # peak-to-trough swing from 4.88pp to 6.00pp and moves the cheapest month from
    # January to DECEMBER. It is also the only month the buyer actually controls.
    # All three rungs of the ladder are contract-grain so a fallback never silently
    # changes the question.
    months = read(os.path.join(ANALYSIS, snap, "by_town_contract_month.csv"))
    seasons = read(os.path.join(ANALYSIS, snap, "by_town_contract_season.csv"))
    towns_csv = read(os.path.join(ANALYSIS, snap, "by_town_contract_all.csv"))
    transit = {r["town"]: r for r in read(os.path.join(SHARE, "transit.csv"))}
    seabra = {r["town"]: r for r in read(os.path.join(SHARE, "seabra_by_town.csv"))}
    tj = {r["town"]: r for r in read(os.path.join(SHARE, "trader_joes_by_town.csv"))}
    wawa = {r["town"]: r for r in read(os.path.join(SHARE, "wawa_by_town.csv"))}
    schools = {r["town"]: r for r in read(os.path.join(SHARE, "schools.csv"))}
    # The hand-ranked tier list — OPINION, not data, and the only input here that is.
    # Everything else in data.js is measured; this is the owner's considered ranking of
    # where he wants to live, authored in tierlist/tierlist.html. Checked: it is largely
    # INDEPENDENT of what HS already scores (commute r=-0.29, schools r=+0.41), so it
    # adds a real signal rather than re-weighting one we have.
    tier_of = {}
    if os.path.exists(TIERS):
        for k, towns in json.load(open(TIERS))["tiers"].items():
            for t in towns:
                tier_of[t] = k
    zips_doc = json.load(open(os.path.join(ROOT, "zips.json")))

    comps = build_comps(sales)

    # NB: no town-wide $/sqft is exported, deliberately. A town's blended $/sqft
    # comes off its typical ~1,500sqft houses; multiplying it by a 9,000sqft house
    # yields a confident number about a house unlike anything in the sample. Every
    # comp tier in the page stays anchored to the subject's sq ft, and when nothing
    # in the town is within +/-25% of that size, the page refuses. Shipping the
    # blended figure would just re-arm that mistake.

    # ---- SEASONAL: the three tiers of the ask-premium ladder ----
    # ---- LEVEL from the full sample, SHAPE from the contract subset -------------
    #
    # pending_date is reported on only 79% of askable sales, and that subset is NOT
    # representative: it sold +4.76% over ask against +2.45% for the rows without one --
    # a 2.3pp gap that persists inside every year (2026: +4.05pp), so it is a reporting
    # bias, not a time artifact. Coverage is also wildly uneven by town (Colonia 23%,
    # Long Valley 95%).
    #
    # Taking the seasonal factor straight off that subset would inflate every expected
    # close by ~2pp -- ~$14k on a $625k ask, in the direction that makes a buyer overbid.
    # But bucketing by CLOSING date is genuinely the wrong event. So decompose:
    #
    #     factor(month) = level(town)                <- ALL askable sales. Unbiased, big.
    #                   + [ contract_month(town, m) - contract_baseline(town) ]
    #                                                <- the SHAPE only, from the subset.
    #
    # Built TWICE: over the full window, and over the last two years -- so the page's
    # "last 2 years only" switch moves BOTH panels. If it only re-cut the comps, panel 1
    # would be answering about 2025-26 while panel 2 still answered about 2023-26.
    ASK = ("n", "median_sold_vs_ask_pct", "pct_at_or_under_ask", "median_dom")

    def seasonal(suffix):
        A = lambda name: read(os.path.join(ANALYSIS, snap, name + suffix + ".csv"))
        level = {r["town"]: ask_row(r, *ASK) for r in A("by_town_level")}
        baseline = {r["town"]: ask_row(r, *ASK) for r in A("by_town_contract_all")}

        # the POOLED curve: how every town, together, deviates by month. This is the prior
        # a thin town gets shrunk toward -- 18k sales instead of 29.
        pooled = {int(r["month_num"]): ask_row(r, *ASK)
                  for r in A("contract_month_all_towns")}
        pooled_base_pct = st.median([v["pct"] for v in pooled.values() if v])
        pooled_base_under = st.median([v["under"] for v in pooled.values()
                                       if v and v["under"] is not None])

        def rebase(row, town, month):
            """LEVEL from the town's full sample; SHAPE from the contract subset, shrunk
            toward the all-towns curve in proportion to how thin the bucket is."""
            base, lvl = baseline.get(town), level.get(town)
            if not row or not base or not lvl:
                return row
            n = row["n"]
            w = n / (n + SHRINK_K)                      # trust in this town's own opinion

            own_dev = row["pct"] - base["pct"]
            pool = pooled.get(month)
            pool_dev = (pool["pct"] - pooled_base_pct) if pool else 0.0
            dev = w * own_dev + (1 - w) * pool_dev

            out = dict(row)
            out["pct"] = round(lvl["pct"] + dev, 2)
            out["w"] = round(w, 2)                      # how much of this is the town's own
            if None not in (row["under"], base["under"], lvl["under"]):
                own_u = row["under"] - base["under"]
                pool_u = (pool["under"] - pooled_base_under) if pool and pool["under"] is not None else 0.0
                out["under"] = round(min(100.0, max(0.0,
                    lvl["under"] + w * own_u + (1 - w) * pool_u)), 1)
            return out

        months = defaultdict(dict)
        for r in A("by_town_contract_month"):
            m = int(r["month_num"])
            months[r["town"]][m] = rebase(ask_row(r, *ASK), r["town"], m)
        # a season inherits the shrunk shape of its months, so the ladder stays coherent
        seasons = defaultdict(dict)
        for r in A("by_town_contract_season"):
            mths = [m for m, se in SEASONS.items() if se == r["season"]]
            seasons[r["town"]][r["season"]] = rebase(
                ask_row(r, *ASK), r["town"], mths[len(mths) // 2])
        return months, seasons, level

    by_month, by_season, by_town = seasonal("")
    r_month, r_season, r_town = seasonal("_recent")

    # ---- town reference: zips, distance, and the two colour layers ----
    towns = {}
    zip_to_town = {}
    for t in zips_doc["towns"]:
        name = t["name"]
        if name not in by_town:
            continue          # in the target list but not yet scraped -- no sales, skip
        for z in t["zips"]:
            zip_to_town.setdefault(z, name)
        tr, sb, tjr = transit.get(name, {}), seabra.get(name, {}), tj.get(name, {})
        ww, sch = wawa.get(name, {}), schools.get(name, {})
        towns[name] = {
            "county": t.get("county", ""),
            "zips": t["zips"],
            "dist": t.get("dist_mi"),
            "months": by_month.get(name, {}),
            "seasons": by_season.get(name, {}),
            "all": by_town[name],
            # the same three rungs, measured on the last two years only
            "recent": {"months": r_month.get(name, {}),
                       "seasons": r_season.get(name, {}),
                       "all": r_town.get(name)},
            "seabra": {
                "mi": num(sb.get("nearest_seabra_mi")),
                "store": sb.get("nearest_seabra_store"),
            } if sb else None,
            # nearest OPEN Trader Joe's. Same contract as seabra: colour, never a filter.
            # Unlike seabra, four stores sit inside target towns, so ~0mi is expected.
            "tj": {
                "mi": num(tjr.get("nearest_tj_mi")),
                "store": tjr.get("nearest_tj_store"),
                "inTown": tjr.get("nearest_tj_store_town") == name,
            } if tjr else None,
            # nearest Wawa. `beyond` = the supplied list was cut at ~5mi, so past that
            # this is the closest store WE WERE GIVEN, not necessarily the closest one.
            "wawa": {
                "mi": num(ww.get("nearest_wawa_mi")),
                "store": ww.get("nearest_wawa_store"),
                "inTown": ww.get("nearest_wawa_store_town") == name,
                "beyond": ww.get("beyond_supplied_radius") == "yes",
            } if ww else None,
            # NJ DOE 2024-25 assessment deciles (1=bottom 10% of NJ districts, 10=top).
            # A DISTRICT proxy keyed to zip -- schools go by attendance boundary, and
            # one zip can span districts at different levels (Garwood: elementary
            # Garwood Boro, high school Clark Twp). Town-level only; verify per house.
            # NOT layers/education/ -- that is ACS adult degrees, an income proxy at
            # r=+0.87, which would score a town's wealth and call it schools.
            # "unknown"/"unranked" are NOT the bottom of the ramp — they mean no read
            # yet (tiers.json says so explicitly). They must stay null so the weighted
            # mean drops them, rather than scoring as an F.
            "tier": tier_of.get(name) if tier_of.get(name) in ("S","A","B","C","D","F") else None,
            "school": {
                "el": num(sch.get("elementary_rating_1_to_10")),
                "mid": num(sch.get("middle_rating_1_to_10")),
                "hs": num(sch.get("high_school_rating_1_to_10")),
                "elProf": num(sch.get("elementary_composite_proficiency_pct")),
                "district": sch.get("elementary_districts") or None,
                "splitDistrict": bool(sch.get("elementary_districts")
                                      and sch.get("high_school_districts")
                                      and sch["elementary_districts"] != sch["high_school_districts"]),
            } if sch else None,
            # notes + confidence ride along verbatim -- they are where the truth is
            # (the RVL has no one-seat peak ride, several buses are rush-only, ...)
            "transit": {
                "min": num(tr.get("best_transit_minutes")),
                "mode": tr.get("best_transit_mode"),
                "station": tr.get("station_name") or tr.get("nearest_station_if_none"),
                "hasStation": tr.get("has_train_station") == "True",
                "line": tr.get("rail_line"),
                "conf": tr.get("confidence"),
                "notes": tr.get("notes"),
            } if tr else None,
        }

    regional, town_idx, newest = price_index(sales)

    sold = sorted(r["sold_date"] for r in sales if r["sold_date"])
    data = {
        # Is this the PUBLISHED copy? The live-market browser is deliberately not
        # deployed (it republishes Realtor.com inventory, hotlinks its photos, and
        # rots ~2%/day -- see .github/workflows/pages.yml), so on the public site
        # market.html 404s and index.html must not offer a link to it. The workflow
        # sets OFFER_DEPLOY=1; a local build leaves it unset and the link appears.
        "deployed": bool(os.environ.get("OFFER_DEPLOY")),
        "family": FAMILY,          # listing property_type -> comp family
        "generated": date.today().isoformat(),
        "snapshot": snap,
        "window": [sold[0], sold[-1]],
        "totalSales": len(sales),
        "compUniverse": len(comps),
        "thin": THIN,
        "seasonOf": SEASONS,
        "zipToTown": zip_to_town,
        "towns": towns,
        "priceIndex": regional,     # year -> multiplier onto today's price level
        "townIndex": town_idx,      # same, per town, where the town can carry one
        "grain": "contract",        # the seasonal curve buckets on pending_date
        "daysToContract": days_to_contract(sales),
        "daysContractToClose": days_contract_to_close(sales),
        "recentYears": [str(newest - 1), str(newest)],
        # [town, sqft, beds, baths, sold_price, sold_vs_ask_pct, year, lot_sqft|0, month,
        #  family]  -- filtered live in JS
        "comps": comps,
    }

    out = os.path.join(HERE, "data.js")
    with open(out, "w") as fh:
        fh.write("// GENERATED by build_data.py -- do not edit. Re-run after sales.csv grows.\n")
        fh.write("window.OFFER_DATA = ")
        json.dump(data, fh, separators=(",", ":"))
        fh.write(";\n")

    kb = os.path.getsize(out) / 1024
    print(f"data.js  {kb:.0f} KB")
    print(f"  towns          {len(towns)}")
    print(f"  comp universe  {len(comps)} of {len(sales)} sales "
          f"({100 * len(comps) / len(sales):.0f}%)")
    print(f"  window         {data['window'][0]} -> {data['window'][1]}")
    print(f"  snapshot       {snap}")
    print()
    bake_listings()
    print()
    bake_sold()


if __name__ == "__main__":
    main()
