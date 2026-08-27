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
# Imported at module level ON PURPOSE, not inside main(). A scrape takes ~3 minutes of
# network; if this module were broken or its boundary file missing, a deferred import
# would only blow up AFTER all that work. Fail at startup instead.
import relabel_listings  # noqa: E402  (same-folder reuse)


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
    # How that town was decided: `polygon` = the listing's own coordinates fell inside
    # that town's boundary (verified); `zip`/`nocoord` = we fell back to the ZIP's label
    # and could NOT verify it. A ZIP is a mail route, not a municipality, so the fallback
    # is a best guess (08812 covers Dunellen AND Green Brook). Written by
    # relabel_listings.py, which main() runs at the end of every scrape — this column
    # must stay in COLS or the writer's extrasaction="ignore" silently drops it.
    "town_source",
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
    # `baths` above SUMS halves (1 full + 2 half reads as 2.0), which is worse than
    # useless for this buyer: his gate is TWO SHOWERS ("we shower almost always at the
    # same time"), and a powder room has none. 324 Green St, Woodbridge reads baths=2.0
    # and its copy says "1 full bathroom, and 2 convenient half baths" -- ONE shower, and
    # the summed column cannot see it. The feed has always returned these two separately
    # (we were already reading them at the g() call below and then discarding the split).
    # Keep `baths` for continuity; gate and score on `baths_full`.
    "baths_full", "baths_half",
    "lat", "lon",            # listings carry these on ~100% of rows; sales.csv has NONE
    "url", "photo",
    # ⚠️ CORRECTED 2026-08-27. The note here used to read "the feed HAS carried these
    # three all along... fill: garage 56%, ac_type 8%, solar 1%". That was measured off
    # the raw HomeHarvest frame, NOT off listings.csv — and all three have been written
    # as BLANK on every run since they were added. Committed listings.csv at HEAD:
    # 0/5741 on all three. Two separate causes, both verified against homeharvest 0.8.18:
    #   * `garage` is the WRONG NAME. HomeHarvest calls the column `parking_garage`
    #     (utils.py:56), so g("garage") has always returned None. Fixed at the g() call.
    #   * `ac_type` and `solar` are NOT HomeHarvest columns AT ALL — no such fields exist
    #     in its output. They can only ever come from mining the description text, which
    #     is what aggregate.py's listing_scrape does (hence the ~1%/6% quoted in
    #     CLAUDE.md — that is a DIFFERENT code path). Reading them as feed fields here
    #     cannot work. Kept in COLS so the schema is stable and the intent is on record;
    #     see KNOWN_BLANK below, which is what stops the guard nagging about them.
    "garage",                # number of bays, from `parking_garage`
    "ac_type",               # text-mined only — always blank here. See KNOWN_BLANK.
    "solar",                 # text-mined only — always blank here. See KNOWN_BLANK.
    # ⚠️ The 2026-08-24 note claimed "HomeHarvest sets extra_property_data=True by
    # default, so we were already paying for them on the wire". That is NOT TRUE of the
    # installed version and these two came back 0/6104 on the 2026-08-27 run.
    # homeharvest 0.8.18 (the LATEST release — no upgrade fixes it) hard-codes
    #     self.extra_property_data = False   # TODO: temporarily disabled
    # in core/scrapers/__init__.py:101, overwriting whatever the caller passes; `tax` and
    # `assessed_value` are produced ONLY inside process_extra_property_details
    # (processors.py:235-236), gated on that flag. So they are never on the wire.
    # This was already known and written down — appraise/context.py:179 says "the live
    # feed ... has no tax field" and predates the 08-24 change. Two contradicting true
    # statements lived in this repo at once; that is why CLAUDE.md now carries one
    # feed-reality table instead of facts buried in comments.
    #
    # THE REAL SOURCE IS MOD-IV, and it is better than the scraper would have been:
    # NET_VALUE (assessed base, per parcel, cloud-safe, already fetched every run) x the
    # DCA general tax rate. That is correct for exactly the reason the 08-24 note cared
    # about — Woodbridge has not revalued since 1986 and Van Decker bars a sale-triggered
    # reassessment, so a Colonia bill tracks a STALE assessed base. Multiplying the real
    # assessed base by the real rate captures that; rate x price cannot. See aggregate.py
    # (assessed_value / land_value / imprvt_value) and layers/tax/ (general_rate_pct).
    # Those are SALE-grain, so they populate sales.csv, not this file — putting tax on an
    # ACTIVE listing still needs an address join to the parcel table (TODO.md).
    # STABLE per spell either way: a tax bill does not move while a house sits.
    "tax",                   # annual $, as billed. Blank here — see KNOWN_BLANK.
    "assessed_value",        # $ — Chapter 123 check. Blank here — see KNOWN_BLANK.
    # ---- VOLATILE: re-read every run, because they move while the spell is open.
    "mls_status",            # FOR_SALE | PENDING | CONTINGENT — the MLS's own state.
                             # NOT the same as `status` above: a PENDING house is still
                             # ON the market (the feed returns it), so its spell stays
                             # `active` until it disappears. ~23% of the feed is already
                             # spoken for, and a browse view MUST filter on this or it
                             # will send you to a house that has an accepted offer.
    "days_on_mls",           # what the feed claims. A relist resets it — that is the
                             # whole reason this file exists. Trust first_seen instead.
    # The listing copy, VERBATIM (trimmed to 900 chars). It used to be the only place
    # garage / central-air / condition existed; garage and ac_type are now structured
    # columns above (the feed always had them, we were discarding them). The text is
    # still the ONLY source for condition, pool, and roof/remodel claims, and it is
    # still the fallback wherever those columns are empty — which for ac_type is 92%
    # of rows. Stored
    # raw rather than pre-parsed, for the reason DEFECTS.md learned the hard way with
    # bldg_desc: the garage parser was wrong for months and fixing it needed a whole
    # re-scrape, because we had thrown the source string away. Keep the text and the
    # next parser fix re-applies to three years of history offline.
    "text",
]

