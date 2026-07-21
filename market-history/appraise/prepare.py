"""Stage 0 — build the two records the appraiser pipeline runs on.

Emits `subject_blind.json` (everything the view-forming stages may see) and
`subject_sealed.json` (the price, opened only at stage 8). See SPIKE-appraiser.md §2:
blinding is PLUMBING, not an instruction. A field that must not be seen is not in the
file. There is nothing here to politely ignore.

  python3 prepare.py "12 Maple Ave" --town Cranford
  python3 prepare.py --key "12|maple|07016"
"""
import argparse, csv, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "run"

# Anything that is the ask, or reveals it. days_on_mls and price_changed are here for the
# reason §2 gives: 140 days with a cut says "overpriced" without naming a number.
BLIND_FIELDS = {"first_list_price", "last_list_price", "price_changed", "days_on_mls",
                "observations", "first_seen", "last_seen", "list_date", "gone_on", "spell",
                # `url` is the Realtor page and the ask is the biggest thing on it, so a
                # blinded stage that can fetch this link is not blinded. `mls_id` is the
                # same leak one search away. Both move to the sealed record; the photo
                # fetcher reads them from there and hands back images only, which is the
                # whole point of it being a separate non-model process (SPIKE §2).
                # `photo` STAYS: it resolves to an image, not a page.
                "url", "mls_id"}

# The prose leaks the ask constantly — "priced to sell", "$50k below assessment", the
# number itself. Scrub before a blinded stage ever sees it.
MONEY = re.compile(r"\$\s?\d[\d,]{2,}(?:\.\d+)?\s?[kKmM]?")
PRICEY = re.compile(r"\b(list(ing)? price|asking|asks?|reduced|price (improvement|drop|cut)"
                    r"|priced (to sell|below|under|at)|below (assessment|market)|new price"
                    r"|best (and )?final|motivated seller)\b", re.I)


def scrub(text):
    if not text: return ""
    t = MONEY.sub("[price removed]", text)
    t = PRICEY.sub("[price talk removed]", t)
    return re.sub(r"\s+", " ", t).strip()


def haversine_mi(a, b):
    (la1, lo1), (la2, lo2) = a, b
    R = 3958.8
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def load_listings():
    with open(ROOT / "listings.csv") as fh:
        return list(csv.DictReader(fh))


def find(rows, key=None, address=None, town=None):
    if key:
        hits = [r for r in rows if r["property_key"] == key]
    else:
        a = re.sub(r"\s+", " ", (address or "").lower()).strip()
        hits = [r for r in rows if a and a in r["address"].lower()
                and (not town or r["town"].lower() == town.lower())]
    active = [r for r in hits if r.get("status") == "active"]
    return active or hits


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def build(row):
    """Split one listing into what the blinded stages see and what stays sealed."""
    blind = {k: v for k, v in row.items() if k not in BLIND_FIELDS and v not in ("", None)}
    blind["text"] = scrub(row.get("text"))
    # town-grain holding cost. §8: an estimate on an estimate, and it says so.
    tax = {}
    tp = ROOT / "layers" / "tax" / "tax_by_town.csv"
    if tp.exists():
        for t in csv.DictReader(open(tp)):
            if t["town"] == row["town"]:
                tax = {"effective_rate_pct": num(t.get("effective_rate_pct")),
                       "town_avg_bill": num(t.get("avg_residential_tax")),
                       "note": "town-grain: rate x our value estimate. NOT this house's "
                               "bill. Verify on the listing."}
    blind["tax"] = tax

    sealed = {"property_key": row["property_key"], "address": row["address"],
              "town": row["town"],
              "last_list_price": num(row.get("last_list_price")),
              "first_list_price": num(row.get("first_list_price")),
              "price_changed": row.get("price_changed"),
              "days_on_mls": row.get("days_on_mls"),
              "mls_status": row.get("mls_status"),
              "url": row.get("url"), "mls_id": row.get("mls_id")}
    return blind, sealed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address", nargs="?")
    ap.add_argument("--town")
    ap.add_argument("--key")
    a = ap.parse_args()
    if not (a.address or a.key):
        sys.exit("give an address or --key")

    rows = load_listings()
    hits = find(rows, a.key, a.address, a.town)
    if not hits:
        sys.exit("no listing matches. it may have sold or never been scraped.")
    if len(hits) > 1:
        print("several match — narrow with --town or --key:", file=sys.stderr)
        for r in hits[:12]:
            print(f"   {r['address']:<34} {r['town']:<16} {r['property_key']}", file=sys.stderr)
        sys.exit(1)

    row = hits[0]
    blind, sealed = build(row)
    OUT.mkdir(exist_ok=True)
    (OUT / "subject_blind.json").write_text(json.dumps(blind, indent=2))
    (OUT / "subject_sealed.json").write_text(json.dumps(sealed, indent=2))

    # A URL in the blind record is a price the model can go and read, so it counts as
    # a leak exactly like a dollar figure does.
    blob = json.dumps(blind)
    leak = MONEY.search(blob) or re.search(r"realtor\.com|zillow\.com|redfin\.com", blob)
    print(f"subject : {row['address']}, {row['town']}")
    print(f"key     : {row['property_key']}")
    print(f"shape   : {blind.get('beds','?')}bd {blind.get('baths','?')}ba "
          f"{blind.get('sqft') or 'sqft n/a'} lot {blind.get('lot_sqft') or 'n/a'} "
          f"built {blind.get('year_built','?')}")
    print(f"extras  : garage={blind.get('garage') or '-'} ac={blind.get('ac_type') or '-'}")
    print(f"blinded : price, dom, price_changed, seen dates removed; text scrubbed")
    print(f"leak chk: {'!! LEAK IN BLIND RECORD: ' + leak.group(0) if leak else 'clean'}")
    print(f"wrote   : {OUT}/subject_blind.json, subject_sealed.json")
    return 1 if leak else 0




def normalise_town(town, zipcode=None):
    """The feed gives the TOWNSHIP ("Bernards Twp"); our comps are keyed on the name we
    use ("Basking Ridge"). Without this, comps() matches nothing and every scraped house
    refuses. Resolve via the zip map we already ship, then fall back to the raw name."""
    import json as _json
    t = (town or "").strip()
    p = ROOT / "offer" / "data.js"
    if p.exists():
        d = _json.loads(p.read_text().split("window.OFFER_DATA =")[1].rstrip().rstrip(";"))
        towns, z2t = d.get("towns", {}), d.get("zipToTown", {})
        # ZIP FIRST, and the order matters. Several tracked towns are sections of a larger
        # township -- Colonia inside Woodbridge, Basking Ridge inside Bernards, Towaco
        # inside Montville -- and the feed reports the TOWNSHIP. Checking the name first
        # meant a Colonia house (07067) came back "Woodbridge", because Woodbridge is also
        # a tracked town so the name matched and the zip was never consulted. Those are
        # different markets with different comps; the zip is the more specific signal and
        # goes first.
        if zipcode and str(zipcode)[:5] in z2t:
            return z2t[str(zipcode)[:5]]
        if t in towns:
            return t
        cleaned = re.sub(r"\s+(Twp|Township|Boro|Borough|City|Village)\.?$", "", t, flags=re.I)
        if cleaned in towns:
            return cleaned
    return t


if __name__ == "__main__":
    sys.exit(main())
