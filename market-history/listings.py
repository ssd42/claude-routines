#!/usr/bin/env python3
"""listings.py — watch what is ON the market, so we can see it LEAVE and COME BACK.

    python3 listings.py                 # one observation run; appends to listings.csv
    python3 listings.py --zip 07090     # limit to zips
    python3 listings.py --dry-run       # scrape + report, write nothing

WHY THIS EXISTS
---------------
A seller whose house isn't moving can pull the listing and put it back later. The MLS
starts a fresh listing — new `days_on_market`, often a new `mls_id` — and the house
reads as brand new. That is the point of the tactic: buyers pay more for a house that
looks like it just arrived.

Our sold-listings source returns ONE row per sold property with ONE `list_date`. A
house that listed in February, was pulled in April, relisted in June and sold in July
reaches us as *a single listing that began in June*. **The February listing does not
exist in our data.** So `days_on_market` in `sales.csv` is a FLOOR, not a fact — and it
is short by the most for exactly the houses that struggled longest. Our data is biased
in the direction of the deception.

No field fixes this. The vendor doesn't return withdrawn listings and exposes no listing
history. The only way to know a house left the market is TO HAVE BEEN WATCHING. So we
watch: each run records what is currently for sale, and a listing that was here last run
and is gone this run has ENDED. If the same property reappears later, that is a RELIST,
and we know the true first-list date because we saw it.

THE GRAIN — one row per listing SPELL, not per sale
---------------------------------------------------
A spell is one continuous period a property sat on the market: `first_seen` to
`last_seen`. A property with two spells was relisted once. `sales.csv` is one row per
transaction; this is one row per *attempt* to transact. Do not merge them (root
CLAUDE.md: grains stay separate) — join on `property_key` when a question spans both.

IT IS FORWARD-ONLY, AND THAT IS THE WHOLE REASON TO START NOW
-------------------------------------------------------------
This can only see disappearances that happen AFTER it starts running. It will tell you
nothing about 2023-2025 — those years stay blind. Every week it doesn't run is a week of
history that can never be reconstructed. The first run just establishes a baseline: it
cannot detect anything until a SECOND run sees something missing.

WHAT WE DELIBERATELY DO NOT DO
------------------------------
We do not fuse two spells into one just because the gap between them was short. A
6-week gap at the SAME price is a days-on-market reset; a 6-week gap at a price cut
from $700K to $625K is a genuine repricing, and reporting "180 days on market" for it
would misrepresent a real new offer to the market. **The price delta is the tell, not
the gap.** So we record the spells as FACTS — every spell keeps its own first/last
price — and leave the collapsing to whoever asks the question. A reader who wants
cumulative time-on-market sums the spells; a reader who wants "days since the seller
last blinked" takes the latest one. Both are derivable. A fused row would destroy the
second one forever.

CAN THIS RUN IN THE CLOUD? NO.
------------------------------
Same constraint as `listing_scrape` in aggregate.py — Realtor.com 403s datacenter IPs,
so this must run on a residential connection. It cannot be a cloud routine. It needs a
weekly local trigger (launchd/cron on the machine), and if that trigger doesn't exist,
this file quietly stops accumulating and the whole thing is worthless. See README.
"""
import argparse
import csv
import re
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
LISTINGS_CSV = os.path.join(BASE, "listings.csv")
ZIPS_FILE = os.path.join(BASE, "zips.json")

sys.path.insert(0, BASE)
from aggregate import address_key, today  # noqa: E402  (same-folder reuse)


def property_key(address, zip_code):
    """Stable identity for a HOUSE — the thing a spell attaches to.

    Built on aggregate.py's address_key so a listing and a sale of the same house land
    on the same key: `address_key` returns (house_number, street_stem), which already
    absorbs the spelling drift between sources (`21 TISBURY VILLAGE` / `21 Tisbury Ct`).
    Flattened to `number|street|zip` so the column is greppable and joinable as a plain
    string rather than a stringified tuple.
    """
    num, street = address_key(address)
    return f"{num}|{street}|{zip_code}"

