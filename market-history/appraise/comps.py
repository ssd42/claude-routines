"""The comp engine, in Python — a PORT of offer/engine.js comps().

WHY THIS FILE EXISTS AND WHY IT IS A LIABILITY
----------------------------------------------
engine.js is the one true engine: analyser.html, market.html and backtest.html all call
it, and its header says the worst bug this tool could have is two pages disagreeing. This
file makes a fourth caller that CANNOT share that code, because the skill runs in Python
and there is no node on this machine.

So this is a deliberate, known duplication. The mitigation is `--selftest`, which prices
houses whose engine.js answer we already know from the backtest and fails loudly if this
port has drifted. Run it after ANY change to engine.js. If it fails, this file is wrong
until proven otherwise — engine.js is the source of truth, never this.

WHAT IS DELIBERATELY NOT PORTED
-------------------------------
compsBorrow() — the "top up from neighbouring towns" rung. It fires on ~11% of houses and
is the most complex part of the engine (distance weights, per-band re-anchoring). Rather
than port it half-right, this returns `failed: insufficient_local_evidence` and the skill
declines to give a range, exactly as SPIKE-appraiser.md §15 Q5 argues it should. Better a
loud refusal than a quiet approximation of a rung the engine spent three revisions fixing.

WHAT THAT COSTS, MEASURED
-------------------------
Against the 2026 graded set (1,384 houses), this port refuses **186 of them, 13.4%**:
154 (11.1%) where engine.js borrows from neighbouring towns, plus 32 (2.3%) that
engine.js refuses as well.

That 13.4% is NOT evenly spread. Borrowing concentrates in small and expensive towns --
Millburn has 3 own-town comps at 1,632 sqft -- so for any given town the refusal rate can
run far above the global figure. If the houses you care about sit in a thin town, this
port declines more often than 13% suggests, and the fix is to port compsBorrow, not to
loosen anything here.
"""
import json, re, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "offer" / "data.js"

TIERS = [
    {"id": "t1", "tag": "sqft ±15% · beds ±1 · baths ±1",  "sq": .15, "bd": 1,  "ba": 1},
    {"id": "t2", "tag": "sqft ±25% · beds ±1 · baths any", "sq": .25, "bd": 1,  "ba": 99},
    {"id": "t3", "tag": "sqft ±25% · any beds or baths",   "sq": .25, "bd": 99, "ba": 99},
]
LOT_TOLS      = [0.30, 0.50]
ERA_TOLS      = [15, 30]
LOT_ONLY_TOLS = [0.20, 0.35, 0.50]
THIN_FAM      = 6
# comp row: [town, sqft, beds, baths, sold, pct, saleYear, lot, month, fam, built]
TOWN, SQ, BD, BA, SOLD, PCT, YR, LOT, MON, FAM, BUILT = range(11)


def load():
    s = DATA.read_text()
    return json.loads(s[s.index("window.OFFER_DATA =") + 19:].rstrip().rstrip(";"))


def _quart(vals):
    """engine.js quart(): [median, s[n>>2], s[(3n)>>2]] — NOT interpolated percentiles.
    Reproduced exactly, including the integer-shift indexing, because matching the page
    matters more than being statistically tidier than the page."""
    s = sorted(vals)
    n = len(s)
    med = st.median(s)
    return med, s[n >> 2], s[(3 * n) >> 2]


