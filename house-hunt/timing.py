#!/usr/bin/env python3
"""
Timing Househunting — a closing-runway planner.

The other half of the routine (match.py) finds houses. This answers the *when*:
given month-to-month rent with a landlord notice period and a target close
window, when does a winning offer need to be in, and when do we give notice?

It reads lead times straight off the hand-tracked comps (comps.json):
  - escrow         = days from under-contract (pending/UC) -> close
  - list_to_uc     = days from listed -> under-contract
and the couple's constraints from timing.json (notice period, target months),
with the price ceiling from criteria.json. Everything is a median over real
local closings, with the messy rows (typo dates, private sales) guarded out.

The key insight it surfaces: escrow (~38d) is SHORTER than a 60-day notice, so
giving notice the day you go under contract leaves the lease running a few weeks
past closing — a safe overlap, not a homelessness gap.

USAGE
  python3 timing.py [YYYY-MM-DD]          # prints the runway board
  (run from the routine folder; reads comps.json, timing.json, criteria.json)
"""

import datetime
import os
import sys

# match.py's main() is guarded by `if __name__ == "__main__"`, so importing it
# is side-effect-free. Reuse its date/median/json helpers rather than re-rolling.
from match import days_between, _median, load_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_REASONABLE_DAYS = 400   # intervals beyond this are data errors, not slow escrows

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ----- lead times from comps --------------------------------------------------

def _interval(start, end):
    """days_between with a sanity guard: drop negatives and absurd gaps (the
    known typo rows in comps.json). Returns None when unusable."""
    d = days_between(start, end)
    if d is None or d < 0 or d > MAX_REASONABLE_DAYS:
        return None
    return d


def lead_times(comps, overrides=None):
    """Median escrow (under-contract -> close) and list -> under-contract, from
    comps['within_budget']. Each metric filters its own Nones, so a row missing
    one date still contributes the other. overrides (from timing.json) win when
    set. Returns {escrow_days, list_to_uc_days, n_escrow, n_list_to_uc}."""
    overrides = overrides or {}
    rows = comps.get("within_budget", [])
    escrow = [d for r in rows
              if (d := _interval(r.get("pending_uc_date"), r.get("closed_date"))) is not None]
    to_uc = [d for r in rows
             if (d := _interval(r.get("listed_date"), r.get("pending_uc_date"))) is not None]
    esc = overrides.get("escrow_days")
    l2u = overrides.get("list_to_uc_days")
    return {
        "escrow_days": esc if esc is not None else _median(escrow),
        "list_to_uc_days": l2u if l2u is not None else _median(to_uc),
        "n_escrow": len(escrow),
        "n_list_to_uc": len(to_uc),
    }


# ----- seasonality (directional; small sample) --------------------------------

_SEASONS = {  # close-month -> season label
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}


def _close_month(rec):
    cd = rec.get("closed_date")
    if not cd:
        return None
    try:
        return int(cd.split("-")[1])
    except (IndexError, ValueError):
        return None


def seasonality(comps, price_max=None):
    """Bucket within-budget comps by the SEASON they closed in and report a
    directional sold-vs-ask read + pace. Deliberately direction + sample size,
    not precise medians — n per season is tiny. Also summarizes the
    out_of_budget over-ask cluster, flagging it as an above-budget tier."""
    buckets = {}
    for r in comps.get("within_budget", []):
        m = _close_month(r)
        ask, close = r.get("asking_price"), r.get("closed_amount")
        if m is None or not ask or not close:
            continue
        s = _SEASONS[m]
        b = buckets.setdefault(s, {"ratios": [], "doms": []})
        b["ratios"].append(close / ask)
        dom = _interval(r.get("listed_date"), r.get("closed_date"))
        if dom is not None:
            b["doms"].append(dom)

    seasons = {}
    for s, b in buckets.items():
        med = _median(b["ratios"])
        seasons[s] = {
            "n": len(b["ratios"]),
            "median_vs_ask": med,
            "direction": "over ask" if med and med > 1 else "under ask",
            "median_dom": _median(b["doms"]),
        }

    oob = comps.get("out_of_budget", [])
    prem = [r["over_asking"] for r in oob if r.get("over_asking") is not None]
    closed = [r["closed_amount"] for r in oob if r.get("closed_amount")]
    frenzy = {
        "n": len(prem),
        "median_premium": _median(prem),
        "median_close": _median(closed),
        "above_budget": bool(price_max and closed and _median(closed) > price_max),
        "price_max": price_max,
    }
    return {"seasons": seasons, "frenzy": frenzy}


