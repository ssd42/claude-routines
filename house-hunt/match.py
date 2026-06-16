#!/usr/bin/env python3
"""
Daily house-hunt: reconcile multi-source listings, score them against your
criteria, diff against what we've already seen, and track watchlisted houses
from list price to sold price.

This is the deterministic half of the routine (like bracket-challenge/score.py).
The *fetching* is done by the scheduled agent, which writes one file per source
into raw/ ; this script does everything after that.

PIPELINE
  raw/<source>.json  (one per source in sources.json)
     -> reconcile by normalized (address + zip), consensus on numbers
     -> score vs criteria.json   -> bucket: match | close | exclude
     -> diff vs seen.json        -> NEW today | THIS WEEK (still-active prior matches)
                                 -> CHANGES: price drops, went-pending, back-on-market
     -> archive solds + comps    -> per-zip median $/sqft, sold/list ratio, days-on-market
     -> annotate each listing     -> days-on-market + "vs area" pricing tag
     -> update watchlist.json    -> capture list->sold price over months
     -> print board ; write history/<date>.json ; update seen.json + watchlist.json

RAW INPUT SHAPE  (what the agent must produce per source, raw/<key>.json)
  {
    "source": "redfin",
    "fetched": "2026-06-10",
    "listings": [
      { "address": "123 Maple St", "zip": "00000", "city": "Springfield",
        "neighborhood": "Maplewood", "price": 749000, "beds": 3, "baths": 2,
        "sqft": 1600, "property_type": "Single Family", "status": "active",
        "sold_price": null, "url": "https://...", "photo_url": "https://...",
        "listed_date": "2026-06-08", "tags": ["garage", "renovated kitchen"] }
    ]
  }
  status is one of: active | pending | sold. tags is free text we match
  nice_to_haves / dealbreakers against (substring, case-insensitive).
  photo_url is the lead photo (used for the Slack cards); optional.

USAGE
  python3 match.py [YYYY-MM-DD] --board    # THE canonical Slack board — post this
                                           # output VERBATIM (cemented headers,
                                           # every house linked). Used by run.sh.
  python3 match.py [YYYY-MM-DD]            # prints the ASCII board
  python3 match.py [YYYY-MM-DD] --md       # prints the Slack-markdown digest
  python3 match.py [YYYY-MM-DD] --blocks   # prints Slack Block Kit JSON (photo
                                           # cards + View-listing buttons)
  python3 match.py [YYYY-MM-DD] --post     # POSTs the Block Kit digest to the
                                           # webhook in $HOUSE_HUNT_SLACK_WEBHOOK
  (run from the routine folder; reads criteria.json, sources.json, raw/*.json)
"""

import datetime
import glob
import json
import os
import re
import sys
import urllib.request

# Optional: the Timing Househunting planner (timing.py) adds a one-line
# closing-runway reminder to the board. Soft-imported so match.py still runs if
# timing.py / timing.json are absent.
try:
    from timing import next_milestone
except Exception:
    next_milestone = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_ABBR = {
    r"\bst\b": "street", r"\bave\b": "avenue", r"\brd\b": "road",
    r"\bdr\b": "drive", r"\bln\b": "lane", r"\bct\b": "court",
    r"\bblvd\b": "boulevard", r"\bpl\b": "place", r"\bter\b": "terrace",
    r"\bcir\b": "circle", r"\bhwy\b": "highway", r"\bpkwy\b": "parkway",
    r"\bapt\b": "", r"\bunit\b": "", r"\b#\b": "",
}


def normalize_address(addr):
    """Lowercase, strip punctuation, expand common abbreviations, collapse
    whitespace -> a stable key for matching the SAME house across sources."""
    s = (addr or "").lower()
    s = re.sub(r"[.,#]", " ", s)
    for pat, repl in _ABBR.items():
        s = re.sub(pat, repl, s)
    return re.sub(r"\s+", " ", s).strip()


def listing_key(address, zip_code):
    return f"{normalize_address(address)}|{(zip_code or '').strip()}"


# ----- reconcile -------------------------------------------------------------

def _consensus_number(values_by_source, trust):
    """values_by_source: {source_key: number|None}. Return (value, discrepancy).
    Rule (see sources.json): value agreed by >=2 sources wins; else the
    highest-trust source's value, flagged as a discrepancy."""
    vals = {s: v for s, v in values_by_source.items() if v is not None}
    if not vals:
        return None, False
    if len(set(vals.values())) == 1:
        return next(iter(vals.values())), False  # one source, or all agree
    counts = {}
    for v in vals.values():
        counts[v] = counts.get(v, 0) + 1
    agreed = [v for v, c in counts.items() if c >= 2]
    if agreed:
        # if multiple values each have >=2 (rare w/ 3 sources), pick the most common
        best = max(agreed, key=lambda v: counts[v])
        discrepancy = len(set(vals.values())) > 1
        return best, discrepancy
    # no agreement -> highest trust source that has a value
    src = max(vals.keys(), key=lambda s: trust.get(s, 0))
    return vals[src], True


