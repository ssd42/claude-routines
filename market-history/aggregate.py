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
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
HIST_DIR = os.path.join(BASE_DIR, "history")
FIX_DIR = os.path.join(BASE_DIR, "fixtures")
ZIPS_FILE = os.path.join(BASE_DIR, "zips.json")
SOURCES_FILE = os.path.join(BASE_DIR, "sources.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
MARKET_CSV = os.path.join(BASE_DIR, "market.csv")
SALES_CSV = os.path.join(BASE_DIR, "sales.csv")
PROV_FILE = os.path.join(BASE_DIR, "_provenance.json")

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
    "address", "zip", "town", "list_date", "sold_date", "days_on_market",
    "list_price", "sold_price", "sold_vs_ask_abs", "sold_vs_ask_pct",
    "price_changes", "sqft", "beds", "baths", "lot_sqft", "year_built",
    "garage", "solar", "ac_type", "property_type",
    "county", "municipality", "prop_class", "nu_code",
    "conflicts", "_sources", "_fetched",
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
    """Map every target zip -> its town name (from zips.json)."""
    cfg = load_json(ZIPS_FILE)
    out = {}
    for t in cfg["towns"]:
        for z in t["zips"]:
            out[z] = t["name"]
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
        r"\bn\b": "north", r"\bs\b": "south", r"\be\b": "east", r"\bw\b": "west",
    }
    for pat, rep in abbr.items():
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


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


def _parse_bldg_desc(desc):
    """Best-effort pull sqft + garage count from MOD-IV BLDG_DESC (e.g. '2S F 1BG',
    '2SCB-3780SF'). Returns (sqft, garage_count) — either may be None."""
    if not desc:
        return None, None
    s = str(desc).upper()
    sqft = None
    m = re.search(r"(\d{3,5})\s*SF", s)
    if m:
        sqft = int(m.group(1))
    garage = None
    m = re.search(r"(\d)\s*[BU]G", s)  # N built-in / under garage
    if m:
        garage = int(m.group(1))
    elif re.search(r"\bAG\b", s):       # attached garage, count unknown
        garage = 1
    return sqft, garage


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
            sqft, garage = _parse_bldg_desc(a.get("BLDG_DESC"))
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
                "sqft": sqft,
                "lot_sqft": round(acre * 43560) if acre else None,
                "year_built": a.get("YR_CONSTR") or None,
                "garage": garage,
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


def fetch_listing_scrape(zips, since, fixture=False, limit=None):
    """TODO: reuse house-hunt HomeHarvest path (local only). DOM/price-cuts/amenities."""
    sys.stderr.write("[listing_scrape] STUB — not implemented yet (0 rows)\n")
    return []


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


def _conflict(field, values, tol_map):
    """True if the non-null values disagree beyond tolerance for this field."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return False
    tol = tol_map.get(field)
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    if tol is not None and len(nums) == len(vals) and nums:
        lo, hi = min(nums), max(nums)
        if lo == 0:
            return hi != 0
        return (hi - lo) / abs(lo) > tol
    return len(set(map(str, vals))) > 1


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
        out = {"zip": z, "town": z2t.get(z, "")}
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
            # Provenance only matters where sources OVERLAP — record just those
            # fields, so the sidecar stays empty until a 2nd source lands.
            if len(seen_vals) >= 2:
                prov[field] = {s: v for s, v in seen_vals}
                if _conflict(field, [v for _, v in seen_vals], tol):
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
    args = ap.parse_args()

    if args.min_price is not None:
        global NJ_MIN_PRICE
        NJ_MIN_PRICE = args.min_price

    sources_cfg = load_json(SOURCES_FILE)
    live = [l["key"] for l in sources_cfg["layers"] if l["status"] == "live"]
    requested = args.source or live
    zips_cfg = load_json(ZIPS_FILE)
    all_zips = {z for t in zips_cfg["towns"] for z in t["zips"]}
    zips = set(args.zips) & all_zips if args.zips else all_zips
    if args.zips and not zips:
        sys.exit(f"none of {args.zips} are target zips")

    os.makedirs(RAW_DIR, exist_ok=True)
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
