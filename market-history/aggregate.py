#!/usr/bin/env python3
"""
market-history — aggregate 3 years of NJ sold/market data across sources, dedupe
it, and emit CSVs. Re-runnable: each run hydrates more data and merges it into
the committed CSVs (the repo is the DB — see ../CLAUDE.md).

WHAT IT PRODUCES
  market.csv   one row per (zip, month, property_type): median sale price, $/sqft,
               days-on-market, sale-to-list ratio, % sold above list, homes sold.
               -> "how each neighborhood moved up/down over 3 years."   [LIVE]
  sales.csv    one row per property SALE (deduped across sources): address, zip,
               list/sold dates, DOM, list/sold price, sold-vs-ask ($ and %),
               sqft/beds/baths, garage/solar/ac_type. Best-effort/nullable.  [rows
               land once nj_records + listing_scrape are implemented]
  raw/         per-source normalized pulls (gitignored) — reproducible re-merge.
  _provenance.json  every source's value for every merged field + which disagreed.

THE THREE LAYERS (see sources.json)
  redfin_dc       [LIVE]  zip-month market aggregates. Cloud-safe. Fills market.csv.
  nj_records      [STUB]  MOD-IV/SR1A deed sales — authoritative price+date. Cloud-safe.
  listing_scrape  [STUB]  Redfin/Realtor/Zillow detail — DOM, price cuts, amenities.
                          Scrape-gated (403s datacenter IPs) -> MUST run locally.

MERGE RULE  (per-field authority, NOT 2-of-3 consensus — layers are complementary)
  Each field fills from the first source in sources.json:field_authority that has
  a non-null value. All competing values are kept in _provenance.json; when 2+
  sources disagree beyond conflict_tolerance, the field name is added to that
  row's `conflicts` column.

DEDUPE KEY
  market: (zip, period_end, property_type)
  sales:  (address_norm, zip, sold_month)  — sold_month distinguishes a house that
          sold more than once in the 3-year window.

USAGE
  python3 aggregate.py                       # fetch all LIVE sources, merge, write CSVs
  python3 aggregate.py --source redfin_dc    # one source
  python3 aggregate.py --zip 07076 07067     # limit to zips (default: all in zips.json)
  python3 aggregate.py --since 2023-07       # earliest month to keep (default: 3y ago)
  python3 aggregate.py --fixture             # use fixtures/ instead of the network (offline demo)
  python3 aggregate.py --no-history          # don't snapshot CSVs into history/

  Redfin's national TSV is large; --zip narrows the FILTER, not the download.
  Override the URL with env MARKET_HISTORY_REDFIN_URL if the S3 path moves.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
HIST_DIR = os.path.join(BASE_DIR, "history")
FIX_DIR = os.path.join(BASE_DIR, "fixtures")

# config — what to scrape
ZIPS_FILE = os.path.join(BASE_DIR, "zips.json")
SOURCES_FILE = os.path.join(BASE_DIR, "sources.json")

# the dataset — sale-grain output
MARKET_CSV = os.path.join(BASE_DIR, "market.csv")
SALES_CSV = os.path.join(BASE_DIR, "sales.csv")

# state/ — machine bookkeeping, not data. Nobody reads these to answer a question:
# state.json is fetch cursors (which zip pulled when), provenance.json is every
# source's value for every merged field. Committed (the repo is the DB) but kept
# out of the root so they don't read as peers of sales.csv.
STATE_DIR = os.path.join(BASE_DIR, "state")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
PROV_FILE = os.path.join(STATE_DIR, "provenance.json")

REDFIN_ZIP_URL = os.environ.get(
    "MARKET_HISTORY_REDFIN_URL",
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/zip_code_market_tracker.tsv000.gz",
)

MARKET_COLS = [
    "zip", "town", "period_begin", "period_end", "property_type",
    "median_sale_price", "median_list_price", "median_ppsf", "median_dom",
    "avg_sale_to_list", "sold_above_list_pct", "homes_sold", "new_listings",
    "inventory", "_source", "_fetched",
]

SALES_COLS = [
    "address", "zip", "town",
    # the timeline. pending_date is the OFFER-ACCEPTED date — the moment the
    # negotiation actually ended. Everything else about "when is it cheap to buy"
    # is really a question about this date, not about sold_date (which trails it
    # by a ~40-day escrow) and not about list_date.
    "list_date", "pending_date", "sold_date",
    "days_to_contract", "days_on_market",
    "list_price", "sold_price", "sold_vs_ask_abs", "sold_vs_ask_pct",
    "price_changes", "sqft", "beds", "baths", "lot_sqft", "year_built",
    "garage", "solar", "ac_type", "property_type",
    "county", "municipality", "prop_class", "nu_code", "bldg_desc",
    "mls", "mls_id",
    "conflicts", "flags", "_sources", "_fetched",
]


def today():
    return datetime.date.today().isoformat()


def load_json(path):
    with open(path) as f:
        return json.load(f)


def default_since():
    d = datetime.date.today()
    return f"{d.year - 3:04d}-{d.month:02d}"


def zip_to_town():
    """Map every target zip -> its town name (from zips.json).

    FALLBACK labelling only — a zip is not a municipality (07006 holds Caldwell,
    North Caldwell and West Caldwell), so a sale with a deed behind it takes its
    town from MUN_NAME instead (see merge_sales). Where a zip is shared, the town
    listed FIRST in zips.json wins, so the label can't flip on a file reorder.
    """
    cfg = load_json(ZIPS_FILE)
    out = {}
    for t in cfg["towns"]:
        for z in t["zips"]:
            out.setdefault(z, t["name"])
    return out


def address_norm(s):
    """lowercase, drop punctuation, expand common abbreviations, collapse ws."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[.,#]", " ", s)
    abbr = {
        r"\bst\b": "street", r"\bave\b": "avenue", r"\brd\b": "road",
        r"\bdr\b": "drive", r"\bln\b": "lane", r"\bct\b": "court",
        r"\bpl\b": "place", r"\bblvd\b": "boulevard", r"\bter\b": "terrace",
        r"\bhwy\b": "highway", r"\bpkwy\b": "parkway", r"\bcir\b": "circle",
        # MOD-IV deed spellings the MLS writes differently — each of these was a
        # real double-counted sale before it was expanded here.
        r"\bla\b": "lane", r"\bsq\b": "square", r"\brdg\b": "ridge",
        r"\bcmn\b": "common", r"\btrl\b": "trail", r"\bhts\b": "heights",
        r"\bplz\b": "plaza", r"\bxing\b": "crossing", r"\bext\b": "extension",
        r"\bn\b": "north", r"\bs\b": "south", r"\be\b": "east", r"\bw\b": "west",
    }
    for pat, rep in abbr.items():
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