def reconcile(raw_by_source, sources_cfg):
    """Merge per-source raw listings into one list keyed by address+zip.
    Numeric fields go through 2-of-3 consensus; text fields union/first-seen.
    Each merged listing carries `sources` (who saw it) and `discrepancies`."""
    trust = {s["key"]: s.get("trust", 0) for s in sources_cfg["sources"]}
    merged = {}
    for src_key, payload in raw_by_source.items():
        for l in payload.get("listings", []):
            k = listing_key(l.get("address"), l.get("zip"))
            slot = merged.setdefault(k, {
                "key": k, "address": l.get("address"), "zip": l.get("zip"),
                "city": l.get("city"), "neighborhood": l.get("neighborhood"),
                "url": l.get("url"), "listed_date": l.get("listed_date"),
                "tags": set(), "sources": [], "_nums": {},
            })
            slot["sources"].append(src_key)
            slot["tags"].update(t.lower() for t in (l.get("tags") or []))
            # prefer any non-null text field we encounter
            for f in ("url", "neighborhood", "listed_date", "city", "property_type",
                      "photo_url", "open_house", "sold_date"):
                if not slot.get(f) and l.get(f):
                    slot[f] = l.get(f)
            for f in ("price", "beds", "baths", "sqft", "sold_price"):
                slot["_nums"].setdefault(f, {})[src_key] = l.get(f)
            # status: worst-case freshness — sold/pending beats active if any source says so
            slot["status"] = _merge_status(slot.get("status"), l.get("status"))

    out = []
    for slot in merged.values():
        listing = {k: v for k, v in slot.items() if k not in ("_nums", "tags")}
        listing["tags"] = sorted(slot["tags"])
        listing["discrepancies"] = []
        for f, by_src in slot["_nums"].items():
            val, disc = _consensus_number(by_src, trust)
            listing[f] = val
            if disc:
                listing["discrepancies"].append(
                    {"field": f, "values": {s: v for s, v in by_src.items() if v is not None}})
        out.append(listing)
    return out


_STATUS_RANK = {"active": 0, "pending": 1, "sold": 2}


def _merge_status(a, b):
    if not a:
        return b
    if not b:
        return a
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


# ----- scoring ---------------------------------------------------------------

def in_target_area(listing, criteria):
    zips = {z for n in criteria["neighborhoods"] for z in n.get("zips", [])}
    if zips and listing.get("zip") in zips:
        return True
    names = {n["name"].lower() for n in criteria["neighborhoods"]}
    return (listing.get("neighborhood") or "").lower() in names


def score(listing, criteria):
    """Return (bucket, sort_score, reasons).
    bucket: 'match' (meets all hard rules), 'close' (bends a rule within
    relax tolerance), or 'exclude'. reasons explains a 'close' verdict."""
    tags = " ".join(listing.get("tags", []))
    if any(db.lower() in tags for db in criteria.get("dealbreakers", [])):
        return "exclude", 0, ["dealbreaker"]
    if not in_target_area(listing, criteria):
        return "exclude", 0, ["outside target neighborhoods"]

    hard, relax = criteria["hard"], criteria.get("relax", {})
    price_max = criteria["price"].get("max")
    price_min = criteria["price"].get("min")
    price = listing.get("price")
    reasons, hard_fail = [], False

    # price ceiling (relaxable)
    if price_max and price is not None and price > price_max:
        over_pct = (price - price_max) / price_max
        if over_pct <= relax.get("price_over_pct", 0):
            reasons.append(f"${(price - price_max):,.0f} over budget")
        else:
            hard_fail = True
    if price_min and price is not None and price < price_min:
        hard_fail = True  # under floor = usually a data issue / not comparable

    # beds / baths / sqft (relaxable downward)
    for field, hard_key, relax_key, kind in [
        ("beds", "beds_min", "beds_under", "count"),
        ("baths", "baths_min", "baths_under", "count"),
        ("sqft", "sqft_min", "sqft_under_pct", "pct"),
    ]:
        need = hard.get(hard_key)
        have = listing.get(field)
        if need and have is not None and have < need:
            if kind == "count":
                if (need - have) <= relax.get(relax_key, 0):
                    reasons.append(f"{need - have} {field} under")
                else:
                    hard_fail = True
            else:  # pct
                under_pct = (need - have) / need
                if under_pct <= relax.get(relax_key, 0):
                    reasons.append(f"{need - have:,.0f} sqft under")
                else:
                    hard_fail = True

    ptype = (listing.get("property_type") or "").lower()
    ptypes = [p.lower() for p in hard.get("property_types", [])]
    if ptypes and ptype and ptype not in ptypes:
        hard_fail = True  # only excludes when the type is KNOWN and wrong

    nice = sum(1 for n in criteria.get("nice_to_haves", []) if n.lower() in tags)
    if hard_fail:
        return "exclude", nice, reasons
    return ("close" if reasons else "match"), nice, reasons


# ----- state: seen.json + diff ----------------------------------------------

