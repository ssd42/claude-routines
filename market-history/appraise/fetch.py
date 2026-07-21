"""Stage 0, the version that should have existed first: drop a link, get an appraisal.

    python3 fetch.py "https://www.zillow.com/homedetails/12-Maple-Ave-Cranford-NJ-07016/123_zpid/"
    python3 fetch.py "https://www.realtor.com/realestateandhomes-detail/..."
    python3 fetch.py "12 Maple Ave, Cranford, NJ 07016"

The link is only ever used to work out an ADDRESS. Zillow, Redfin and Realtor URLs all
carry it in the path, so no site is special and nothing is fetched from the site you
pasted. The facts then come from the same source listings.py already uses.

THIS FETCH IS A NON-MODEL PROCESS, and that is the whole point. It writes the price
straight into subject_sealed.json and never into subject_blind.json, so the stages that
form a view cannot see it — the blinding is plumbing, exactly as SPIKE-appraiser.md §2
requires. A model that fetched the page itself would read the price off the top and
anchor on it.

Falls back to listings.csv when the scrape is rate-limited (Realtor throttles hard), so a
house we already hold still appraises offline.
"""
import argparse, csv, json, re, sys, warnings
from pathlib import Path
from urllib.parse import unquote

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUN = HERE / "run"
import prepare  # reuse the scrub + blind/sealed contract, so both paths agree

STATES = r"(?:NJ|NY|PA|CT)"


def address_from_url(u):
    """Every big listing site puts the address in the path. Pull it out; ignore the rest."""
    u = unquote(u.split("?")[0].rstrip("/"))
    # realtor: .../realestateandhomes-detail/103-Emerald-Valley-Ln_Basking-Ridge_NJ_07920_M54...
    m = re.search(r"/realestateandhomes-detail/([^/]+)", u)
    if m:
        p = m.group(1).split("_")
        street = p[0].replace("-", " ")
        town = p[1].replace("-", " ") if len(p) > 1 else ""
        st = p[2] if len(p) > 2 else "NJ"
        zc = p[3] if len(p) > 3 and p[3].isdigit() else ""
        return f"{street}, {town}, {st} {zc}".strip().rstrip(",")
    # zillow: /homedetails/12-Maple-Ave-Cranford-NJ-07016/123456_zpid/
    m = re.search(r"/homedetails/([^/]+)", u)
    if m:
        # "12-Maple-Ave-Cranford-NJ-07016" -> street and town cannot be split reliably
        # (both are hyphenated, both are variable length, and "Basking-Ridge" is two
        # words). Don't guess: hyphens to spaces and let the search handle it, which it
        # does. An earlier version tried a regex here and produced "12, Maple Ave
        # Cranford" — a wrong comma is worse than no comma.
        return m.group(1).replace("-", " ")
    # redfin: /NJ/Cranford/12-Maple-Ave-07016/home/123456
    m = re.search(rf"/({STATES})/([^/]+)/([^/]+?)-(\d{{5}})/home/", u)
    if m:
        return (f"{m.group(3).replace('-',' ')}, {m.group(2).replace('-',' ')}, "
                f"{m.group(1)} {m.group(4)}")
    return None


def scrape(address):
    from homeharvest import scrape_property
    for lt in ("for_sale", "pending", "sold"):
        try:
            df = scrape_property(location=address, listing_type=lt, limit=5)
        except Exception as e:
            print(f"  {lt}: {type(e).__name__} {str(e)[:90]}", file=sys.stderr)
            continue
        if len(df):
            return df.iloc[0], lt
    return None, None


def from_csv(address):
    """Offline fallback — the house may already be in our own scrape."""
    want = re.sub(r"[^a-z0-9]", "", address.lower())[:18]
    for r in csv.DictReader(open(ROOT / "listings.csv")):
        if re.sub(r"[^a-z0-9]", "", r["address"].lower())[:18] == want:
            return r
    return None