def comps(D, town, sqft, beds, baths, mode="idx", lot=None, fam=None, built=None):
    if not sqft and not lot and beds is None and baths is None:
        return None
    ix = D["townIndex"].get(town) or D["priceIndex"]
    THIN = D["thin"]
    want_fam = fam or None

    def mult(c):
        return (ix.get(str(c[YR]), 1.0) if mode == "idx" else 1.0)

    def val_of(c):
        return (c[SOLD] / c[SQ]) * mult(c) * sqft if sqft else c[SOLD] * mult(c)

    def ok(c, t, lt, et):
        if c[TOWN] != town: return False
        if mode == "recent" and str(c[YR]) not in D["recentYears"]: return False
        if want_fam and c[FAM] != want_fam: return False
        if beds  is not None and abs(c[BD] - beds)  > t["bd"]: return False
        if baths is not None and abs(c[BA] - baths) > t["ba"]: return False
        if sqft and abs(c[SQ] - sqft) / sqft > t["sq"]: return False
        if lt is not None and not (c[LOT] and abs(c[LOT] - lot) / lot <= lt): return False
        if et is not None and built and not (c[BUILT] and abs(c[BUILT] - built) <= et):
            return False
        return True

    def build(hit, t, lot_tol, era_tol):
        mid, p25, p75 = _quart([val_of(c) for c in hit])
        return {
            "tier": t["id"], "tierTag": t["tag"], "n": len(hit),
            "mid": mid, "lo": p25, "hi": p75,
            "ppsf": st.median([(c[SOLD] / c[SQ]) * mult(c) for c in hit]) if sqft else None,
            "eraTol": era_tol, "eraDropped": bool(built) and era_tol is None,
            "degraded": t["id"] != "t1",
            "lotTol": lot_tol, "lotDropped": bool(lot) and lot_tol is None,
            "bySize": bool(sqft), "fam": want_fam,
            "famDropped": bool(fam) and not want_fam,
            "borrowed": mode == "idx" and town not in D["townIndex"],
            "sales": [{"sqft": c[SQ], "beds": c[BD], "baths": c[BA], "year": c[YR],
                       "month": c[MON], "lot": c[LOT], "built": c[BUILT],
                       "sold": c[SOLD], "vsAsk": c[PCT], "val": val_of(c)} for c in hit],
        }

    def ladder(min_n, et):
        if not sqft and lot:
            for lt in LOT_ONLY_TOLS:
                for t in [{"id": "L1", "tag": "lot-matched · beds ±0 · baths ±0.5", "bd": 0, "ba": .5},
                          {"id": "L2", "tag": "lot-matched · beds ±1 · baths ±1",   "bd": 1, "ba": 1}]:
                    hit = [c for c in D["comps"] if ok(c, t, lt, et)]
                    if len(hit) >= min_n:
                        r = build(hit, t, lt, et); r["noSize"] = True; return r
            return None
        if not sqft:
            for t in [{"id": "b1", "tag": "beds ±0 · baths ±0.5", "bd": 0, "ba": .5},
                      {"id": "b2", "tag": "beds ±1 · baths ±1",   "bd": 1, "ba": 1}]:
                hit = [c for c in D["comps"]
                       if c[TOWN] == town
                       and (mode != "recent" or str(c[YR]) in D["recentYears"])
                       and (not want_fam or c[FAM] == want_fam)
                       and (beds  is None or abs(c[BD] - beds)  <= t["bd"])
                       and (baths is None or abs(c[BA] - baths) <= t["ba"])
                       and (et is None or not built or (c[BUILT] and abs(c[BUILT] - built) <= et))]
                if len(hit) >= min_n:
                    r = build(hit, t, None, et); r["noSize"] = True; return r
            return None
        if lot:
            for lt in LOT_TOLS:
                for t in TIERS:
                    hit = [c for c in D["comps"] if ok(c, t, lt, et)]
                    if len(hit) >= min_n: return build(hit, t, lt, et)
        for t in TIERS:
            hit = [c for c in D["comps"] if ok(c, t, None, et)]
            if len(hit) >= min_n: return build(hit, t, None, et)
        return None

    r = None
    if built:
        for et in ERA_TOLS:
            r = ladder(THIN, et)
            if r: break
    if not r: r = ladder(THIN, None)
    if r: return r

    # engine.js borrows from neighbours here. This port does not — see the module docstring.
    r = ladder(THIN_FAM, None)
    if r: r["thinFam"] = True; return r
    if want_fam:
        want_fam = None
        r = ladder(THIN, None)
        if r: return r
    return {"failed": True, "reason": "insufficient_local_evidence"}