def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def diff_seen(scored, seen, today, window=7):
    """Bucket listings into new-today vs this-week, detect price/status CHANGES
    against the prior snapshot, and update seen. `scored` is a list of
    (listing, bucket, sort_score, reasons). Returns (new_today, this_week, alerts);
    each alert is (listing, message)."""
    listings = seen.setdefault("listings", {})
    today_d = datetime.date.fromisoformat(today)
    new_today, this_week, alerts = [], [], []

    def _facts(listing):
        # Static descriptors persisted on the seen record so seen.json is
        # analyzable on its own (no need to re-join every history/ snapshot).
        return {f: listing.get(f) for f in (
            "address", "zip", "city", "neighborhood", "url", "property_type",
            "beds", "baths", "sqft", "listed_date")}

    for entry in scored:
        listing = entry[0]
        k = listing["key"]
        rec = listings.get(k)
        new_price, new_status = listing.get("price"), listing.get("status")
        if rec is None:
            listings[k] = {**_facts(listing), "first_seen": today, "last_seen": today,
                           "status": new_status, "last_price": new_price,
                           "price_history": [{"date": today, "price": new_price}]}
            new_today.append(entry)
            continue

        # --- detect changes BEFORE overwriting the prior record ---
        old_price, old_status = rec.get("last_price"), rec.get("status")
        if old_price and new_price and new_price < old_price:
            drop = old_price - new_price
            pct = drop / old_price * 100
            alerts.append((listing, f"🔻 price ${new_price:,.0f}  (−${drop:,.0f}, −{pct:.0f}%)"))
        elif old_price and new_price and new_price > old_price:
            alerts.append((listing, f"🔺 price ${new_price:,.0f}  (+${new_price - old_price:,.0f})"))
        if old_status == "active" and new_status == "pending":
            alerts.append((listing, "⏳ went pending"))
        elif old_status in ("pending", "contingent") and new_status == "active":
            alerts.append((listing, "↩️ back on market"))

        first = datetime.date.fromisoformat(rec["first_seen"])
        # backfill static facts onto older thin records; refresh any that filled in
        for f, v in _facts(listing).items():
            if v is not None and rec.get(f) is None:
                rec[f] = v
        if new_price is not None and new_price != rec.get("last_price"):
            rec.setdefault("price_history", []).append({"date": today, "price": new_price})
        rec["last_seen"] = today
        rec["status"] = new_status
        rec["last_price"] = new_price
        if (today_d - first).days <= window:
            this_week.append(entry)
    return new_today, this_week, alerts


# ----- sold archive + area comps (P1) ---------------------------------------

def _median(nums):
    s = sorted(n for n in nums if n is not None)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def days_between(start, end):
    if not start or not end:
        return None
    try:
        return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
    except ValueError:
        return None


def record_solds(merged, seen, today):
    """Archive any listing now marked sold into seen['sold'] (keyed by listing,
    so re-runs update rather than duplicate). Feeds the area comps. Returns a
    list of (listing, message) for the CHANGES section."""
    archive = seen.setdefault("sold", {})
    seen_listings = seen.get("listings", {})
    events = []
    for listing in merged:
        if listing.get("status") != "sold" or not listing.get("sold_price"):
            continue
        k = listing["key"]
        if k in archive:
            continue  # already recorded
        rec = seen_listings.get(k, {})
        list_price = rec.get("last_price") or listing.get("price")
        start = listing.get("listed_date") or rec.get("first_seen")
        # prefer the ACTUAL sale date from the source; fall back to today only if
        # the feed didn't supply one (so the $/sqft trend reflects real timing).
        sold_date = listing.get("sold_date") or today
        archive[k] = {
            "zip": listing.get("zip"), "sold_price": listing.get("sold_price"),
            "list_price": list_price, "sqft": listing.get("sqft"),
            "dom": days_between(start, sold_date), "sold_date": sold_date,
        }
        # Only a CHANGE if we'd actually shown this house before; bulk comps
        # we never tracked just seed the market stats silently.
        if k in seen_listings:
            sp = listing.get("sold_price")
            ratio = f" ({sp / list_price * 100 - 100:+.0f}% vs list)" if list_price else ""
            events.append((listing, f"✅ sold ${sp:,.0f}{ratio}"))
    return events


def area_stats(seen):
    """Per-zip market comps from the sold archive: median sold $/sqft, median
    sold-vs-list ratio, median days-on-market, and sample size."""
    by_zip = {}
    for rec in seen.get("sold", {}).values():
        by_zip.setdefault(rec.get("zip"), []).append(rec)
    stats = {}
    for z, recs in by_zip.items():
        ppsf = [r["sold_price"] / r["sqft"] for r in recs if r.get("sqft") and r.get("sold_price")]
        ratio = [r["sold_price"] / r["list_price"] for r in recs if r.get("list_price") and r.get("sold_price")]
        stats[z] = {
            "n": len(recs),
            "median_ppsf": _median(ppsf),
            "median_ratio": _median(ratio),
            "median_dom": _median([r.get("dom") for r in recs]),
            "ppsf_trend": _ppsf_trend(recs),
        }
    return stats


def _ppsf_trend(recs):
    """Direction of $/sqft over the comp window: split sold comps by sale date
    into older vs recent halves, return the % change in median $/sqft (recent
    vs older). None if too few dated comps to be meaningful."""
    dated = [(r["sold_date"], r["sold_price"] / r["sqft"]) for r in recs
             if r.get("sold_date") and r.get("sqft") and r.get("sold_price")]
    if len(dated) < 6:
        return None  # not enough signal to call a direction
    dated.sort()
    mid = len(dated) // 2
    older = _median([p for _, p in dated[:mid]])
    recent = _median([p for _, p in dated[mid:]])
    if not older or not recent or len(set(d for d, _ in dated)) < 2:
        return None  # all same date (e.g. undated feed) -> no real trend
    return (recent - older) / older * 100