# --------------------------------------------------------------------------- #
# Column bookkeeping — the guard that would have caught five dead columns       #
# --------------------------------------------------------------------------- #
# COLS above is the CSV SCHEMA. It is not what gets written. A row is assembled
# in main() from SPELL_KEYS + STABLE + VOLATILE + VOLATILE_TEXT, and those two
# lists were maintained separately and SILENTLY DIVERGED: `tax`,
# `assessed_value`, `garage`, `ac_type` and `solar` all sat in COLS but in none
# of the write tuples, so nothing could ever write them — DictWriter just emitted
# the empty string, forever, on every run.
#
# Nobody noticed for five weeks because A COLUMN OF BLANKS LOOKS EXACTLY LIKE A
# SPARSE COLUMN. aggregate.py already guards the equivalent failure one level up
# (it stops loudly when a whole SOURCE returns nothing, added after the trend
# feed silently died for weeks). This is that same guard at COLUMN grain, which
# is where it was missing. Both are cheap; both only exist because the silent
# version cost real data.
#
# These tuples live at module scope, not inside main(), specifically so
# _assert_cols_covered() can run at IMPORT — no network, no scrape, microseconds.

# Written by hand when a spell opens or continues, not copied from an observation.
# `town_source` is the exception: relabel_listings.relabel() writes it after the
# scrape (see the note in COLS), so it is legitimately absent from the row dict here.
SPELL_KEYS = ("property_key", "address", "zip", "town", "town_source", "spell",
              "mls_id", "list_date", "first_seen", "last_seen",
              "first_list_price", "last_list_price", "observations",
              "status", "gone_on", "price_changed")

# STABLE: a house does not grow a bedroom, move, or get re-billed mid-spell.
# Written once when the spell opens, and backfilled onto older spells ONLY where
# blank — never overwriting an observation we already made.
STABLE = ("beds", "baths", "baths_full", "baths_half", "sqft", "lot_sqft",
          "year_built", "property_type", "lat", "lon", "url", "photo",
          "garage", "ac_type", "solar", "tax", "assessed_value")

# VOLATILE: re-read every run, because they move while the spell is open.
VOLATILE = ("mls_status", "days_on_mls")

# The copy can be rewritten mid-spell (a stale listing gets a refresh), so re-read it.
VOLATILE_TEXT = ("text",)

# WHY a column is allowed to be 100% empty. The fill-rate guard warns about any
# other COLS field that comes back 0%. Every entry here is a VERIFIED FACT about
# the feed (homeharvest 0.8.18, checked 2026-08-27) with the evidence attached —
# not a licence to stop caring about the column. Delete an entry the moment its
# reason stops being true, and the guard will start telling you about it again.
KNOWN_BLANK = {
    "tax": "extra_property_data hard-disabled in homeharvest 0.8.18 "
           "(core/scrapers/__init__.py:101, 'TODO: temporarily disabled') — the "
           "field is never on the wire. Real source is MOD-IV NET_VALUE x the DCA "
           "general rate; see aggregate.py + layers/tax/.",
    "assessed_value": "same cause as `tax`. MOD-IV carries it directly, per parcel.",
    "ac_type": "not a HomeHarvest column at all — text-mined only (aggregate.py).",
    "solar": "not a HomeHarvest column at all — text-mined only (aggregate.py).",
}


