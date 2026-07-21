"""Stages 1, 2, 5 and 6 — everything deterministic, assembled into one packet.

Reads run/subject_blind.json and writes run/context.json: the comp anchor, the
comparables with ask AND sold, house-level flood and store distances, and the estimated
holding cost. All blind — nothing here touches the asking price.

  python3 context.py
"""
import csv, json, math, statistics as st
from pathlib import Path
import comps as C

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUN = HERE / "run"


def haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _ring_contains(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def flood_zone(lat, lon):
    """Point-in-polygon against the FEMA layer. THIS house, not the town average --
    the pages today can only say what share of a town is in a flood zone."""
    p = ROOT / "layers" / "flood" / "flood_zones.geojson"
    if not p.exists() or lat is None: return None
    g = json.loads(p.read_text())
    for f in g["features"]:
        geom = f.get("geometry") or {}
        polys = ([geom["coordinates"]] if geom.get("type") == "Polygon"
                 else geom.get("coordinates", []) if geom.get("type") == "MultiPolygon" else [])
        for poly in polys:
            if poly and _ring_contains((lon, lat), poly[0]):
                return f["properties"].get("z")
    return None


def stores_near(lat, lon):
    """House-to-store, which is new. layers/README.md is explicit that these are
    nice-to-haves and NEVER filters or price adjustments -- they go in the narrative."""
    out = {}
    for name, f in [("wawa", "wawa/wawa.json"),
                    ("trader_joes", "trader_joes/trader_joes.json"),
                    ("seabra", "seabra/seabra.json")]:
        p = ROOT / "layers" / f
        if not p.exists() or lat is None: continue
        d = json.loads(p.read_text())
        locs = next((v for v in d.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
        best = None
        for s in locs:
            if s.get("status") and s["status"] != "open": continue
            if s.get("lat") is None: continue
            mi = haversine_mi(lat, lon, s["lat"], s["lon"])
            if best is None or mi < best[0]: best = (mi, s.get("name") or s.get("town"))
        if best: out[name] = {"miles": round(best[0], 2), "which": best[1]}
    return out


def transit(town):
    p = ROOT / "layers" / "transit" / "transit.json"
    if not p.exists(): return {}
    d = json.loads(p.read_text())
    # several keys hold lists (_caveats etc) -- take the one holding dicts
    rows = next((v for v in d.values()
                 if isinstance(v, list) and v and isinstance(v[0], dict)), [])
    for r in rows:
        if r.get("town") == town:
            # NOTE: town-grain. The layer names the station but carries no coordinates,
            # so "how far is THIS house from the platform" is not computable today.
            return {**r, "_grain": "town — no station coordinates, so this is not "
                                   "distance from this house"}
    return {}


def recent_sales(town, beds, baths, sqft, months=18, k=3):
    """Comparables for the OUTPUT (SPIKE section 6, item 2): real recent sales carrying
    ask AND sold. Read from share/sales.csv rather than the comp universe, because comp
    rows are anonymous by design and this output needs an address you can go look at.

    The window counts back from the newest sale we HOLD, not from today -- the data ends
    a few days behind real time and measuring from today would quietly shrink it. Ranked
    by shape: size gap dominates, then beds, then baths.
    """
    p = ROOT / "share" / "sales.csv"
    if not p.exists(): return []
    rows, newest = [], ""
    for r in csv.DictReader(open(p)):
        d = (r.get("sold_date") or "")[:10]
        if d > newest: newest = d
        if r.get("town") != town or not d: continue
        try:
            sold, ask = float(r["sold_price"]), float(r["list_price"])
            sq, bd, ba = float(r["sqft"]), float(r["beds"]), float(r["baths"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (sold and ask and sq): continue
        rows.append((d, sq, bd, ba, {
            "address": r["address"], "sold_date": d,
            "ask": int(ask), "sold": int(sold),
            "gap_pct": round((sold - ask) / ask * 100, 1),
            "sqft": int(sq), "beds": bd, "baths": ba,
            "year_built": r.get("year_built") or None,
            "days_on_market": r.get("days_on_market") or None}))
    if not rows: return []

    y, m = int(newest[:4]), int(newest[5:7])
    m -= months
    cutoff = f"{y + (m - 1) // 12:04d}-{((m - 1) % 12) + 1:02d}-{newest[8:10]}"
    recent = [r for r in rows if r[0] >= cutoff] or rows

    # With no sqft and no beds/baths there is nothing to rank on, and the sort silently
    # degenerates into "the first three rows we happened to read" -- which then get
    # printed under the heading "comparable sales". Three arbitrary houses presented as
    # comparables is worse than none, so refuse instead. (Seen in the wild: a $315k, an
    # $891k and a $375k sale offered as comps for one listing.)
    if not sqft and beds is None and baths is None:
        return []

    def shape(r):
        _d, sq, bd, ba, _rec = r
        return ((abs(sq - sqft) / sqft if sqft else 0)
                + (abs(bd - beds) * 0.15 if beds is not None else 0)
                + (abs(ba - baths) * 0.10 if baths is not None else 0))

    recent.sort(key=shape)
    picked = [r[4] for r in recent[:k]]
    # Without sqft the ranking is beds/baths only, which is a much weaker claim to
    # "comparable". Say so on the row rather than letting it read as a size match.
    if not sqft:
        for p in picked:
            p["match_basis"] = "beds/baths only — this listing publishes no sqft"
    return picked


def main():
    subj = json.loads((RUN / "subject_blind.json").read_text())
    D = C.load()
    num = lambda v: float(v) if v not in (None, "", "None") else None

    sqft, lot = num(subj.get("sqft")), num(subj.get("lot_sqft"))
    beds, baths = num(subj.get("beds")), num(subj.get("baths"))
    built = num(subj.get("year_built"))
    fam = D["family"].get(subj.get("property_type", ""))

    anchor = C.comps(D, subj["town"], sqft, beds, baths, "idx",
                     lot if (lot and lot > 500) else None, fam,
                     int(built) if built else None)
    # comps() returns None outright when it has NO shape to match on -- no sqft, no lot,
    # no beds, no baths. sqft is missing on 71% of live listings, so this is ordinary,
    # not exotic. Turn it into an explicit refusal rather than an empty dict that the
    # next line will happily index into.
    if anchor is None:
        anchor = {"failed": True,
                  "reason": "no_shape_to_match_on",
                  "detail": "this listing publishes no sqft, lot, beds or baths, so "
                            "there is nothing to find comparable sales against"}
    if not anchor.get("failed"):
        anchor.pop("sales", None)          # keep the packet readable; §6 wants named comps

    lat, lon = num(subj.get("lat")), num(subj.get("lon"))
    # Look the tax rate up here rather than trusting the subject record to carry it --
    # the drop-a-link path builds its record from the live feed, which has no tax field,
    # and holding cost silently vanished on every scraped house.
    tax = subj.get("tax") or {}
    if not tax:
        tp = ROOT / "layers" / "tax" / "tax_by_town.csv"
        if tp.exists():
            for t in csv.DictReader(open(tp)):
                if t["town"] == subj["town"]:
                    tax = {"effective_rate_pct": num(t.get("effective_rate_pct")),
                           "town_avg_bill": num(t.get("avg_residential_tax"))}
    rate = tax.get("effective_rate_pct")
    hold = None
    if rate and not anchor.get("failed"):
        hold = {"annual_estimate": round(anchor["mid"] * rate / 100),
                "monthly_estimate": round(anchor["mid"] * rate / 100 / 12),
                "basis": f"{rate}% effective rate x our value estimate",
                "warning": "ESTIMATE ON AN ESTIMATE. Not this house's bill — the town's "
                           "effective rate applied to our own number. Verify on the listing."}

    ctx = {
        "subject": {k: subj.get(k) for k in
                    ("property_key", "address", "town", "beds", "baths", "sqft",
                     "lot_sqft", "year_built", "property_type", "garage", "ac_type")},
        "anchor": anchor,
        "comparables": recent_sales(subj["town"], beds, baths, sqft),
        "location": {"flood_zone": flood_zone(lat, lon),
                     "stores_miles": stores_near(lat, lon),
                     "transit": transit(subj["town"]),
                     "note": "flood and store distance are HOUSE-level (from this "
                             "listing's coordinates). Transit is town-level. None of "
                             "these may move the value range — see layers/README.md."},
        "holding_cost": hold,
    }
    (RUN / "context.json").write_text(json.dumps(ctx, indent=2))

    a = ctx["anchor"] or {"failed": True, "reason": "no anchor"}
    print(f"anchor   : " + ("REFUSED — " + a.get("reason", "")
          if a.get("failed") else
          f"${a['mid']:,.0f}  (${a['lo']:,.0f}–${a['hi']:,.0f})  n={a['n']} tier={a['tier']}"))
    if a and not a.get("failed"):
        flags = [k for k in ("degraded", "lotDropped", "eraDropped", "famDropped",
                             "thinFam", "borrowed") if a.get(k)]
        print(f"flags    : {', '.join(flags) if flags else 'none — clean comp set'}")
    print(f"comps    : " + (f"{len(ctx['comparables'])} recent sales with ask AND sold"
          if ctx["comparables"] else
          "none offered — no sqft/beds/baths to match on, so any pick would be arbitrary"))
    for c in ctx["comparables"]:
        print(f"           {c['address'][:28]:<28} {c['sold_date']}  ask ${c['ask']:>9,} "
              f"sold ${c['sold']:>9,}  {c['gap_pct']:+.1f}%")
    print(f"flood    : {ctx['location']['flood_zone'] or 'not in a mapped zone'}")
    print(f"stores   : " + ", ".join(f"{k} {v['miles']}mi" for k, v in
                                     ctx['location']['stores_miles'].items()) or "n/a")
    print(f"holding  : " + (f"~${hold['annual_estimate']:,}/yr (~${hold['monthly_estimate']:,}/mo) — ESTIMATE"
                            if hold else "n/a"))
    print(f"wrote    : {RUN}/context.json")


if __name__ == "__main__":
    main()