# ----- runway: back-plan from a target close date -----------------------------

def _add_days(d, n):
    return d + datetime.timedelta(days=int(round(n)))


def _last_of_month(year, month):
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def runway(close_date, escrow_days, notice_days):
    """Back-plan one target close date. The accepted offer (under-contract) must
    land ~escrow_days before close. Notice fires no earlier than under-contract
    (you don't tell the landlord before you're actually in contract), so the
    lease ends notice_days after UC and overlaps closing by (notice - escrow)."""
    uc_by = _add_days(close_date, -escrow_days)
    notice_by = uc_by                      # give notice when you go under contract
    lease_ends = _add_days(notice_by, notice_days)
    overlap_days = (lease_ends - close_date).days
    return {
        "close_date": close_date,
        "offer_accepted_by": uc_by,
        "give_notice_by": notice_by,
        "lease_ends": lease_ends,
        "overlap_days": overlap_days,
    }


def plan(comps, cfg, criteria, today):
    """Build the runway for each candidate close month, dropping any whose
    offer-by date has already passed (no point planning the past)."""
    lt = lead_times(comps, cfg.get("lead_time_overrides"))
    escrow = lt["escrow_days"]
    notice = cfg.get("notice_period_days", 60)
    price_max = (criteria or {}).get("price", {}).get("max")
    tc = cfg.get("target_close", {})
    year = tc.get("year", today.year)

    rows = []
    for m in tc.get("months", []):
        close_date = _last_of_month(year, m)
        r = runway(close_date, escrow, notice)
        r["month"] = m
        r["past"] = r["offer_accepted_by"] < today
        rows.append(r)
    return {
        "lead_times": lt, "notice": notice, "price_max": price_max,
        "rows": rows, "seasonality": seasonality(comps, price_max),
    }


# ----- render -----------------------------------------------------------------

def _fmt(d):
    return f"{_MONTHS[d.month]} {d.day}, {d.year}"


