"""The REAL tax bill for one address, from the NJ MOD-IV parcel record.

    from parcel import lookup
    rec = lookup("324 Green St", "Woodbridge", "07095")

WHY THIS EXISTS. Holding cost used to be an ESTIMATE ON AN ESTIMATE: the town's
effective tax rate multiplied by our own value estimate. That is two guesses stacked,
and in a town that has not revalued it is not even the right quantity -- Woodbridge
bills ~12.7 per $100 of ASSESSED value against Cranford's ~6.8, because Woodbridge's
assessed base is frozen in 1986 dollars and Van Decker bars a sale-triggered
reassessment. Multiplying a 2026 price by a rate cannot see that. It is the whole
reason 384 Maplewood pays ~$3k less than 496 Outlook with an extra room.

MOD-IV carries `LAST_YR_TX`: the ACTUAL DOLLAR AMOUNT BILLED on that parcel. Measured
2026-08-27 it is populated on 100% of qualifying sale rows in both Woodbridge and
Cranford. It is on the same statewide endpoint aggregate.py already queries every run,
so this costs one small request and is cloud-safe (no key, public gov data).

(We missed it for weeks because grepping the field list for "TAX" does not match
"LAST_YR_TX". It had been sitting there the entire time.)

SOLD vs ACTIVE. sales.csv only holds houses that have SOLD, and an appraisal subject is
by definition still on the market -- so the bill cannot come from our own CSVs. It has
to be looked up against the parcel table by address, which is what this does.

MATCHING IS DELIBERATELY STRICT. A wrong parcel is far worse than no parcel: it would
hand back a confident, precise, real-looking number for the house next door. So we
require an exact normalised (house-number, street) match and REFUSE on ambiguity --
`None` is a fine answer and the caller falls back to a clearly-labelled estimate.
"""
import json
import os
import re
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir)
MUNIS = os.path.join(ROOT, "nj_municipalities.json")

ENDPOINT = ("https://maps.nj.gov/arcgis/rest/services/Framework/Cadastral"
            "/MapServer/0/query")
FIELDS = ("PROP_LOC,PAMS_PIN,LAST_YR_TX,NET_VALUE,LAND_VAL,IMPRVT_VAL,"
          "PROP_CLASS,YR_CONSTR,BLDG_DESC,DEED_DATE,SALE_PRICE")

# Street-type and directional spellings collapsed to one token, so "324 Green St" from
# the listing feed matches "324 GREEN STREET" on the deed. Same intent as aggregate.py's
# address_key -- copied, not imported: appraise is a consumer of this routine's data and
# the two normalisers are allowed to drift (root CLAUDE.md, independence rule).
_ABBR = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "lane": "ln", "court": "ct", "place": "pl", "terrace": "ter", "terr": "ter",
    "boulevard": "blvd", "circle": "cir", "parkway": "pkwy", "highway": "hwy",
    "trail": "trl", "way": "way", "square": "sq", "plaza": "plz", "crescent": "cres",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
}
_UNIT = re.compile(r"\b(apt|unit|ste|suite|#)\s*[\w-]+\b", re.I)


def norm_street(s):
    """'324 GREEN STREET, Unit 2B' -> ('324', 'green st')."""
    s = _UNIT.sub(" ", str(s or "").lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t]
    if not toks:
        return None, ""
    num = toks[0] if toks[0].isdigit() else None
    rest = toks[1:] if num else toks
    rest = [_ABBR.get(t, t) for t in rest]
    return num, " ".join(rest)


# The normalised street-type tokens _ABBR can produce, plus the ones already short.
_TYPES = {"st", "ave", "rd", "dr", "ln", "ct", "pl", "ter", "blvd", "cir",
          "pkwy", "hwy", "trl", "way", "sq", "plz", "cres"}


def _drop_type(street):
    """'outlook ave' -> 'outlook'. Empty if the name IS only a type token."""
    toks = street.split()
    while toks and toks[-1] in _TYPES:
        toks.pop()
    return " ".join(toks)


def _municipality(town):
    """Our town label -> the (COUNTY, MUN_NAME) MOD-IV knows it by.

    Section towns (Colonia in Woodbridge, Short Hills in Millburn) are not
    municipalities and are filed under the parent township -- the same
    `section_of` relationship aggregate.py uses.
    """
    with open(MUNIS) as fh:
        cfg = json.load(fh)
    units = cfg["municipalities"] if isinstance(cfg, dict) else cfg
    for u in units:
        if u.get("town") == town:
            return u.get("county"), u.get("mun")
    return None, None


def _query(county, mun, num, street_head, timeout=30):
    # Narrow server-side by house number + the first street word, then match exactly in
    # Python. A LIKE on the whole normalised string would miss every spelling variant,
    # which is the thing we are trying to survive.
    esc = street_head.replace("'", "''").upper()
    where = (f"COUNTY='{county}' AND MUN_NAME='{mun}' AND PROP_CLASS='2' "
             f"AND PROP_LOC LIKE '{num} {esc}%'")
    params = {"where": where, "outFields": FIELDS, "returnGeometry": "false",
              "f": "json", "resultRecordCount": "50"}
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return [f["attributes"] for f in json.load(resp).get("features", [])]


def lookup(address, town, zip_code=None, timeout=30):
    """The parcel record for one address, or None.

    Returns None -- never a guess -- when the town is unknown, the network fails, or
    the address does not match exactly one parcel. The caller is expected to fall back
    to a labelled estimate, so a miss is safe and a MISMATCH would not be.
    """
    num, street = norm_street(address)
    if not num or not street:
        return None
    county, mun = _municipality(town)
    if not county or not mun:
        return None
    try:
        recs = _query(county, mun, num, street.split()[0], timeout=timeout)
    except Exception:
        return None                      # offline / endpoint down -> fall back quietly

    parsed = [(a, norm_street(a.get("PROP_LOC"))) for a in recs]
    hits = [a for a, (pn, ps) in parsed if pn == num and ps == street]

    # Second pass: same house number, same street NAME, different street TYPE.
    # Listings get the suffix wrong constantly -- the subject "496 Outlook Rd" is
    # "496 OUTLOOK AVE" on the deed, and refusing that would throw away a real bill over
    # a word neither party is careful about. Still gated on a UNIQUE hit, so a township
    # that genuinely has both a 496 Outlook Rd and a 496 Outlook Ave stays a refusal.
    if not hits:
        head = _drop_type(street)
        if head:
            hits = [a for a, (pn, ps) in parsed
                    if pn == num and _drop_type(ps) == head]

    if len(hits) != 1:
        return None                      # 0 = no such parcel, >1 = ambiguous. Refuse both.

    a = hits[0]

    def pos(v):
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    return {
        "prop_loc": a.get("PROP_LOC"),
        "pams_pin": a.get("PAMS_PIN"),
        "tax_billed": pos(a.get("LAST_YR_TX")),
        "assessed_value": pos(a.get("NET_VALUE")),
        "land_value": pos(a.get("LAND_VAL")),
        "imprvt_value": pos(a.get("IMPRVT_VAL")),
        "year_built": pos(a.get("YR_CONSTR")),
        "bldg_desc": (a.get("BLDG_DESC") or "").strip() or None,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("usage: python3 parcel.py '<address>' '<town>'")
    print(json.dumps(lookup(sys.argv[1], sys.argv[2]), indent=2))