def annotate(listing, seen, stats, today):
    """Attach true days-on-market (_dom, from listed_date only) and a numeric
    "vs area" pricing delta (_vs_area, % vs median sold $/sqft) to a listing."""
    listing["_dom"] = days_between(listing.get("listed_date"), today)
    listing["_vs_area"] = None
    z = stats.get(listing.get("zip"))
    price, sqft = listing.get("price"), listing.get("sqft")
    if z and z.get("median_ppsf") and price and sqft:
        pct = (price / sqft - z["median_ppsf"]) / z["median_ppsf"] * 100
        if abs(pct) >= 3:  # ignore noise within ±3%
            listing["_vs_area"] = round(pct)


# ----- watchlist tracker -----------------------------------------------------

def update_watchlist(watchlist, merged_by_key, today):
    """For each tracked house, capture price changes and a sold price when the
    status flips. Returns a list of human-readable update strings."""
    updates = []
    for item in watchlist.get("tracked", []):
        if item.get("_example"):
            continue
        cur = merged_by_key.get(item["id"]) or merged_by_key.get(
            listing_key(item.get("address"), item.get("zip")))
        if not cur:
            continue
        price = cur.get("price")
        if price and price != item.get("list_price") and item.get("status") != "sold":
            item.setdefault("price_history", []).append({"date": today, "price": price})
            old = item.get("list_price")
            item["list_price"] = item.get("list_price") or price
            if old and price != old:
                updates.append(f"{item['address']}: price now ${price:,.0f} (was ${old:,.0f})")
        if cur.get("status") == "sold" and item.get("status") != "sold":
            item["status"] = "sold"
            item["sold_price"] = cur.get("sold_price")
            item["sold_date"] = today
            if item.get("added"):
                d0 = datetime.date.fromisoformat(item["added"])
                item["days_on_market"] = (datetime.date.fromisoformat(today) - d0).days
            lp, sp = item.get("list_price"), item.get("sold_price")
            delta = f" ({'+' if sp and lp and sp >= lp else ''}{(sp - lp):,.0f} vs list)" if sp and lp else ""
            updates.append(f"SOLD ${sp:,.0f}{delta} after {item.get('days_on_market','?')}d: {item['address']}")
    return updates


# ----- render ----------------------------------------------------------------

def _status_label(s):
    return {"coming_soon": "🆕 coming soon", "pending": "⏳ pending"}.get(s, "")


def _vs_area_label(pct):
    if pct is None:
        return None
    return f"🟢 {abs(pct):.0f}% under area" if pct < 0 else f"🔴 {pct:.0f}% over area"


def _tags(listing, reasons):
    """Trailing annotations shared by ASCII + Slack: status, value, dom, ⚠, reasons."""
    bits = []
    sl = _status_label(listing.get("status"))
    if sl:
        bits.append(sl)
    va = _vs_area_label(listing.get("_vs_area"))
    if va:
        bits.append(va)
    if listing.get("_dom") is not None:
        bits.append(f"{listing['_dom']}d on mkt")
    if listing.get("discrepancies"):
        bits.append("⚠ source mismatch")
    bits += reasons
    return bits


def _row(listing, reasons):
    price = f"${listing['price']:,.0f}" if listing.get("price") else "$?"
    beds, baths = listing.get("beds"), listing.get("baths")
    b = f"{beds if beds is not None else '?'}bd" + (f"/{baths}ba" if baths is not None else "")
    sqft = f"{listing['sqft']:,}sf" if listing.get("sqft") else ""
    addr = (listing.get("address") or "?")[:30]
    tags = _tags(listing, reasons)
    why = f"  — {', '.join(tags)}" if tags else ""
    return f"  {price:>9}  {b:<9} {sqft:<8} {addr}{why}"


def _market_footer(stats):
    lines = []
    for z, s in sorted(stats.items()):
        if not s["n"]:
            continue
        parts = []
        if s["median_ppsf"]:
            parts.append(f"median sold ${s['median_ppsf']:,.0f}/sf")
        if s["median_ratio"]:
            parts.append(f"{(s['median_ratio'] - 1) * 100:+.0f}% vs list")
        if s["median_dom"] is not None:
            parts.append(f"{s['median_dom']:.0f}d on market")
        lines.append(f"  {z}: {', '.join(parts)}  (n={s['n']} sold)")
    return lines


