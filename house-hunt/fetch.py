#!/usr/bin/env python3
"""
House-hunt listing fetcher — the agent-side half that fills raw/ before match.py.

WHY THIS RUNS LOCALLY (not in the cloud routine): real-estate sites 403 every
datacenter IP, and the scheduled cloud sandbox blocks all outbound HTTP except
the git proxy + attached MCP connectors. Free listing data is only reachable
from a residential IP — i.e. this machine. So you run fetch.py here, then
match.py turns raw/ into the board.

SOURCES (in order; first one that returns listings wins):
  1. RentCast  — official JSON API, free 50 calls/mo. Set RENTCAST_API_KEY.
                 stdlib only (urllib). No photos. Primary.
  2. HomeHarvest — free OSS scraper of Realtor.com (`pip install homeharvest`).
                 No key, includes photos + listing URLs. Fallback.

It writes one file per source into raw/<source>.json in EXACTLY the shape
match.py documents (see its header docstring), keyed to the target zips in
criteria.json. raw/ is gitignored and rewritten each run.

USAGE
  python3 fetch.py                      # auto: RentCast if key set, else HomeHarvest;
                                        # pulls recently-sold comps by default
  python3 fetch.py --source homeharvest # force a source
  python3 fetch.py --no-sold           # skip the recently-sold comp pull

NOTE: solds are fetched BY DEFAULT so the dataset captures list->sold outcomes
(match.py's record_solds archives them into seen.json['sold'] + the market comps).
Solds come from HomeHarvest only; the RentCast path is active-listings-only.
"""

import datetime
import glob
import json
import os
import sys
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
RENTCAST_BASE = "https://api.rentcast.io/v1"


def _today():
    return datetime.date.today().isoformat()


def load_criteria_zips():
    """Target zips from criteria.json (fall back to the two known zips)."""
    path = os.path.join(BASE_DIR, "criteria.json")
    try:
        with open(path) as f:
            crit = json.load(f)
        zips = [z for n in crit.get("neighborhoods", []) for z in n.get("zips", [])]
        return zips or ["07076", "07067"]
    except (OSError, ValueError):
        return ["07076", "07067"]


def _search_url(address, city, zip_code):
    """RentCast gives no listing URL — build a Google search so the row is still
    clickable (HomeHarvest supplies a real property_url instead)."""
    q = urllib.parse.quote_plus(f"{address} {city} NJ {zip_code} for sale")
    return f"https://www.google.com/search?q={q}"


# ----- source 1: RentCast (stdlib) -------------------------------------------