# ── selftest ───────────────────────────────────────────────────────────────────
# Ground truth captured 2026-07-21 from the engine.js measurement harness. Every case is
# run the way backtest.html runs it: subject removed from its own comp set, mode "idx",
# lot passed only when > 500, fam from D.family[property_type], built = year_built.
#
# Between them these seven exercise era<=15, era<=30, era-dropped, tiers t1/t2/t3, lot
# tolerances 0.3/0.5/none, all three families, and the thinFam / borrow / pooled
# fallbacks. If you change engine.js, run this. A green run means the port still agrees;
# a red one means THIS FILE is wrong until proven otherwise.
#
# addr, town, sqft, beds, baths, lot, built, fam, sold, expect_mid, n, tier, eraTol, rung
SELFTEST = [
    ("53 Ponds Cir",      "Wayne",       3500, 4.0, 3.5, None,  1985, "attached",  625000,
        829456.17,  6, "t2", None, "thinFam"),
    ("33 Menlo Ave",      "Metuchen",    2007, 4.0, 2.0, 6098,  1948, "house",     515000,
        920248.92, 20, "t2", 15,   "era"),
    ("21 Robertson Rd",   "West Orange", 1730, 3.0, 3.0, 5001,  1931, "house",     438000,
        756875.00, 17, "t2", 15,   "era"),
    # engine.js BORROWS here (Millburn tops up from Maplewood/Summit/Springfield/South
    # Orange). This port does not implement borrow, so the correct behaviour is a refusal.
    ("96 Rector St",      "Millburn",    1632, 3.0, 2.5, 3920,  1910, "house",     651888,
        None,      None, None, None, "REFUSE"),
    ("10 Smith Manor Blvd Unit 121", "West Orange", 2207, 3.0, 3.0, None, 1993, "attached", 349000,
        705093.51, 31, "t1", 15,   "era"),
    ("11 Cleveland St",   "Morristown",  1183, 4.0, 3.5, 5663,  1906, "multi",     935000,
        622943.96, 26, "t3", None, "pooled"),
    ("3 Brook Way",       "West Orange", 3179, 5.0, 4.0, 20473, 1927, "house",    1450000,
        1008267.22, 24, "t2", 30,  "era"),
]


def _rung(r):
    if r.get("failed"):     return "REFUSE"
    if r.get("thinFam"):    return "thinFam"
    if r.get("famDropped"): return "pooled"
    if r.get("eraTol") is not None: return "era"
    return "no-era"


def _selftest():
    D = load()
    all_comps = D["comps"]
    bad = 0
    print(f"{'house':<32}{'expect mid':>12}{'got':>12}{'n':>5}{'tier':>6}{'era':>5}{'rung':>9}")
    print("-" * 84)
    for (addr, town, sqft, bd, ba, lot, built, fam, sold,
         exp_mid, exp_n, exp_tier, exp_era, exp_rung) in SELFTEST:
        drop = {i for i, c in enumerate(all_comps)
                if c[TOWN] == town and c[SQ] == sqft and c[BD] == bd
                and c[BA] == ba and c[SOLD] == sold}
        D["comps"] = [c for i, c in enumerate(all_comps) if i not in drop]
        r = comps(D, town, sqft, bd, ba, "idx", lot, fam, built)
        D["comps"] = all_comps

        rung = _rung(r)
        if exp_rung == "REFUSE":
            ok = bool(r.get("failed"))
            print(f"{addr[:31]:<32}{'(refuse)':>12}{('refused' if ok else 'ANSWERED'):>12}"
                  f"{'':>5}{'':>6}{'':>5}{rung:>9}  {'' if ok else '<-- SHOULD HAVE REFUSED'}")
            bad += 0 if ok else 1
            continue
        if r.get("failed"):
            print(f"{addr[:31]:<32}{exp_mid:>12,.0f}{'REFUSED':>12}"
                  f"{'':>5}{'':>6}{'':>5}{rung:>9}  <-- UNEXPECTED REFUSAL")
            bad += 1
            continue

        drift = abs(r["mid"] - exp_mid) / exp_mid * 100
        ok = (drift < 0.05 and r["n"] == exp_n and r["tier"] == exp_tier
              and r["eraTol"] == exp_era and rung == exp_rung)
        print(f"{addr[:31]:<32}{exp_mid:>12,.0f}{r['mid']:>12,.0f}{r['n']:>5}"
              f"{r['tier']:>6}{str(r['eraTol']):>5}{rung:>9}  "
              f"{'' if ok else '<-- DRIFTED'}")
        bad += 0 if ok else 1

    print("-" * 84)
    print("PASS - this port still matches engine.js" if not bad else
          f"FAIL - {bad} case(s) drifted. engine.js is the source of truth; fix THIS file.")
    return 0 if not bad else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