def render(new_today, this_week, close_enough, alerts, wl_updates, stats, today):
    L = [f"🏠  HOUSE HUNT — {today}", ""]
    nudge = next_milestone(today) if next_milestone else None
    if nudge:
        L += [f"  {nudge}", ""]
    L.append(f"🆕  NEW TODAY ({len(new_today)})")
    L += [_row(l, r) for l, _, _, r in new_today] or ["  (none)"]
    L.append("")
    L.append(f"🔔  CHANGES ({len(alerts)})  — on houses we've already shown")
    L += [f"  {msg}  {(l.get('address') or '')[:30]}" for l, msg in alerts] or ["  (none)"]
    L.append("")
    L.append(f"🤏  CLOSE ENOUGH ({len(close_enough)})  — bends a rule")
    L += [_row(l, r) for l, _, _, r in close_enough] or ["  (none)"]
    L.append("")
    L.append(f"🔁  THIS WEEK ({len(this_week)})  — still active from prior days")
    L += [_row(l, r) for l, _, _, r in this_week] or ["  (none)"]
    L.append("")
    L.append(f"👀  WATCHLIST ({len(wl_updates)} updates)")
    L += [f"  {u}" for u in wl_updates] or ["  (no changes)"]
    L.append("")
    L.append("📊  MARKET (from solds we've tracked)")
    L += _market_footer(stats) or ["  (no sold data yet — builds as houses close)"]
    L.append("")
    L.append("  ⚠ = sources disagreed on a number ;  vs area = list $/sf vs median sold $/sf")
    return "\n".join(L)


# ----- "worth a look" ranking + Slack Block Kit digest ----------------------

def worth_a_look(new_today, this_week, alerts, deal_pct=-8):
    """The ONLY 'loud' section: meaningfully under-market listings, price drops,
    and back-on-market. Returns [(listing, extra_reason)] — extra_reason is ''
    when the listing's own tags already explain why it's here (e.g. a deal)."""
    picks, seen = [], set()
    for entry in list(new_today) + list(this_week):
        l = entry[0]
        va = l.get("_vs_area")
        if va is not None and va <= deal_pct and l["key"] not in seen:
            picks.append((l, "")); seen.add(l["key"])
    for l, msg in alerts:
        if "🔻" in msg or "back on market" in msg:
            if l["key"] not in seen:
                picks.append((l, msg)); seen.add(l["key"])
    return picks


def open_houses_from(*groups):
    """Listings (deduped) that advertise an open house, for the weekend section."""
    out, seen = [], set()
    for g in groups:
        for entry in g:
            l = entry[0] if isinstance(entry, tuple) else entry
            if l.get("open_house") and l["key"] not in seen:
                out.append(l); seen.add(l["key"])
    return out


def _card_blocks(listing, reasons):
    """One listing -> Slack blocks: lead photo, a clickable address, specs,
    value/status tags, source attribution, and a View button."""
    price = f"${listing['price']:,.0f}" if listing.get("price") else "Price n/a"
    specs = []
    if listing.get("beds"):
        specs.append(f"{listing['beds']} bd")
    if listing.get("baths"):
        specs.append(f"{listing['baths']} ba")
    if listing.get("sqft"):
        specs.append(f"{listing['sqft']:,} sqft")
    spec = "  ·  ".join(specs)
    addr = listing.get("address") or "?"
    town = listing.get("city") or listing.get("neighborhood") or listing.get("zip") or ""
    label = f"{addr}, {town}".strip(", ")
    link = f"<{listing['url']}|{label}>" if listing.get("url") else label
    lines = [f"*{price}*" + (f"   ·   {spec}" if spec else ""), f"🏡 {link}"]
    tagline = "  ·  ".join(_tags(listing, reasons))
    if tagline:
        lines.append(f"_{tagline}_")
    if listing.get("sources"):
        lines.append(f"`seen on {', '.join(sorted(listing['sources']))}`")
    section = {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
    if listing.get("photo_url"):
        section["accessory"] = {"type": "image", "image_url": listing["photo_url"],
                                "alt_text": label[:150]}
    blocks = [section]
    if listing.get("url"):
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "View listing"},
             "url": listing["url"]}]})
    return blocks


def render_slack_blocks(worth, new_today, open_houses, alerts, stats, today, max_cards=6):
    """The single daily message as Block Kit: a quiet ⭐ lead (photo cards with
    a View-listing button for the few houses that deserve a decision), then
    collapsed counts, an open-house section, a compact New-today list, and a
    market line. Stays well under Slack's 50-block limit."""
    B = [{"type": "header", "text": {"type": "plain_text", "text": f"🏠 House Hunt · {today}"}}]
    B.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": f"NJ target towns · 3+ bd · 1.5+ ba · ≤$650k    ·    🆕 {len(new_today)} new · 🔔 {len(alerts)} changes"}]})

    B.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*⭐ Worth a look ({len(worth)})*"}})
    if not worth:
        B.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_nothing urgent today_"}]})
    for l, extra in worth[:max_cards]:
        B.append({"type": "divider"})
        B += _card_blocks(l, [extra] if extra else [])

    if open_houses:
        B.append({"type": "divider"})
        B.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🗓 Open houses this weekend*\n"
            + "\n".join(f"• <{l.get('url')}|{l.get('address')}> — {l.get('open_house')}" for l in open_houses)}})

    if new_today:
        B.append({"type": "divider"})
        rows = []
        for l, _, _, r in new_today[:18]:
            price = f"${l['price']:,.0f}" if l.get("price") else "n/a"
            tail = "  ·  ".join(_tags(l, r))
            rows.append(f"• <{l.get('url')}|{l.get('address')}> — *{price}*" + (f"  ·  {tail}" if tail else ""))
        B.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🆕 New today*\n" + "\n".join(rows)}})

    mf = _market_footer(stats)
    if mf:
        B.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "📊 " + "   ·   ".join(m.strip() for m in mf)}]})
    B.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": "reply in thread:  `track <addr>`  ·  `mute <addr>`  ·  `note <addr> \"…\"`"}]})
    return {"blocks": B}