# Words that carry no identity: street types, and the *designator* part of a unit
# ("apt 3" -> the "3" identifies the unit, "apt" does not). Dropped when building
# the loose match key so `TISBURY VILLAGE` and `TISBURY CT` — the same development,
# spelled differently by the deed and the MLS — collapse to one sale.
_NOISE_WORDS = {
    "street", "avenue", "road", "drive", "lane", "court", "place", "boulevard",
    "terrace", "highway", "parkway", "circle", "common", "commons", "cmn",
    "village", "way", "trail", "path", "run", "square", "plaza", "crossing",
    "extension", "turnpike", "route", "apartment", "apt", "unit", "suite",
    "ste", "number", "no",
}


def address_key(s):
    """Loose identity key for one property: (house_number, street_stem).

    Deliberately lossier than address_norm — it exists to catch the SAME sale
    recorded by two sources that spell the address differently:

        15 COUNTRY MEADOW LN  / 15 Country Meadows Ln  (plural)
        3 GLEN GATE           / 3 Glen Gate Rd         (suffix absent)
        39 WILLOW BROOK DRIVE / 39 Willowbrook Dr      (spacing)
        21 TISBURY VILLAGE    / 21 Tisbury Ct          (street type differs)
        1220 BIRCH ST         / 1220B Birch St         (unit letter on number)

    Unit identifiers are KEPT (only the "apt"/"unit" word is dropped), so two
    condos in one building stay distinct. Never used alone — callers must also
    agree on sold_price, which is what makes the looseness safe.
    """
    s = address_norm(s)
    if not s:
        return ("", "")
    parts = s.split()
    # leading house number: digits only, so "1220b" == "1220"
    num = ""
    if parts and re.match(r"^\d", parts[0]):
        num = re.match(r"^(\d+)", parts[0]).group(1)
        parts = parts[1:]
    stem = "".join(p for p in parts if p not in _NOISE_WORDS)
    # singular/plural: meadows -> meadow
    if len(stem) > 3 and stem.endswith("s"):
        stem = stem[:-1]
    return (num, stem)


_DIRECTIONALS = {"north", "south", "east", "west"}


def address_key_loose(s):
    """address_key with unit ids and trailing directionals ALSO stripped.

    Catches the residue the strict key can't:
        8 JENNIFER COURT      / 8 Jennifer Ct Unit 8    (deed omits the unit)
        18 HAMILTON DRIVE EAST/ 18 Hamilton Dr          (deed keeps the directional)

    Far blunter — it would happily fuse two different units of one building. Only
    ever used behind an EXACT sold_price match, which is what keeps it honest.
    """
    s = address_norm(s)
    if not s:
        return ("", "")
    parts = s.split()
    num = ""
    if parts and re.match(r"^\d", parts[0]):
        num = re.match(r"^(\d+)", parts[0]).group(1)
        parts = parts[1:]
    stem = "".join(
        p for p in parts
        if p not in _NOISE_WORDS
        and p not in _DIRECTIONALS
        and not any(ch.isdigit() for ch in p)   # drop unit ids: "3", "d2", "1407"
        and len(p) > 1                          # drop bare unit letters: "a", "c"
    )
    if len(stem) > 3 and stem.endswith("s"):
        stem = stem[:-1]
    return (num, stem)