def _assert_cols_covered():
    """Every COLS entry must be writable by something. Runs at import.

    This is the whole lesson of 2026-08-27 in six lines: the schema and the
    writers are two hand-maintained lists, so make their divergence a crash
    instead of a silent blank column.
    """
    written = set(SPELL_KEYS) | set(STABLE) | set(VOLATILE) | set(VOLATILE_TEXT)
    unwritable = [c for c in COLS if c not in written]
    if unwritable:
        raise AssertionError(
            "listings.py: %r are in COLS but in none of SPELL_KEYS / STABLE / "
            "VOLATILE / VOLATILE_TEXT, so nothing can ever write them and they "
            "would ship as blank columns. Add each to the tuple it belongs in."
            % (unwritable,))
    orphan = [c for c in sorted(written) if c not in COLS]
    if orphan:
        raise AssertionError(
            "listings.py: %r are written but missing from COLS, so DictWriter's "
            "extrasaction='ignore' would silently drop them." % (orphan,))
    stale = [c for c in KNOWN_BLANK if c not in COLS]
    if stale:
        raise AssertionError(
            "listings.py: KNOWN_BLANK names %r, which are no longer in COLS. "
            "Drop the entries." % (stale,))


_assert_cols_covered()


def report_fill(rows):
    """Print how full every column actually is, and shout about the empty ones.

    The point is the 0% line. A brand-new column that silently writes nothing
    looks identical to a column that is merely thin, and that is precisely how
    five fields survived five weeks of clean-looking runs.
    """
    n = len(rows)
    if not n:
        return
    filled = {c: sum(1 for r in rows if str(r.get(c, "")).strip()) for c in COLS}
    print("\n— column fill (%d rows) —" % n)
    for c in COLS:
        pct = 100.0 * filled[c] / n
        mark = "" if filled[c] else ("  (known: %s)" % KNOWN_BLANK[c].split(" — ")[0]
                                     if c in KNOWN_BLANK else "   <-- EMPTY")
        print("  %-18s %6d  %5.1f%%%s" % (c, filled[c], pct, mark))

    surprises = [c for c in COLS if not filled[c] and c not in KNOWN_BLANK]
    if surprises:
        sys.stderr.write(
            "\n!! %d column(s) wrote NOTHING and have no recorded reason: %s\n"
            "   A blank column looks exactly like a sparse one, so this will not\n"
            "   show up anywhere else. Either the feed renamed the field, or it is\n"
            "   missing from STABLE/VOLATILE, or it never existed. Check, then\n"
            "   either fix the mapping or add it to KNOWN_BLANK with the evidence.\n"
            % (len(surprises), ", ".join(surprises)))


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
                "baths_full": int(full) if full else "",
                "baths_half": int(half) if half else "",
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
                # `parking_garage`, NOT `garage` — HomeHarvest's column name
                # (utils.py:56). g("garage") returned None on every row ever scraped.
                "garage": g("parking_garage") or "",
                "ac_type": str(g("ac_type") or "").lower(),
                "solar": "yes" if g("solar") else "",
                "tax": int(float(g("tax"))) if g("tax") else "",
                "assessed_value": (int(float(g("assessed_value")))
                                   if g("assessed_value") else ""),
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

    # STABLE / VOLATILE / VOLATILE_TEXT are module-level now, checked against COLS at
    # import by _assert_cols_covered(). They used to be defined here, out of sight of
    # the schema they are supposed to match — which is how five columns went dead.

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

    # Report on what was actually WRITTEN, not on what the feed handed us. The two are
    # not the same thing — that distinction is the entire bug this guard exists for.
    report_fill(rows)

    # Resolve every town from its coordinates, right here, every run. New spells arrive
    # carrying only the ZIP's label (see the `town`/`town_source` note in COLS), and a ZIP
    # is not a municipality — so without this the file ships unverified towns until someone
    # remembers to re-run it by hand. It is idempotent and needs no network.
    #
    # Deliberately AFTER listings.csv is written, and deliberately non-fatal: the scrape is
    # the expensive, unrepeatable part (it is forward-only — a missed run is a relist we
    # can never observe again). If the boundary check fails, we keep the scrape and say the
    # towns are unverified, which the pages now render honestly as `town_source=unchecked`.
    # Losing three minutes of network to a missing GeoJSON would be the worse trade.
    print("\n— verifying towns against boundaries —")
    try:
        relabel_listings.relabel()
    except Exception as e:                                   # noqa: BLE001 — see above
        sys.stderr.write(
            f"\n!! town verification FAILED ({type(e).__name__}: {e}).\n"
            "   listings.csv IS written and the scrape is safe — but its towns are the\n"
            "   ZIP's label, unverified. Fix the cause and re-run:\n"
            "       python3 relabel_listings.py\n")


if __name__ == "__main__":
    main()