def render_markdown(worth, new_today, this_week, close_enough, alerts, open_houses, wl_updates, stats, today):
    """The single daily message as markdown (for the Slack API path, no photos):
    quiet ⭐ lead, collapsed counts, open houses, New-today list, watchlist, market."""
    def line(l, reasons):
        price = f"**${l['price']:,.0f}**" if l.get("price") else "**Price n/a**"
        specs = []
        if l.get("beds"):
            specs.append(f"{l['beds']} bd")
        if l.get("sqft"):
            specs.append(f"{l['sqft']:,} sqft")
        label = f"{l.get('address') or '?'}, {l.get('city') or l.get('zip') or ''}".strip(", ")
        link = f"[{label}]({l['url']})" if l.get("url") else label
        body = " · ".join([price] + specs + _tags(l, reasons))
        src = f"  _(on {', '.join(sorted(l['sources']))})_" if l.get("sources") else ""
        return f"• {link} — {body}{src}"

    out = [f"## 🏠 House Hunt · {today}", "_NJ target towns · 3+ bd · 1.5+ ba · ≤$650k_", ""]
    out.append(f"**⭐ Worth a look ({len(worth)})**")
    out += [line(l, [extra] if extra else []) for l, extra in worth] or ["_nothing urgent today_"]
    out += ["", f"🆕 New: {len(new_today)}  ·  🔔 Changes: {len(alerts)}  ·  🤏 Close: {len(close_enough)}  ·  🔁 This week: {len(this_week)}"]
    if open_houses:
        out += ["", f"**🗓 Open houses this weekend ({len(open_houses)})**"]
        out += [f"• [{l.get('address')}]({l.get('url')}) — {l.get('open_house')}" for l in open_houses]
    out += ["", f"**🆕 New today ({len(new_today)})**"]
    out += [line(l, r) for l, _, _, r in new_today] or ["_none_"]
    if alerts:
        out += ["", f"**🔔 Changes ({len(alerts)})**"]
        out += [f"• {m} — {(l.get('address') or '')}" for l, m in alerts]
    out += ["", f"**👀 Watchlist ({len(wl_updates)})** — reply `track <address>` to follow a house to its sale"]
    out += [f"• {u}" for u in wl_updates] or ["_none tracked yet_"]
    mf = _market_footer(stats)
    if mf:
        out += ["", "**📊 Market pulse**"] + [m.strip() for m in mf]
    out += ["", "_reply in thread: `track <addr>` · `mute <addr>` · `note <addr> \"…\"`  ·  value tag = list $/sf vs median sold $/sf_"]
    return "\n".join(out)


def post_to_webhook(payload):
    """POST a Block Kit payload to the Slack incoming webhook named by the
    HOUSE_HUNT_SLACK_WEBHOOK env var. The secret lives only in the scheduler's
    env (never the repo). Returns True on success."""
    url = os.environ.get("HOUSE_HUNT_SLACK_WEBHOOK")
    if not url:
        print("HOUSE_HUNT_SLACK_WEBHOOK not set — skipping post", file=sys.stderr)
        return False
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"Slack post failed: {e}", file=sys.stderr)
        return False


# ----- curated digest (clean, hierarchical, clickable) -----------------------

def _is_junk(l):
    """Obviously-broken rows we shouldn't surface: missing beds, or absurd
    days-on-market (stale relist / bad record, e.g. 700+ days)."""
    if not l.get("beds"):
        return True
    dom = l.get("_dom")
    return dom is not None and dom > 365


def _is_over_budget(l, price_max):
    return bool(price_max and l.get("price") and l["price"] > price_max)


def _digest_line(l, reasons, show_town=False):
    """One clickable, scannable bullet for the Slack digest (standard markdown)."""
    price = f"**${l['price']:,.0f}**" if l.get("price") else "**price n/a**"
    spec = []
    if show_town and (l.get("city") or l.get("neighborhood")):
        spec.append(l.get("city") or l.get("neighborhood"))
    if l.get("beds"):
        spec.append(f"{l['beds']:g}bd")
    if l.get("baths"):
        spec.append(f"{l['baths']:g}ba")
    if l.get("sqft"):
        spec.append(f"{l['sqft']:,}sf")
    tail = []
    if l.get("_dom") is not None:
        tail.append(f"{l['_dom']}d on mkt")
    va = _vs_area_label(l.get("_vs_area"))
    if va:
        tail.append(va)
    tail += list(reasons)
    addr = l.get("address") or "?"
    link = f"[{addr}]({l['url']})" if l.get("url") else addr
    head = " · ".join([price] + ([" ".join(spec)] if spec else []))
    return f"• {link} — {head}" + (f"  ·  {' · '.join(tail)}" if tail else "")