def _num(v):
    """TSV cell -> float or None. Handles '', 'NA', '$', '%', commas."""
    if v is None:
        return None
    v = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if v == "" or v.upper() in ("NA", "NAN", "NULL"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


# --------------------------------------------------------------------------- #
# SOURCE: redfin_dc  (LIVE)                                                    #
# --------------------------------------------------------------------------- #
def _open_redfin_stream(fixture):
    """Yield decoded text lines from either the fixture TSV or the S3 gz."""
    if fixture:
        path = os.path.join(FIX_DIR, "redfin_dc.tsv")
        sys.stderr.write(f"[redfin_dc] fixture: {path}\n")
        with open(path, encoding="utf-8") as f:
            for line in f:
                yield line
        return
    sys.stderr.write(
        f"[redfin_dc] streaming {REDFIN_ZIP_URL}\n"
        "[redfin_dc] (national file; large download, filtered line-by-line)\n"
    )
    req = urllib.request.Request(REDFIN_ZIP_URL, headers={"User-Agent": "market-history/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with gzip.GzipFile(fileobj=resp) as gz:
            for raw in gz:
                yield raw.decode("utf-8", "replace")


def fetch_redfin_dc(zips, since, fixture=False, limit=None):
    """Stream Redfin's zip-month TSV, keep target zips since `since` month."""
    z2t = zip_to_town()
    rows = []
    header = None
    idx = {}
    kept = 0
    for i, line in enumerate(_open_redfin_stream(fixture)):
        cells = line.rstrip("\n").split("\t")
        if header is None:
            header = cells
            idx = {name: j for j, name in enumerate(header)}
            missing = [c for c in ("region", "period_begin", "period_end", "property_type") if c not in idx]
            if missing:
                sys.stderr.write(f"[redfin_dc] WARNING: missing columns {missing}; header={header[:8]}...\n")
            continue

        def col(name):
            j = idx.get(name)
            return cells[j] if j is not None and j < len(cells) else None

        m = re.search(r"(\d{5})", col("region") or "")
        if not m:
            continue
        z = m.group(1)
        if z not in zips:
            continue
        pbeg = (col("period_begin") or "")[:7]  # YYYY-MM
        if pbeg < since:
            continue
        rows.append({
            "grain": "zip_month",
            "zip": z,
            "town": z2t.get(z, ""),
            "period_begin": col("period_begin"),
            "period_end": col("period_end"),
            "property_type": col("property_type"),
            "median_sale_price": _int(col("median_sale_price")),
            "median_list_price": _int(col("median_list_price")),
            "median_ppsf": _num(col("median_ppsf")),
            "median_dom": _num(col("median_dom")),
            "avg_sale_to_list": _num(col("avg_sale_to_list")),
            "sold_above_list_pct": _num(col("sold_above_list")),
            "homes_sold": _int(col("homes_sold")),
            "new_listings": _int(col("new_listings")),
            "inventory": _int(col("inventory")),
            "_source": "redfin_dc",
            "_fetched": today(),
        })
        kept += 1
        if limit and kept >= limit:
            break
    sys.stderr.write(f"[redfin_dc] kept {kept} zip-month rows\n")
    return rows


# --------------------------------------------------------------------------- #
# SOURCE STUBS — implement next. Each MUST return sale-grain dicts in the      #
# contract below so the merge picks them up with zero further wiring.          #
#   {grain:'sale', address, zip, sold_date:'YYYY-MM-DD', sold_price, list_date,#
#    list_price, days_on_market, price_changes, sqft, beds, baths, lot_sqft,   #
#    year_built, garage, solar, ac_type, property_type, _source, _fetched}     #
# Missing fields -> None (best-effort/nullable). Don't invent values.          #
# --------------------------------------------------------------------------- #
NJ_MUN_FILE = os.path.join(BASE_DIR, "nj_municipalities.json")

# NJ MOD-IV property-class -> our property_type label (best-effort).
NJ_CLASS = {
    "1": "Vacant Land", "2": "Residential", "3A": "Farm", "3B": "Farm",
    "4A": "Commercial", "4B": "Industrial", "4C": "Apartment (5+)",
}

# SR1A non-usable deed codes: sales NOT usable as market comps (family transfers,
# sheriff sales, $1 deeds, etc.). Numeric 01-33. We drop these from sales.csv.
NJ_NONUSABLE = {f"{i:02d}" for i in range(1, 34)}

# Floor to drop nominal/non-arms-length deeds that carry no NU code ($1, $10
# intra-family transfers). No NJ house trades arms-length below this. --min-price overrides.
NJ_MIN_PRICE = 10000


def _parse_deed_date(dd):
    """MOD-IV DEED_DATE 'YYMMDD' -> 'YYYY-MM-DD' (or None). Pivot: YY<=40 -> 20YY."""
    dd = str(dd or "").strip()
    if len(dd) != 6 or not dd.isdigit():
        return None
    yy, mm, day = int(dd[:2]), int(dd[2:4]), int(dd[4:6])
    if not (1 <= mm <= 12 and 1 <= day <= 31):
        return None
    year = 2000 + yy if yy <= 40 else 1900 + yy
    return f"{year:04d}-{mm:02d}-{day:02d}"


# MOD-IV BLDG_DESC garage codes. `2S-F-L-DG` = 2-storey, frame, ..., detached garage.
# An optional leading digit is the stall count (`2AG` = 2-car attached).
_GARAGE_RE = re.compile(r"\b(\d)?\s*([ABDU]G)\b")

# What BLDG_DESC does NOT contain: square footage. Verified against 2,000 parcels
# across 5 municipalities — ZERO carry one. The old parser searched it for `\d{3,5}SF`
# anyway and matched digits out of the structure code, inventing 49 "houses" of 4, 6,
# 22 and 35 square feet. sqft is now sourced from listing_scrape ONLY; on a deed row it
# is left NULL, which is the honest answer. Do not re-add this.


def _parse_bldg_desc(desc):
    """Garage stalls from MOD-IV BLDG_DESC. Returns None when unstated.

    Codes: AG attached, DG detached, BG built-in, UG under. All four mean the house
    HAS a garage — the earlier parser only recognised AG (plus a digit-prefixed B/UG),
    so every DETACHED garage was recorded as 'no information'. DG is not an edge case:
    across 2,000 parcels it appeared 127 times against AG's 123. It was the single most
    common garage in the data and we were dropping all of it.
    """
    if not desc:
        return None
    m = _GARAGE_RE.search(str(desc).upper())
    if not m:
        return None
    count, _code = m.groups()
    return int(count) if count else 1   # code present but no stall count -> at least 1


def _arcgis_query(endpoint, where, out_fields, page=1000, timeout=90):
    """Query an ArcGIS FeatureServer/MapServer layer, paginating via resultOffset."""
    out = []
    offset = 0
    while True:
        params = {
            "where": where, "outFields": out_fields, "returnGeometry": "false",
            "f": "json", "resultRecordCount": str(page), "resultOffset": str(offset),
            "orderByFields": "OBJECTID",  # indexed PK: fast + stable pagination (we sort client-side)
        }
        url = endpoint + "/query?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            d = json.load(resp)
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        feats = d.get("features", [])
        out.extend(a["attributes"] for a in feats)
        if len(feats) < page or not d.get("exceededTransferLimit"):
            break
        offset += page
    return out


def fetch_nj_records(zips, since, fixture=False, limit=None):
    """NJ MOD-IV deed sales via the statewide maps.nj.gov Cadastral layer.

    ONE endpoint covers every county; we query per (COUNTY, MUN_NAME) unit from
    nj_municipalities.json. Authoritative sold price + date + year built + lot +
    (best-effort) sqft/garage. Residential (class 2) by default. Cloud-safe.
    Drops SR1A non-usable deed codes. sold_date window = [since .. today].
    """
    if fixture:
        path = os.path.join(FIX_DIR, "nj_records.json")
        if os.path.exists(path):
            sys.stderr.write(f"[nj_records] fixture: {path}\n")
            return load_json(path)
        sys.stderr.write("[nj_records] no fixture, 0 rows\n")
        return []

    cfg = load_json(NJ_MUN_FILE)
    endpoint = cfg["endpoint"]
    # date window as YYMMDD strings for a server-side string range on DEED_DATE
    lo = f"{int(since[2:4]):02d}{int(since[5:7]):02d}01" if len(since) >= 7 else f"{int(since[2:4]):02d}0101"
    today_d = datetime.date.today()
    hi = f"{today_d.year % 100:02d}{today_d.month:02d}{today_d.day:02d}"
    out_fields = ("PROP_LOC,ZIP5,COUNTY,MUN_NAME,SALE_PRICE,DEED_DATE,SALES_CODE,"
                  "PROP_CLASS,YR_CONSTR,CALC_ACRE,BLDG_DESC")

    rows = []
    units = [u for u in cfg["municipalities"] if not zips or (set(u["zips"]) & zips)]
    for u in units:
        where = (
            f"COUNTY='{u['county']}' AND MUN_NAME='{u['mun']}' "
            f"AND PROP_CLASS='2' AND SALE_PRICE>0 "
            f"AND DEED_DATE>='{lo}' AND DEED_DATE<='{hi}'"
        )
        try:
            recs = _arcgis_query(endpoint, where, out_fields)
        except Exception as e:
            sys.stderr.write(f"[nj_records] {u['county']}/{u['mun']} ERROR: {e}\n")
            continue
        kept = 0
        unit_zips = set(u["zips"])
        for a in recs:
            code = (a.get("SALES_CODE") or "").strip()
            if code in NJ_NONUSABLE:
                continue  # non-usable deed (family transfer, sheriff sale, $1, ...)
            if (a.get("SALE_PRICE") or 0) < NJ_MIN_PRICE:
                continue  # nominal/uncoded transfer ($1, $10, ...)
            sold_date = _parse_deed_date(a.get("DEED_DATE"))
            if not sold_date or sold_date[:7] < since:
                continue
            bldg_desc = (a.get("BLDG_DESC") or "").strip() or None
            garage = _parse_bldg_desc(bldg_desc)
            z5 = (a.get("ZIP5") or "").strip()
            if u.get("section_of"):
                # town is a SECTION of this municipality (e.g. Colonia in Woodbridge);
                # subset the township pull to the section's zip rather than mislabel it all.
                if z5 not in unit_zips:
                    continue
                z = z5
            else:
                z = z5 if z5 in unit_zips else u["zips"][0]
            acre = a.get("CALC_ACRE") or 0
            rows.append({
                "grain": "sale",
                "address": (a.get("PROP_LOC") or "").strip(),
                "zip": z,
                "town": u["town"],
                "county": u["county"],
                "municipality": u["mun"],
                "sold_date": sold_date,
                "sold_price": a.get("SALE_PRICE"),
                # no sqft: MOD-IV does not carry one (see _parse_bldg_desc). Left NULL
                # on deed rows; listing_scrape is the only source for it.
                "lot_sqft": round(acre * 43560) if acre else None,
                "year_built": a.get("YR_CONSTR") or None,
                "garage": garage,
                # the string `garage` was parsed FROM, stored verbatim so a parser fix
                # can be re-applied to three years of history offline instead of
                # re-scraping. ~12 chars/row. This is what the garage bug cost us: it
                # was only findable by going back out to the network.
                "bldg_desc": bldg_desc,
                "prop_class": a.get("PROP_CLASS"),
                "nu_code": code or None,
                "property_type": NJ_CLASS.get(a.get("PROP_CLASS") or "", None),
                "_source": "nj_records",
                "_fetched": today(),
            })
            kept += 1
            if limit and len(rows) >= limit:
                break
        sys.stderr.write(f"[nj_records] {u['county']}/{u['mun']}: {kept} sales\n")
        if limit and len(rows) >= limit:
            break
    sys.stderr.write(f"[nj_records] total {len(rows)} sale rows from {len(units)} municipalities\n")
    return rows


# HomeHarvest `style` enum -> property_type label (copied pattern, not import).
_HH_STYLE = {
    "SINGLE_FAMILY": "Single Family", "MULTI_FAMILY": "Multi-Family",
    "DUPLEX_TRIPLEX": "Multi-Family", "TOWNHOMES": "Townhouse",
    "TOWNHOUSE": "Townhouse", "CONDOS": "Condo", "CONDO": "Condo",
    "CONDO_TOWNHOME": "Townhouse", "APARTMENT": "Apartment",
    "LAND": "Land", "FARM": "Land", "MOBILE": "Manufactured",
}


def _scan_amenities(text):
    """Best-effort solar + AC type from a listing description (None if unstated)."""
    if not text:
        return None, None
    t = str(text).lower()
    solar = True if "solar" in t else None
    ac = None
    if "central air" in t or "central a/c" in t or "central a.c" in t or "central ac" in t:
        ac = "central"
    elif "window unit" in t or "window a/c" in t or "window air" in t:
        ac = "window"
    return solar, ac


def _clean_list_dates(raw):
    """Repair Realtor.com's `list_date`, which is a RECORD-INGESTION timestamp.

    When their backend bulk-refreshes a batch of sold records, every property in the
    batch is stamped with the refresh time — `2024-08-04 14:51:57`, identical to the
    SECOND across dozens of unrelated houses in different towns. Taken at face value
    it produced 1,862 corrupt rows (8.2% of list-dated rows). See ../DEFECTS.md.

    Two tells:
      1. list_date > sold_date          — impossible; definitive.
      2. list_date timestamp reused by another property in the same pull — a real
         listing time is never shared to the second. This catches the dangerous ones
         whose fake date happens to PRECEDE the sale, which rule 1 cannot see.

    RECOVERY, in order. We only null as a last resort:
      a. `days_on_mls` is a second witness to the same interval — on healthy rows
         `sold_date - days_on_mls == list_date` to the day. If it is present, rebuild
         list_date from it.
      b. Otherwise null list_date. A blank is honest; a fabricated date silently
         poisons every time-on-market figure.

    `pending_date`, `list_price` and the sale fields are untouched — only list_date is
    junk, so sold-vs-ask and (crucially) the offer-accepted date still stand. Every
    touched row is marked in `flags` so the repair is visible, never silent.
    """
    shared = {ts for ts, n in Counter(
        r["_list_ts"] for r in raw if r.get("_list_ts")).items() if n > 1}
    for r in raw:
        ts = r.pop("_list_ts", None)
        ld, sd, dom = r.get("list_date"), r.get("sold_date"), r.get("days_on_market")
        why = None
        if ld and sd and ld > sd:
            why = "list_date_after_sold_date"
        elif ts and ts in shared:
            why = "list_date_is_batch_sentinel"
        if not why:
            continue
        if dom is not None and sd:                       # (a) rebuild from days_on_mls
            r["list_date"] = (datetime.date.fromisoformat(sd)
                              - datetime.timedelta(days=int(dom))).isoformat()
            r["flags"] = why + ";list_date_rebuilt_from_dom"
        else:                                            # (b) unrecoverable
            r["list_date"] = None
            r["days_on_market"] = None
            r["flags"] = why + ";list_date_nulled"
    hit = [r for r in raw if r.get("flags")]
    fixed = sum(1 for r in hit if "rebuilt" in r["flags"])
    if hit:
        sys.stderr.write(
            "[listing_scrape] %d fabricated list_dates (%d shared ingestion "
            "timestamps): %d rebuilt from days_on_mls, %d nulled — see DEFECTS.md\n"
            % (len(hit), len(shared), fixed, len(hit) - fixed))
    return raw


def fetch_listing_scrape(zips, since, fixture=False, limit=None):
    """Recent SOLD listings via HomeHarvest (Realtor.com). LOCAL ONLY (403s in
    cloud). Fills DOM, list price, beds/baths, garage, amenities — and the recent
    ~12-18mo that nj_records lags. Zip-based (Realtor.com knows zips). Copies
    house-hunt's HomeHarvest field mapping (pattern, not import)."""
    if fixture:
        path = os.path.join(FIX_DIR, "listing_scrape.json")
        if os.path.exists(path):
            sys.stderr.write(f"[listing_scrape] fixture: {path}\n")
            return load_json(path)
        sys.stderr.write("[listing_scrape] no fixture, 0 rows\n")
        return []
    try:
        from homeharvest import scrape_property
        import pandas as pd
    except ImportError:
        sys.stderr.write("[listing_scrape] homeharvest not installed "
                         "(pip install homeharvest) — 0 rows\n")
        return []

    date_from = f"{since}-01" if len(since) == 7 else since
    date_to = today()
    rows = []
    for z in sorted(zips):
        try:
            df = scrape_property(location=z, listing_type="sold",
                                 date_from=date_from, date_to=date_to)
        except Exception as e:
            sys.stderr.write(f"[listing_scrape] {z} ERROR: {e}\n")
            continue
        kept = 0
        for _, r in df.iterrows():
            def g(k):
                v = r.get(k)
                try:
                    if pd.isna(v):
                        return None
                except (TypeError, ValueError):
                    pass
                return v
            sold_date = str(g("last_sold_date"))[:10] if g("last_sold_date") else None
            sold_price = g("sold_price")
            if not sold_date or not sold_price or sold_date[:7] < since:
                continue
            full, half = g("full_baths") or 0, g("half_baths") or 0
            baths = (full + 0.5 * half) or None
            street, unit = g("street"), g("unit")
            addr = f"{street} {unit}".strip() if unit else street
            garage = g("parking_garage")
            solar, ac = _scan_amenities(g("text"))
            rows.append({
                "grain": "sale",
                "address": addr,
                "zip": str(g("zip_code") or z)[:5],
                "sold_date": sold_date,
                "sold_price": int(sold_price),
                "list_price": int(g("list_price")) if g("list_price") else None,
                "list_date": str(g("list_date"))[:10] if g("list_date") else None,
                # full timestamp kept only so _clean_list_dates can spot the batch
                # artifacts (a shared ingestion time); it never reaches the CSV
                "_list_ts": str(g("list_date")) if g("list_date") else None,
                # THE OFFER-ACCEPTED DATE. Realtor.com exposes it and we were
                # throwing it away — every "when should we bid" question needs this,
                # not sold_date (which trails it by a ~40-day escrow). Far cleaner
                # than list_date: ~1% incoherent vs ~7%.
                "pending_date": str(g("pending_date"))[:10] if g("pending_date") else None,
                "days_on_market": int(g("days_on_mls")) if g("days_on_mls") is not None else None,
                "mls": g("mls"),
                "mls_id": str(g("mls_id")) if g("mls_id") else None,
                "beds": g("beds"),
                "baths": baths,
                "sqft": g("sqft"),
                "lot_sqft": int(g("lot_sqft")) if g("lot_sqft") else None,
                "year_built": g("year_built"),
                "garage": int(garage) if garage is not None else None,
                "solar": solar,
                "ac_type": ac,
                "property_type": _HH_STYLE.get(str(g("style") or "").upper(),
                                               str(g("style") or "").replace("_", " ").title() or None),
                "_source": "listing_scrape",
                "_fetched": today(),
            })
            kept += 1
            if limit and len(rows) >= limit:
                break
        sys.stderr.write(f"[listing_scrape] {z}: {kept} sold listings\n")
        if limit and len(rows) >= limit:
            break
    sys.stderr.write(f"[listing_scrape] total {len(rows)} sold rows from {len(zips)} zips\n")
    return _clean_list_dates(rows)


SOURCE_FNS = {
    "redfin_dc": fetch_redfin_dc,
    "nj_records": fetch_nj_records,
    "listing_scrape": fetch_listing_scrape,
}


# --------------------------------------------------------------------------- #
# MERGE                                                                        #
# --------------------------------------------------------------------------- #
def merge_market(new_rows):
    """Dedupe zip-month rows by (zip, period_end, property_type). Newest wins.

    Idempotent: re-reads existing market.csv so a re-run HYDRATES rather than
    overwrites. Only redfin_dc feeds this grain today.
    """
    by_key = {}
    for r in _read_csv(MARKET_CSV):  # existing state
        by_key[(r["zip"], r["period_end"], r["property_type"])] = r
    for r in new_rows:
        by_key[(r["zip"], r["period_end"], r["property_type"])] = r
    return list(by_key.values())


def _sold_month(r):
    sd = r.get("sold_date") or ""
    return sd[:7] if len(sd) >= 7 else "unknown"


# Fields where cross-source differences are expected and NOT real conflicts:
# property_type vocab differs by source (MOD-IV "Residential" vs MLS "Single Family").
CATEGORICAL_NOFLAG = {"property_type"}
# Date fields: deed-recording date (MOD-IV) lags the MLS close date by days —
# same sale, not a conflict. Flag only if further apart than this many days.
DATE_FIELDS = {"sold_date": 21, "list_date": 21}


def _conflict(field, values, tol_map):
    """True if the non-null values disagree beyond tolerance for this field."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2 or field in CATEGORICAL_NOFLAG:
        return False
    if field in DATE_FIELDS and all(isinstance(v, str) and len(v) >= 10 for v in vals):
        try:
            dts = [datetime.date.fromisoformat(v[:10]) for v in vals]
            return (max(dts) - min(dts)).days > DATE_FIELDS[field]
        except ValueError:
            pass
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    if field == "year_built" and len(nums) == len(vals):
        return (max(nums) - min(nums)) > 1  # ±1yr assessor-vs-MLS drift is fine
    tol = tol_map.get(field)
    if tol is not None and len(nums) == len(vals) and nums:
        lo, hi = min(nums), max(nums)
        if lo == 0:
            return hi != 0
        return (hi - lo) / abs(lo) > tol
    return len(set(map(str, vals))) > 1


# How close two sold_prices must be to be believed the same sale. Deed and MLS
# occasionally differ by a rounding/transfer-tax hair; beyond this they are two
# different houses that merely share a street and a month.
COALESCE_PRICE_TOL = 0.01


def _price_agrees(rows):
    """True if every row's sold_price sits within COALESCE_PRICE_TOL of the others."""
    ps = [float(r["sold_price"]) for r in rows
          if r.get("sold_price") not in (None, "")]
    if len(ps) < 2:
        return True  # nothing to contradict
    lo, hi = min(ps), max(ps)
    return lo > 0 and (hi - lo) / lo <= COALESCE_PRICE_TOL


def _srcs(r):
    return set((r.get("_sources") or r.get("_source") or "").split(",")) - {""}


def _fuse(members, authority):
    """Collapse rows known to be one sale into a single row, by field authority."""
    base = max(members, key=lambda m: len(m.get("address") or ""))
    merged = dict(base)
    for field, order in authority.items():
        if field.startswith("_"):
            continue
        picked = None
        for src in order:                      # authority order, best first
            for m in members:
                if src in _srcs(m) and m.get(field) not in (None, ""):
                    picked = m[field]
                    break
            if picked is not None:
                break
        if picked is None:                     # no authority hit: any value will do
            picked = next((m[field] for m in members
                           if m.get(field) not in (None, "")), None)
        if picked is not None:
            merged[field] = picked

    merged["address"] = base.get("address")
    merged["_sources"] = ",".join(sorted(set().union(*(_srcs(m) for m in members))))
    merged["conflicts"] = ";".join(sorted(
        {c for m in members for c in (m.get("conflicts") or "").split(";") if c}
    ))
    merged["flags"] = ";".join(sorted(
        {f for m in members for f in (m.get("flags") or "").split(";") if f}
    ))
    lp, sp = _num(merged.get("list_price")), _num(merged.get("sold_price"))
    if lp and sp:
        merged["sold_vs_ask_abs"] = sp - lp
        merged["sold_vs_ask_pct"] = round((sp - lp) / lp * 100, 2)
    _set_days_to_contract(merged)
    return merged


def _set_days_to_contract(row):
    """days_to_contract = list -> under contract. How long you actually have to act.

    Median 14 days across the dataset, and half of all homes go under contract inside
    two weeks — so this, not `days_on_market` (which is list -> CLOSING and trails the
    negotiation by a ~40-day escrow), is the number that says how fast a buyer must move.
    """
    ld, pd_ = row.get("list_date"), row.get("pending_date")
    row["days_to_contract"] = None
    if ld and pd_:
        d = (datetime.date.fromisoformat(pd_) - datetime.date.fromisoformat(ld)).days
        if d >= 0:                      # a negative interval means one date is junk
            row["days_to_contract"] = d


def _coalesce_pass(rows, authority, keyfn, exact_price):
    """One fusing sweep. Rows fuse only when ALL of these hold:

      1. same (key, zip, sold_month) — same house, per whichever key is in play,
      2. sold_price agrees (exactly, or within tolerance) — the real safety check,
      3. they came from DIFFERENT sources — one source listing a street twice in a
         month is two houses (27 Knoll Rd, 914 Knoll Rd), not a double-count.
    """
    buckets = defaultdict(list)
    for r in rows:
        smonth = (r.get("sold_date") or "")[:7] or "unknown"
        buckets[(keyfn(r.get("address")), r.get("zip"), smonth)].append(r)

    out, fused = [], 0
    for (akey, _z, _m), members in buckets.items():
        # unkeyable (no house number AND no stem) — never risk fusing these
        if len(members) == 1 or akey == ("", ""):
            out.extend(members)
            continue
        prices = [float(m["sold_price"]) for m in members
                  if m.get("sold_price") not in (None, "")]
        ok = (len(set(prices)) <= 1) if exact_price else _price_agrees(members)
        if not ok:
            out.extend(members)          # same street, different houses
            continue
        all_srcs = [_srcs(m) for m in members]
        if any(a & b for i, a in enumerate(all_srcs) for b in all_srcs[i + 1:]):
            # Careful: a RE-FETCH is not a second house. Once a sale is fused, the row
            # carries BOTH sources and the *other* source's address spelling, so the
            # next pull of the same deed can't match merge_sales' exact address key and
            # arrives here looking like an nj-vs-nj collision. Left alone, every re-run
            # re-adds it and the dataset inflates (it is supposed to be idempotent).
            # Tell them apart by the source SET: a re-fetch is a proper subset of the
            # fused row it came from; two genuinely distinct houses have equal source
            # sets, so they never subset each other and still fall through as before.
            survivors = [m for i, m in enumerate(members)
                         if not any(i != j and all_srcs[i] < all_srcs[j]
                                    for j in range(len(members)))]
            if len(survivors) == 1:      # everything else was a redundant re-fetch
                out.append(survivors[0])
                fused += len(members) - 1
                continue
            out.extend(members)          # same source twice => distinct properties
            continue
        out.append(_fuse(members, authority))
        fused += len(members) - 1
    return out, fused


def coalesce_sales(rows, sources_cfg):
    """Fuse rows that are ONE sale recorded twice under different address spellings.

    merge_sales' exact key cannot see these — the deed says `21 TISBURY VILLAGE`,
    the MLS says `21 Tisbury Ct`, and the sale lands as two rows, inflating every
    count. Runs over the FULL row set (freshly-merged + previously-committed), so
    it also repairs duplicates already sitting in sales.csv.

    Two sweeps, loosening the address key while tightening the price guard:
      1. address_key       + price within 1%  — the ordinary spelling drift.
      2. address_key_loose + price EXACTLY equal — unit ids and directionals that
         only one source recorded. Blunt key, so the price guard does the work.

    Returns (rows, n_fused).
    """
    authority = sources_cfg["field_authority"]
    rows, n1 = _coalesce_pass(rows, authority, address_key, exact_price=False)
    rows, n2 = _coalesce_pass(rows, authority, address_key_loose, exact_price=True)
    return rows, n1 + n2


def merge_sales(new_rows, sources_cfg):
    """Per-field authority merge of sale-grain rows across sources.

    Groups by (address_norm, zip, sold_month); for each field picks the first
    source in field_authority that has a value; records provenance + conflicts.
    """
    authority = sources_cfg["field_authority"]
    tol = sources_cfg["conflict_tolerance"]
    z2t = zip_to_town()

    groups = defaultdict(list)
    for r in new_rows:
        key = (address_norm(r.get("address")), r.get("zip"), _sold_month(r))
        groups[key].append(r)

    merged, provenance = [], {}
    for (anorm, z, smonth), members in groups.items():
        by_src = {m["_source"]: m for m in members}
        # Town comes from the deed's MUNICIPALITY when we have one, and only falls
        # back to the zip otherwise: a zip can cover several municipalities (07006 is
        # Caldwell AND North Caldwell AND West Caldwell), so zip_to_town would lump
        # them. listing_scrape-only sales have no municipality and keep the fallback.
        nj = by_src.get("nj_records")
        out = {"zip": z, "town": (nj or {}).get("town") or z2t.get(z, "")}
        prov, conflicts = {}, []

        # every candidate field = union of authority keys
        for field, order in authority.items():
            if field.startswith("_"):
                continue
            picked = None
            seen_vals = []
            for src in order:
                if src in by_src and by_src[src].get(field) is not None:
                    seen_vals.append((src, by_src[src][field]))
                    if picked is None:
                        picked = by_src[src][field]
            out[field] = picked
            # Provenance is the audit trail for DISAGREEMENTS — record a field only
            # when sources actually conflict (agreements need no trail; the merged
            # value already reflects the consensus). Keeps the sidecar small.
            if len(seen_vals) >= 2 and _conflict(field, [v for _, v in seen_vals], tol):
                prov[field] = {s: v for s, v in seen_vals}
                conflicts.append(field)

        # address: keep the longest raw string seen (most complete)
        out["address"] = max((m.get("address") or "" for m in members), key=len)
        # derived sold-vs-ask
        lp, sp = out.get("list_price"), out.get("sold_price")
        if lp and sp:
            out["sold_vs_ask_abs"] = sp - lp
            out["sold_vs_ask_pct"] = round((sp - lp) / lp * 100, 2)
        else:
            out["sold_vs_ask_abs"] = out["sold_vs_ask_pct"] = None
        out["conflicts"] = ";".join(conflicts)
        out["_sources"] = ",".join(sorted(by_src))
        out["_fetched"] = today()
        merged.append(out)
        if prov:
            provenance[f"{anorm}|{z}|{smonth}"] = prov

    return merged, provenance


# --------------------------------------------------------------------------- #
# IO                                                                           #
# --------------------------------------------------------------------------- #
def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path, cols, rows):
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (list, dict)):
            return json.dumps(v, separators=(",", ":"))
        return v
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: cell(r.get(c)) for c in cols})