def render(p, today):
    lt = p["lead_times"]
    escrow = lt["escrow_days"]
    notice = p["notice"]
    L = [f"⏱  TIMING HOUSEHUNTING — runway to close in {today.year}   (as of {today.isoformat()})"]
    if escrow is None:
        return "\n".join(L + ["", "  (not enough dated comps to estimate escrow yet)"])
    L.append(f"   from comps: escrow (under-contract → close) ≈ {escrow:.0f} days  (n={lt['n_escrow']})")
    if p["price_max"]:
        L.append(f"   budget ceiling (criteria.json): ${p['price_max']:,.0f}")
    L.append("")
    L.append("  TO CLOSE BY        OFFER ACCEPTED BY      GIVE LANDLORD NOTICE    LEASE OVERLAP")
    live = [r for r in p["rows"] if not r["past"]]
    for r in (live or p["rows"]):
        label = f"end of {_MONTHS[r['month']]} {r['close_date'].year}"
        overlap = r["overlap_days"]
        if overlap > 0:
            ov = f"~{overlap}d past close"
        elif overlap == 0:
            ov = "ends at close"
        else:
            ov = f"{-overlap}d gap ⚠"
        past = "  (offer date passed)" if r["past"] else ""
        L.append(f"    {label:<16} {_fmt(r['offer_accepted_by']):<22} "
                 f"at UC (~{_MONTHS[r['give_notice_by'].month]} {r['give_notice_by'].day}){'':<6} {ov}{past}")
    if not live:
        L.append("    (every target month's offer date has already passed — edit target_close in timing.json)")
    L.append("")

    # the notice tradeoff, computed (not hard-coded). Round escrow to match the
    # whole-day overlap shown in the table above.
    gap = notice - round(escrow)
    L.append("  THE NOTICE CALL")
    if gap > 0:
        L.append(f"    Escrow (~{escrow:.0f}d) is shorter than your {notice}-day notice. Give notice the day")
        L.append(f"    you go under contract → lease ends ~{gap} days AFTER closing. Safe buffer,")
        L.append(f"    ~{gap // 7} wks of double housing cost. (To zero the overlap you'd notice")
        L.append("    ~before UC — too risky before you're actually under contract.)")
    else:
        L.append(f"    Escrow (~{escrow:.0f}d) is LONGER than your {notice}-day notice — give notice")
        L.append(f"    ~{-gap} days AFTER going under contract to line the lease end up with closing.")
    L.append("")

    # seasonality
    L.append("  SEASON YOU CLOSE IN (directional — small sample)")
    seasons = p["seasonality"]["seasons"]
    order = ["Winter", "Spring", "Summer", "Fall"]
    for s in order:
        st = seasons.get(s)
        if not st:
            continue
        vs = f"{(st['median_vs_ask'] - 1) * 100:+.0f}% vs ask" if st["median_vs_ask"] else "—"
        dom = f", ~{st['median_dom']:.0f}d on mkt" if st["median_dom"] is not None else ""
        L.append(f"    {s:<7}: closed {st['direction']} ({vs}{dom})  (n={st['n']})")
    fr = p["seasonality"]["frenzy"]
    if fr["n"]:
        tier = ""
        if fr["above_budget"]:
            tier = (f"  ⚠ these closed ~${fr['median_close']:,.0f} — ABOVE your "
                    f"${fr['price_max']:,.0f} budget, so your tier may run cooler")
        L.append(f"    Spring frenzy: {fr['n']} sales over ask, median +${fr['median_premium']:,.0f} over.{tier}")
    L.append("")
    L.append("  notes: escrow from clean comps; private sales & typo-dated rows excluded.")
    L.append("         \"offer accepted by\" = close date − escrow; time to FIND a winning")
    L.append("         house is on top of this and varies — start looking well before these dates.")
    return "\n".join(L)


def next_milestone(today=None):
    """One-line runway reminder for match.py's daily board. Returns the soonest
    still-future 'have an accepted offer by' date across the target months, or
    None if unavailable. Kept import-safe and exception-free for the caller."""
    try:
        today = today or datetime.date.today()
        if isinstance(today, str):           # match.py passes an isoformat string
            today = datetime.date.fromisoformat(today)
        comps = load_json(os.path.join(BASE_DIR, "comps.json"), None)
        cfg = load_json(os.path.join(BASE_DIR, "timing.json"), None)
        criteria = load_json(os.path.join(BASE_DIR, "criteria.json"), {})
        if not comps or not cfg:
            return None
        p = plan(comps, cfg, criteria, today)
        future = sorted((r for r in p["rows"] if not r["past"]),
                        key=lambda r: r["offer_accepted_by"])
        if not future:
            return None
        r = future[0]
        return (f"⏱ To close by {_MONTHS[r['month']]} {r['close_date'].year}, have an accepted "
                f"offer by ~{_fmt(r['offer_accepted_by'])} (give landlord notice then).")
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    today = datetime.date.fromisoformat(args[0]) if args else datetime.date.today()
    comps = load_json(os.path.join(BASE_DIR, "comps.json"), None)
    if comps is None:
        print("missing comps.json", file=sys.stderr)
        sys.exit(2)
    cfg = load_json(os.path.join(BASE_DIR, "timing.json"), None)
    if cfg is None:
        print("missing timing.json", file=sys.stderr)
        sys.exit(2)
    criteria = load_json(os.path.join(BASE_DIR, "criteria.json"), {})
    print(render(plan(comps, cfg, criteria, today), today))


if __name__ == "__main__":
    main()