def render_digest_md(today, fresh, stretch, worth, alerts, pending_count,
                     stale_count, stats, nudge=None, max_fresh=15):
    """Curated, hierarchical Slack-markdown digest: changes → deals → fresh
    (newest first) → a small over-budget 'stretch' list → what we hid → market.
    Built for a phone glance, every address a real link."""
    out = [f"🏠  **House Hunt · {today}**", "_NJ target towns · 3+ bd · 1.5+ ba · ≤ $650k_"]
    if nudge:
        out += ["", nudge]
    if alerts:
        out += ["", f"**🔔 Changes ({len(alerts)})** — on houses already shown"]
        out += [f"• {m} — {(l.get('address') or '')}" for l, m in alerts]
    if worth:
        out += ["", f"**⭐ Worth a look ({len(worth)})** — under-market & price drops"]
        out += [_digest_line(l, [e] if e else []) for l, e in worth[:8]]
    out += ["", f"**🆕 Fresh — newest first ({len(fresh)})**"]
    shown = fresh[:max_fresh]
    out += [_digest_line(l, r) for l, _, _, r in shown] or ["_nothing in budget today_"]
    if len(fresh) > len(shown):
        out.append(f"_…+{len(fresh) - len(shown)} more in-budget (older listings)_")
    if stretch:
        out += ["", f"**🤏 Stretch — just over budget ({len(stretch)})**"]
        out += [_digest_line(l, r) for l, _, _, r in stretch[:6]]
    hidden = []
    if pending_count:
        hidden.append(f"{pending_count} pending")
    if stale_count:
        hidden.append(f"{stale_count} stale/incomplete")
    if hidden:
        out += ["", f"_hidden: {' · '.join(hidden)}_"]
    mf = _market_footer(stats)
    out += ["", "**📊 Market**"]
    out += [m.strip() for m in mf] if mf else ["_no sold comps yet — `fetch.py --sold` to seed_"]
    out += ["", "_reply in thread: `track <addr>` · `mute <addr>` · `note <addr> \"…\"`_"]
    return "\n".join(out)


# ----- THE canonical board (cemented format — post this verbatim) ------------