def _sort_market(rows):
    return sorted(rows, key=lambda r: (str(r.get("zip")), str(r.get("period_end")), str(r.get("property_type"))))


def _sort_sales(rows):
    return sorted(rows, key=lambda r: (str(r.get("zip")), str(r.get("sold_date")), str(r.get("address"))))


def snapshot_history(market_rows, sales_rows):
    day_dir = os.path.join(HIST_DIR, today())
    os.makedirs(day_dir, exist_ok=True)
    _write_csv(os.path.join(day_dir, "market.csv"), MARKET_COLS, _sort_market(market_rows))
    _write_csv(os.path.join(day_dir, "sales.csv"), SALES_COLS, _sort_sales(sales_rows))


def update_state(source, market_rows, sales_rows):
    """Per (source, zip) cursor: newest date seen + row count, so a re-run knows
    how current each zip is. Handles both grains (period_end / sold_date)."""
    state = load_json(STATE_FILE) if os.path.exists(STATE_FILE) else {}
    agg = defaultdict(lambda: {"latest": "", "rows": 0})
    for r in market_rows:
        if r.get("_source") == source and r.get("zip"):
            a = agg[r["zip"]]
            a["rows"] += 1
            a["latest"] = max(a["latest"], str(r.get("period_end") or ""))
    for r in sales_rows:
        if r.get("_source") == source and r.get("zip"):
            a = agg[r["zip"]]
            a["rows"] += 1
            a["latest"] = max(a["latest"], str(r.get("sold_date") or ""))
    bucket = state.setdefault(source, {})
    for z, v in agg.items():
        bucket[z] = {"latest": v["latest"], "rows": v["rows"], "last_fetched": today()}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Aggregate NJ market/sold data -> CSVs.")
    ap.add_argument("--source", nargs="*", help="sources to run (default: all LIVE)")
    ap.add_argument("--zip", nargs="*", dest="zips", help="limit to these zips")
    ap.add_argument("--since", default=default_since(), help="earliest YYYY-MM to keep")
    ap.add_argument("--fixture", action="store_true", help="use fixtures/, no network")
    ap.add_argument("--limit", type=int, help="cap rows per source (debug)")
    ap.add_argument("--min-price", type=int, help="drop nj_records sales below this (default 10000)")
    ap.add_argument("--no-history", action="store_true", help="skip history/ snapshot")
    ap.add_argument("--dedupe-only", action="store_true",
                    help="no fetch: re-coalesce the committed sales.csv and rewrite it")
    args = ap.parse_args()

    if args.min_price is not None:
        global NJ_MIN_PRICE
        NJ_MIN_PRICE = args.min_price

    sources_cfg = load_json(SOURCES_FILE)

    # Repair pass over already-committed data. No network, no fetch: read sales.csv,
    # fuse the rows that are one sale under two spellings, write it back.
    if args.dedupe_only:
        existing = _read_csv(SALES_CSV)
        deduped, fused = coalesce_sales(existing, sources_cfg)
        print(f"{len(existing)} rows -> {len(deduped)} ({fused} duplicate row(s) fused)")
        _write_csv(SALES_CSV, SALES_COLS, _sort_sales(deduped))
        return

    live = [l["key"] for l in sources_cfg["layers"] if l["status"] == "live"]
    requested = args.source or live
    zips_cfg = load_json(ZIPS_FILE)
    all_zips = {z for t in zips_cfg["towns"] for z in t["zips"]}
    zips = set(args.zips) & all_zips if args.zips else all_zips
    if args.zips and not zips:
        sys.exit(f"none of {args.zips} are target zips")

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    market_new, sales_new = [], []
    for src in requested:
        fn = SOURCE_FNS.get(src)
        if not fn:
            sys.stderr.write(f"[{src}] unknown source, skipping\n")
            continue
        rows = fn(zips, args.since, fixture=args.fixture, limit=args.limit)
        with open(os.path.join(RAW_DIR, f"{src}.json"), "w") as f:
            json.dump(rows, f, indent=2)
        for r in rows:
            (market_new if r.get("grain") == "zip_month" else sales_new).append(r)

    market_rows = _sort_market(merge_market(market_new))
    existing_sales = _read_csv(SALES_CSV)
    sales_merged, prov = merge_sales(sales_new, sources_cfg)
    # keep existing sales rows that this run didn't touch (idempotent hydrate)
    touched = {(address_norm(r.get("address")), r.get("zip"), _sold_month(r)) for r in sales_merged}
    for r in existing_sales:
        k = (address_norm(r.get("address")), r.get("zip"), (r.get("sold_date") or "")[:7] or "unknown")
        if k not in touched:
            sales_merged.append(r)
    # Safety net over the FULL set (new + previously-committed): fuse one sale that
    # two sources spelled differently. merge_sales' exact key cannot see these, and
    # without this every count runs a few percent high. Also repairs history.
    sales_merged, fused = coalesce_sales(sales_merged, sources_cfg)
    if fused:
        print(f"  coalesced {fused} duplicate row(s) — same sale, different address spelling")
    sales_rows = _sort_sales(sales_merged)

    _write_csv(MARKET_CSV, MARKET_COLS, market_rows)
    _write_csv(SALES_CSV, SALES_COLS, sales_rows)
    if prov:
        existing_prov = load_json(PROV_FILE) if os.path.exists(PROV_FILE) else {}
        existing_prov.update(prov)
        with open(PROV_FILE, "w") as f:
            json.dump(existing_prov, f, indent=2, sort_keys=True)

    for src in requested:
        update_state(src, market_new, sales_new)
    if not args.no_history:
        snapshot_history(market_rows, sales_rows)

    conflicted = sum(1 for r in sales_rows if r.get("conflicts"))
    print(
        f"market.csv: {len(market_rows)} zip-month rows "
        f"({len({r['zip'] for r in market_rows})} zips)\n"
        f"sales.csv:  {len(sales_rows)} sale rows ({conflicted} with field conflicts)\n"
        f"sources run: {', '.join(requested)}  |  since {args.since}"
    )


if __name__ == "__main__":
    main()