COLS = [
    "property_key",          # address_key + zip. The identity of the HOUSE.
    "address", "zip", "town",
    "spell",                 # 1 = first time we ever saw it listed, 2 = relisted once, ...
    "mls_id",                # a relist usually gets a NEW one — corroborates the spell split
    "list_date",             # what the feed claims this listing began (may itself be a relist)
    "first_seen", "last_seen",   # what WE observed. This is the part we can vouch for.
    "first_list_price", "last_list_price",
    "observations",          # how many runs saw it. 1 = we've only ever seen it once.
    "status",                # active | gone   — OUR spell state, not the MLS's
    "gone_on",               # first run that did NOT see it. Blank while active.
    "price_changed",         # yes if last_list_price != first_list_price during the spell
    # ---- the house itself. Added 2026-07-16 so offer/market.html can browse the
    # market and hand a house to the analyser. STABLE per spell (a house does not
    # grow a bedroom mid-listing), so they are written once, when the spell opens.
    "beds", "baths", "sqft", "lot_sqft", "year_built", "property_type",
    "lat", "lon",            # listings carry these on ~100% of rows; sales.csv has NONE
    "url", "photo",
    # ---- VOLATILE: re-read every run, because they move while the spell is open.
    "mls_status",            # FOR_SALE | PENDING | CONTINGENT — the MLS's own state.
                             # NOT the same as `status` above: a PENDING house is still
                             # ON the market (the feed returns it), so its spell stays
                             # `active` until it disappears. ~23% of the feed is already
                             # spoken for, and a browse view MUST filter on this or it
                             # will send you to a house that has an accepted offer.
    "days_on_mls",           # what the feed claims. A relist resets it — that is the
                             # whole reason this file exists. Trust first_seen instead.
    # The listing copy, VERBATIM (trimmed to 900 chars). It is the only place garage /
    # pool / central-air / condition exist — no structured field carries them. Stored
    # raw rather than pre-parsed, for the reason DEFECTS.md learned the hard way with
    # bldg_desc: the garage parser was wrong for months and fixing it needed a whole
    # re-scrape, because we had thrown the source string away. Keep the text and the
    # next parser fix re-applies to three years of history offline.
    "text",
]

# Realtor.com's for_sale feed includes homes that already have an accepted offer.
AVAILABLE = {"FOR_SALE"}

# Same normalisation aggregate.py uses, so property_type matches sales.csv and the
# comp engine compares like with like.
STYLE = {
    "SINGLE_FAMILY": "Single Family", "MULTI_FAMILY": "Multi-Family",
    "CONDOS": "Condo", "CONDO": "Condo", "CONDO_TOWNHOME": "Condo",
    "CONDO_TOWNHOME_ROWHOME_COOP": "Condo", "TOWNHOMES": "Townhouse",
    "TOWNHOUSE": "Townhouse", "DUPLEX_TRIPLEX": "Multi-Family",
    "APARTMENT": "Condo", "LAND": "Land", "MOBILE": "Mobile", "FARM": "Farm",
}


def load_existing():
    if not os.path.exists(LISTINGS_CSV):
        return []
    with open(LISTINGS_CSV, newline="") as fh:
        return list(csv.DictReader(fh))