def render_board_md(today, new_week, still_active, alerts, wl_updates, stats,
                    zip_names, zip_dist, nudge=None, max_new=12, max_active=6,
                    max_market=12):
    """THE one canonical Slack board. Fixed headers, every house linked, every
    section always rendered (shows "(none)" when empty). Listings + the market
    table are ordered CLOSEST-FIRST to the priority anchor (07090). This is the
    SINGLE source of truth for the daily post — `match.py --board` prints exactly
    what gets sent to Slack. Post it verbatim; do not hand-rewrite the message."""
    out = [f"🏠 *House Hunt · {today}*", "_NJ target towns · 3+ bd · 1.5+ ba · ≤ $650k · nearest Westfield first_"]
    if nudge:
        out += ["", nudge]

    out += ["", f"*🔔 Changes ({len(alerts)})* — price drops · pending · back-on-market · sold"]
    out += [f"• {m} — {(l.get('address') or '')}" for l, m in alerts] or ["_(none)_"]

    out += ["", f"*🆕 New this week ({len(new_week)})* — newly listed (≤7d on mkt)"]
    shown = new_week[:max_new]
    out += [_digest_line(l, r, show_town=True) for l, _, _, r in shown] or ["_(none)_"]
    if len(new_week) > len(shown):
        out.append(f"_…+{len(new_week) - len(shown)} more (see seen.json)_")

    out += ["", f"*🔁 Still active ({len(still_active)})*"]
    shown = still_active[:max_active]
    out += [_digest_line(l, r, show_town=True) for l, _, _, r in shown] or ["_(none)_"]
    if len(still_active) > len(shown):
        out.append(f"_…+{len(still_active) - len(shown)} more (see seen.json)_")

    out += ["", f"*👀 Watchlist ({len(wl_updates)})* — list→sold tracking"]
    out += [f"• {u}" for u in wl_updates] or ["_(no changes)_"]

    out += ["", "*📊 Market — median sold $/sqft · 90d trend (nearest first)*"]
    mk = []
    for z, s in stats.items():
        if not s.get("n") or not s.get("median_ppsf"):
            continue
        tr = s.get("ppsf_trend")
        trend = f" {'▲' if tr >= 0 else '▼'}{abs(tr):.0f}%" if tr is not None else ""
        dom = f"{s['median_dom']:.0f}d" if s.get("median_dom") is not None else "?"
        mk.append((zip_dist.get(z, 999), -s["n"],
                   f"• {zip_names.get(z, z)} — ${s['median_ppsf']:,.0f}/sf{trend} · {dom} · n={s['n']}"))
    mk.sort(key=lambda x: (x[0], x[1]))
    out += [line for _, _, line in mk[:max_market]] or ["_no sold comps yet_"]
    if len(mk) > max_market:
        out.append(f"_…+{len(mk) - max_market} more towns farther out (see seen.json)_")
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_blocks = "--blocks" in sys.argv
    want_post = "--post" in sys.argv
    want_md = "--md" in sys.argv
    want_digest = "--digest" in sys.argv
    want_board = "--board" in sys.argv
    today = args[0] if args else datetime.date.today().isoformat()
    criteria = load_json(os.path.join(BASE_DIR, "criteria.json"), None)
    if criteria is None:
        print("missing criteria.json — copy criteria.template.json and fill it in",
              file=sys.stderr)
        sys.exit(2)
    sources_cfg = load_json(os.path.join(BASE_DIR, "sources.json"), {"sources": []})

    raw_by_source = {}
    for path in glob.glob(os.path.join(BASE_DIR, "raw", "*.json")):
        payload = load_json(path, {})
        if payload.get("source"):
            raw_by_source[payload["source"]] = payload

    merged = reconcile(raw_by_source, sources_cfg)
    merged_by_key = {m["key"]: m for m in merged}

    scored = []
    for listing in merged:
        if listing.get("status") == "sold":
            continue  # solds feed comps/watchlist, not the buy buckets
        bucket, sort_score, reasons = score(listing, criteria)
        if bucket != "exclude":
            scored.append((listing, bucket, sort_score, reasons))
    # mutes.json: houses the user said "mute <address>" on — hide from all buckets
    muted = set(load_json(os.path.join(BASE_DIR, "mutes.json"), {"muted": []}).get("muted", []))
    if muted:
        scored = [t for t in scored if t[0]["key"] not in muted
                  and normalize_address(t[0].get("address")) not in muted]
    # sort: most nice-to-have hits first, then cheapest
    scored.sort(key=lambda t: (-t[2], t[0].get("price") or 1e12))

    seen = load_json(os.path.join(BASE_DIR, "seen.json"), {"listings": {}})
    sold_events = record_solds(merged, seen, today)          # P1: feed comps
    new_today, this_week, alerts = diff_seen(scored, seen, today)  # P0: changes
    alerts += sold_events
    close_enough = [t for t in scored if t[1] == "close"]

    stats = area_stats(seen)                                  # P1: per-zip comps
    for listing in merged:
        annotate(listing, seen, stats, today)                 # P1: dom + vs-area tag

    watchlist = load_json(os.path.join(BASE_DIR, "watchlist.json"), {"tracked": []})
    wl_updates = update_watchlist(watchlist, merged_by_key, today)

    worth = worth_a_look(new_today, this_week, alerts)
    open_houses = open_houses_from(new_today, this_week)

    # ---- curate the display lists for the digest (P0/P1) ----
    price_max = (criteria.get("price") or {}).get("max")
    pending_count = sum(1 for t in new_today if t[0].get("status") == "pending")
    stale_count = sum(1 for t in new_today
                      if t[0].get("status") == "active" and _is_junk(t[0]))
    active_clean = [t for t in new_today
                    if t[0].get("status") == "active" and not _is_junk(t[0])]
    active_clean.sort(key=lambda t: t[0].get("_dom") if t[0].get("_dom") is not None else 99999)
    fresh = [t for t in active_clean if not _is_over_budget(t[0], price_max)]
    stretch = [t for t in active_clean if _is_over_budget(t[0], price_max)]
    nudge = next_milestone(today) if next_milestone else None

    if want_board:
        zip_names = {z: n["name"] for n in criteria["neighborhoods"] for z in n.get("zips", [])}
        zip_dist = {z: n.get("dist_mi", 999) for n in criteria["neighborhoods"] for z in n.get("zips", [])}
        # active in-criteria listings, ordered CLOSEST-to-07090 first, then cheapest
        active = [t for t in scored if t[0].get("status") == "active"]
        active.sort(key=lambda t: (zip_dist.get(t[0].get("zip"), 999), t[0].get("price") or 1e12))
        def _fresh(l):
            return l.get("_dom") is not None and l["_dom"] <= 7
        new_week = [t for t in active if _fresh(t[0])]
        still_active = [t for t in active if not _fresh(t[0])]
        print(render_board_md(today, new_week, still_active, alerts, wl_updates,
                              stats, zip_names, zip_dist, nudge))
    elif want_digest:
        print(render_digest_md(today, fresh, stretch, worth, alerts,
                               pending_count, stale_count, stats, nudge))
    elif want_md:
        print(render_markdown(worth, new_today, this_week, close_enough, alerts,
                              open_houses, wl_updates, stats, today))
    else:
        print(render(new_today, this_week, close_enough, alerts, wl_updates, stats, today))
    blocks_payload = render_slack_blocks(worth, new_today, open_houses, alerts, stats, today)
    blocks_payload["text"] = (f"🏠 House Hunt {today}: {len(new_today)} new · "
                              f"{len(alerts)} changes · {len(worth)} worth a look")
    if want_blocks:
        print("\n===== SLACK BLOCKS (POST to the C0B9JHL9NE9 webhook) =====")
        print(json.dumps(blocks_payload, indent=2))
    if want_post and post_to_webhook(blocks_payload):
        print("✅ posted to Slack webhook", file=sys.stderr)

    # persist state
    os.makedirs(os.path.join(BASE_DIR, "history"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "history", f"{today}.json"), "w") as f:
        json.dump(merged, f, indent=2, default=list)
    with open(os.path.join(BASE_DIR, "seen.json"), "w") as f:
        json.dump(seen, f, indent=2)
    with open(os.path.join(BASE_DIR, "watchlist.json"), "w") as f:
        json.dump(watchlist, f, indent=2)


if __name__ == "__main__":
    main()