def fetch_rentcast(zips, api_key):
    """Active for-sale listings per zip via RentCast. Returns a list in match.py
    shape, or raises on a hard error (caller falls back to HomeHarvest)."""
    listings = []
    for zip_code in zips:
        qs = urllib.parse.urlencode({"zipCode": zip_code, "status": "Active", "limit": 500})
        req = urllib.request.Request(
            f"{RENTCAST_BASE}/listings/sale?{qs}",
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.load(resp)
        for r in rows if isinstance(rows, list) else []:
            addr = r.get("addressLine1") or (r.get("formattedAddress") or "").split(",")[0]
            z = (r.get("zipCode") or zip_code)[:5]
            city = r.get("city")
            listings.append({
                "address": addr,
                "zip": z,
                "city": city,
                "neighborhood": city,
                "price": r.get("price"),
                "beds": r.get("bedrooms"),
                "baths": r.get("bathrooms"),
                "sqft": r.get("squareFootage"),
                "property_type": r.get("propertyType"),
                "status": "active",  # status=Active query → all active
                "sold_price": None,
                "url": _search_url(addr, city, z),
                "photo_url": None,  # RentCast has no photos
                "listed_date": (r.get("listedDate") or "")[:10] or None,
                "tags": [],
            })
    return listings


# ----- source 2: HomeHarvest (third-party, lazy import) ----------------------

_HH_STATUS = {"FOR_SALE": "active", "PENDING": "pending", "CONTINGENT": "pending",
              "SOLD": "sold"}

# HomeHarvest `style` enum -> match.py / criteria.json property_type strings.
_HH_STYLE = {
    "SINGLE_FAMILY": "Single Family",
    "TOWNHOMES": "Townhouse", "TOWNHOUSE": "Townhouse", "TOWNHOME": "Townhouse",
    "CONDOS": "Condo", "CONDO": "Condo", "CONDO_TOWNHOME": "Townhouse",
    "MULTI_FAMILY": "Multi-Family", "DUPLEX_TRIPLEX": "Multi-Family",
    "APARTMENT": "Apartment", "LAND": "Land", "FARM": "Land", "MOBILE": "Manufactured",
}


def _norm_style(s):
    if not s:
        return None
    return _HH_STYLE.get(str(s).upper(), str(s).replace("_", " ").title())


def _hh_rows(zips, listing_type, sold_status, past_days=None):
    from homeharvest import scrape_property  # lazy: only needed on this path
    import pandas as pd
    out = []
    for zip_code in zips:
        kwargs = {"location": zip_code, "listing_type": listing_type}
        if past_days:
            kwargs["past_days"] = past_days
        df = scrape_property(**kwargs)
        for _, r in df.iterrows():
            def g(k):
                v = r.get(k)
                # normalize pandas NA / NaN -> None (else `NA or x` raises)
                try:
                    if pd.isna(v):
                        return None
                except (TypeError, ValueError):
                    pass
                return v
            full = g("full_baths") or 0
            half = g("half_baths") or 0
            baths = (full + 0.5 * half) or None
            street = g("street")
            unit = g("unit")
            addr = f"{street} {unit}".strip() if unit else street
            z = str(g("zip_code") or zip_code)[:5]
            status = sold_status or _HH_STATUS.get(str(g("status") or "").upper(), "active")
            photos = g("alt_photos")
            photo = g("primary_photo") or (photos.split(",")[0] if isinstance(photos, str) else None)
            out.append({
                "address": addr,
                "zip": z,
                "city": g("city"),
                "neighborhood": g("city"),
                "price": g("list_price") or g("sold_price"),
                "beds": g("beds"),
                "baths": baths,
                "sqft": g("sqft"),
                "property_type": _norm_style(g("style")),
                "status": status,
                "sold_price": g("sold_price") if status == "sold" else None,
                "sold_date": (str(g("last_sold_date"))[:10] if g("last_sold_date") else None),
                # listing-side (seller) agent + brokerage. Realtor.com does NOT
                # publish the buyer's agent, so there is no buyer-side field here.
                "list_agent": g("agent_name"),
                "list_brokerage": g("office_name") or g("broker_name"),
                "url": g("property_url"),
                "photo_url": photo,
                "listed_date": (str(g("list_date"))[:10] if g("list_date") else None),
                "tags": [],
            })
    return out


def fetch_homeharvest(zips, want_sold=False):
    listings = _hh_rows(zips, "for_sale", None)
    if want_sold:
        listings += _hh_rows(zips, "sold", "sold", past_days=90)
    return listings


# ----- write + orchestrate ---------------------------------------------------

def _clear_raw():
    os.makedirs(RAW_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(RAW_DIR, "*.json")):
        os.remove(f)


def write_raw(source, listings):
    path = os.path.join(RAW_DIR, f"{source}.json")
    with open(path, "w") as f:
        json.dump({"source": source, "fetched": _today(), "listings": listings}, f, indent=2)
    return path


def main():
    args = sys.argv[1:]
    force = None
    if "--source" in args:
        force = args[args.index("--source") + 1]
    want_sold = "--no-sold" not in args  # solds on by default; --no-sold to skip
    zips = load_criteria_zips()
    key = os.environ.get("RENTCAST_API_KEY")

    use_rentcast = force == "rentcast" or (force is None and key)
    if use_rentcast:
        if not key:
            print("RentCast needs RENTCAST_API_KEY (free at rentcast.io).", file=sys.stderr)
            sys.exit(2)
        try:
            listings = fetch_rentcast(zips, key)
            if listings:
                _clear_raw()
                path = write_raw("rentcast", listings)
                print(f"RentCast: {len(listings)} listings across {zips} -> {path}")
                return
            print("RentCast returned 0 listings; falling back to HomeHarvest.", file=sys.stderr)
        except Exception as e:  # network / 401 / 429 / parse
            print(f"RentCast failed ({e}); falling back to HomeHarvest.", file=sys.stderr)
        if force == "rentcast":
            sys.exit(1)

    # HomeHarvest path
    try:
        listings = fetch_homeharvest(zips, want_sold=want_sold)
    except ImportError:
        print("HomeHarvest not installed. Run: pip install homeharvest "
              "(or set RENTCAST_API_KEY to use RentCast).", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"HomeHarvest failed: {e}", file=sys.stderr)
        sys.exit(1)
    if not listings:
        print("No listings found from any source.", file=sys.stderr)
        sys.exit(1)
    _clear_raw()
    path = write_raw("homeharvest", listings)
    print(f"HomeHarvest: {len(listings)} listings across {zips} -> {path}")


if __name__ == "__main__":
    main()