def scrape(zips, dry):
    """Everything currently FOR SALE in the target zips. LOCAL ONLY (403s in cloud)."""
    try:
        from homeharvest import scrape_property
        import pandas as pd
    except ImportError:
        sys.exit("homeharvest not installed — pip install homeharvest")

    seen = {}
    for z in sorted(zips):
        try:
            df = scrape_property(location=z, listing_type="for_sale")
        except Exception as e:
            sys.stderr.write(f"[listings] {z} ERROR: {e}\n")
            continue
        n = 0
        for _, r in df.iterrows():
            def g(k):
                v = r.get(k)
                try:
                    if pd.isna(v):
                        return None
                except (TypeError, ValueError):
                    pass
                return v

            street, unit = g("street"), g("unit")
            if not street:
                continue
            addr = f"{street} {unit}".strip() if unit else street
            zc = str(g("zip_code") or z)[:5]
            key = property_key(addr, zc)
            # one property, one entry per run — a duplicate row in the feed is not a relist
            if key in seen:
                continue
            full, half = g("full_baths") or 0, g("half_baths") or 0
            seen[key] = {
                "property_key": key, "address": addr, "zip": zc,
                "mls_id": str(g("mls_id")) if g("mls_id") else "",
                "list_date": str(g("list_date"))[:10] if g("list_date") else "",
                "list_price": int(g("list_price")) if g("list_price") else "",
                # the house — for offer/market.html. sqft is ~47% filled and lot ~89%;
                # the analyser takes either, so a sqft-less listing is still usable and
                # must not be dropped here.
                "beds": int(g("beds")) if g("beds") else "",
                "baths": (full + 0.5 * half) or "",
                "sqft": int(g("sqft")) if g("sqft") else "",
                "lot_sqft": int(g("lot_sqft")) if g("lot_sqft") else "",
                "year_built": int(g("year_built")) if g("year_built") else "",
                "property_type": STYLE.get(str(g("style") or "").upper().strip(), ""),
                "lat": round(float(g("latitude")), 6) if g("latitude") else "",
                "lon": round(float(g("longitude")), 6) if g("longitude") else "",
                "url": g("property_url") or "",
                "photo": g("primary_photo") or "",
                "mls_status": str(g("status") or "").upper(),
                "days_on_mls": int(g("days_on_mls")) if g("days_on_mls") is not None else "",
                "text": re.sub(r"\s+", " ", str(g("text") or ""))[:900],
            }
            n += 1
        sys.stderr.write(f"[listings] {z}: {n} active listings\n")
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", dest="zips", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = json.load(open(ZIPS_FILE))
    zip_town = {}
    for t in cfg["towns"]:
        for z in t["zips"]:
            zip_town.setdefault(z, t["name"])
    zips = set(args.zips) & set(zip_town) if args.zips else set(zip_town)

    run = today()
    rows = load_existing()
    first_ever = not rows

    live = scrape(zips, args.dry_run)

    # index the ACTIVE spell per property (a property has at most one open spell)
    active = {r["property_key"]: r for r in rows if r["status"] == "active"}
    spells = {}
    for r in rows:
        spells[r["property_key"]] = max(spells.get(r["property_key"], 0), int(r["spell"]))

    new_spells, relists, continued, ended = 0, 0, 0, 0

    STABLE = ("beds", "baths", "sqft", "lot_sqft", "year_built", "property_type",
              "lat", "lon", "url", "photo")
    # the copy can be rewritten mid-spell (a stale listing gets a refresh), so re-read it
    VOLATILE_TEXT = ("text",)
    VOLATILE = ("mls_status", "days_on_mls")

    for key, obs in live.items():
        cur = active.get(key)
        if cur:                                        # still on the market
            cur["last_seen"] = run
            cur["observations"] = str(int(cur["observations"]) + 1)
            if obs["list_price"] != "":
                if str(obs["list_price"]) != cur["last_list_price"]:
                    cur["price_changed"] = "yes"
                cur["last_list_price"] = str(obs["list_price"])
            # mls_status moves while the spell is open (FOR_SALE -> PENDING), so it is
            # re-read every run. The spell itself stays `active`: a pending house has
            # not left the market, it just isn't available to you.
            for f in VOLATILE + VOLATILE_TEXT:
                cur[f] = str(obs[f])
            # backfill the house fields onto spells opened before 2026-07-16, when this
            # file only recorded prices. Only ever fills a blank — never overwrites an
            # observation we already made.
            for f in STABLE:
                if not cur.get(f):
                    cur[f] = str(obs[f])
            continued += 1
            continue
        # not currently open -> either brand new to us, or BACK after being gone
        n = spells.get(key, 0) + 1
        if n > 1:
            relists += 1
        else:
            new_spells += 1
        spells[key] = n
        row = {
            "property_key": key, "address": obs["address"], "zip": obs["zip"],
            "town": zip_town.get(obs["zip"], ""), "spell": str(n),
            "mls_id": obs["mls_id"], "list_date": obs["list_date"],
            "first_seen": run, "last_seen": run,
            "first_list_price": str(obs["list_price"]), "last_list_price": str(obs["list_price"]),
            "observations": "1", "status": "active", "gone_on": "", "price_changed": "",
        }
        for f in STABLE + VOLATILE + VOLATILE_TEXT:
            row[f] = str(obs[f])
        rows.append(row)

    # anything that WAS active and is not in this run's scrape has left the market.
    # It either sold or was withdrawn — link_sales.py decides which, by checking sales.csv.
    for key, cur in active.items():
        if key not in live:
            cur["status"] = "gone"
            cur["gone_on"] = run
            ended += 1

    avail = sum(1 for o in live.values() if o["mls_status"] in AVAILABLE)
    print()
    print("run %s — %d active listings scraped across %d zips" % (run, len(live), len(zips)))
    print("  %5d listings continued from a previous run" % continued)
    print("  %5d new to us (first spell)" % new_spells)
    print("  %5d RELISTED (a property we had seen leave, now back)" % relists)
    print("  %5d left the market since the last run (sold or withdrawn)" % ended)
    print()
    print("  %5d actually AVAILABLE (mls_status FOR_SALE)" % avail)
    print("  %5d already pending/contingent — still listed, not buyable" % (len(live) - avail))
    have = lambda f: sum(1 for o in live.values() if o[f] != "")
    print("  house detail: sqft on %d%%, lot on %d%% — the analyser takes either"
          % (100 * have("sqft") / max(len(live), 1), 100 * have("lot_sqft") / max(len(live), 1)))

    if first_ever:
        print()
        print("  This is the BASELINE run. It cannot detect a relist yet — a relist needs")
        print("  us to see a listing LEAVE and COME BACK, which takes at least two more")
        print("  runs. From here on, every run adds history that cannot be recovered")
        print("  retroactively. Run it weekly.")

    if args.dry_run:
        print("\n--dry-run: listings.csv not written")
        return

    rows.sort(key=lambda r: (r["town"], r["property_key"], int(r["spell"])))
    with open(LISTINGS_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote listings.csv (%d spells across %d properties)"
          % (len(rows), len(spells)))


if __name__ == "__main__":
    main()