def g(row, *names):
    for n in names:
        if n in row.index and str(row[n]) not in ("nan", "<NA>", "None", ""):
            return row[n]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="a listing URL from any site, or a plain address")
    ap.add_argument("--offline", action="store_true", help="skip the scrape, use listings.csv")
    a = ap.parse_args()

    address = (address_from_url(a.target) if a.target.lower().startswith("http")
               else a.target)
    if not address:
        sys.exit("could not read an address out of that link — paste the address instead")
    print(f"address : {address}")

    row, kind = (None, None) if a.offline else scrape(address)
    RUN.mkdir(exist_ok=True)

    if row is not None:
        photos = [p for p in str(g(row, "alt_photos") or "").split(", ") if p.startswith("http")]
        blind = {
            "address": str(g(row, "street") or address),
            "town": str(g(row, "city") or ""), "zip": str(g(row, "zip_code") or ""),
            "beds": g(row, "beds"),
            "baths": (float(g(row, "full_baths") or 0) + 0.5 * float(g(row, "half_baths") or 0)) or None,
            "sqft": g(row, "sqft"), "lot_sqft": g(row, "lot_sqft"),
            "year_built": g(row, "year_built"),
            "property_type": {"SINGLE_FAMILY": "Single Family", "CONDOS": "Condo",
                              "CONDO": "Condo", "TOWNHOMES": "Townhouse",
                              "MULTI_FAMILY": "Multi-Family"}.get(str(g(row, "style") or ""), ""),
            "garage": g(row, "garage"), "ac_type": g(row, "ac_type"),
            "lat": g(row, "latitude"), "lon": g(row, "longitude"),
            "text": prepare.scrub(str(g(row, "text") or "")),
            "photos": photos,          # image URLs — they resolve to pictures, not to a page
            "source": f"live scrape ({kind})",
        }
        sealed = {"address": blind["address"], "town": blind["town"],
                  "last_list_price": float(g(row, "list_price") or 0) or None,
                  "days_on_mls": g(row, "days_on_mls"), "mls_status": g(row, "status"),
                  "mls_id": g(row, "mls_id"), "url": g(row, "property_url")}
    else:
        r = from_csv(address)
        if not r:
            sys.exit("the scrape was blocked and this house isn't in listings.csv either.\n"
                     "try again in a minute, or run listings.py to refresh the scrape.")
        print("  (scrape unavailable — using our own listings.csv)")
        blind, sealed = prepare.build(r)
        blind["photos"] = [r["photo"]] if r.get("photo") else []
        blind["source"] = "listings.csv (offline fallback)"

    for k in ("beds", "baths", "sqft", "lot_sqft", "year_built"):
        v = blind.get(k)
        blind[k] = None if v in (None, "", "nan") else float(v)
    blind["town"] = prepare.normalise_town(blind.get("town"), blind.get("zip"))

    blob = json.dumps(blind)
    leak = prepare.MONEY.search(blob) or re.search(r"realtor\.com/realestate|zillow\.com/homedetails", blob)
    (RUN / "subject_blind.json").write_text(json.dumps(blind, indent=2))
    (RUN / "subject_sealed.json").write_text(json.dumps(sealed, indent=2, default=str))

    print(f"town    : {blind['town']}")
    print(f"shape   : {blind.get('beds') or '?'}bd {blind.get('baths') or '?'}ba "
          f"{int(blind['sqft']) if blind.get('sqft') else 'sqft n/a'} · "
          f"lot {int(blind['lot_sqft']) if blind.get('lot_sqft') else 'n/a'} · "
          f"built {int(blind['year_built']) if blind.get('year_built') else '?'}")
    print(f"photos  : {len(blind.get('photos') or [])} image urls")
    print(f"source  : {blind['source']}")
    print(f"sealed  : price + dom + url held back")
    print(f"leak chk: {'!! LEAK: ' + leak.group(0) if leak else 'clean'}")
    return 1 if leak else 0


if __name__ == "__main__":
    sys.exit(main())
