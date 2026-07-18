#!/usr/bin/env python3
"""Average residential PROPERTY TAX per town, from NJ DCA's annual Property Tax Tables.

    python3 layers/tax/fetch_tax.py

Writes layers/tax/tax_by_town.csv -- one row per town: the AVERAGE RESIDENTIAL TAX BILL
and the EFFECTIVE (equalized) tax rate. This is a town-grain layer (an attribute of a
place), same contract as seabra/transit/education: keyed on `town`, ships as its own file,
joined at share/build time, NEVER a filter or a merge into a sales file.

WHY THIS MATTERS. In NJ, effective rates swing ~1.4%-3.3% by town; on a $700k house that
is ~$10k vs ~$23k a YEAR -- often a bigger monthly-cost swing than the mortgage-rate or
commute differences already on the map. It was the biggest omission.

SOURCE. NJ Dept of Community Affairs (DCA), Division of Local Government Services, "<yy>
Property Tax Tables" -- the authoritative per-municipality file, published annually:
  https://www.nj.gov/dca/dlgs/resources/Property_Tax/<YY>_data/<YY>taxes.xls
Sheet "Municipal Tax Summary", one row per municipality (565 of them). Columns used:
  1  Municipality              2  County
  30 Average Total Property Taxes (the avg residential BILL, $)     <- the headline number
  39 CY Total EQ Rate           (equalized/effective rate per $100) <- estimate YOUR bill:
                                                                        price * rate / 100
  29 Average Residential Property Value (assessed; context only)

LOCAL PREP, like listing_scrape. The DCA file is binary .xls (BIFF), so parsing needs
`xlrd` (pip install xlrd) -- a data-prep dependency, NOT a runtime one. CI/build only ever
read the committed CSV. Re-run this by hand when DCA publishes a new year; bump TAX_YEAR.

SECTIONS. 11 of our towns are CENSUS sections of a township, not municipalities of their
own (Colonia in Woodbridge, Short Hills in Millburn, Basking Ridge in Bernards...). A
section pays its PARENT township's rate, so it inherits the parent's row -- same as the
school layer. SECTION_MAP names each parent (with county, since NJ reuses town names).
"""
import csv
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
ZIPS = os.path.join(ROOT, "zips.json")
OUT = os.path.join(HERE, "tax_by_town.csv")

TAX_YEAR = 25   # DCA file year (2025 tables); bump when a newer year is published
SRC = f"https://www.nj.gov/dca/dlgs/resources/Property_Tax/{TAX_YEAR}_data/{TAX_YEAR}taxes.xls"
RAW = os.path.join(HERE, f"{TAX_YEAR}taxes.xls")   # gitignored transient source

C_MUNI, C_COUNTY, C_VALUE, C_BILL, C_EQRATE = 1, 2, 29, 30, 39

# our section towns -> the parent municipality (exact DCA name) they inherit, same county
SECTION_MAP = {
    "Colonia": "Woodbridge Township", "Short Hills": "Millburn Township",
    "Gillette": "Long Hill Township", "Stirling": "Long Hill Township",
    "Millington": "Long Hill Township", "South Orange": "South Orange Village Township",
    "Martinsville": "Bridgewater Township", "Basking Ridge": "Bernards Township",
    "Cedar Knolls": "Hanover Township", "Towaco": "Montville Township",
    "Long Valley": "Washington Township",
}

SUFFIX = re.compile(r"\s+(city|borough|boro|township|twp|town|village)\.?$", re.I)


def bare(name):
    return SUFFIX.sub("", str(name).strip().lower()).strip()


def main():
    import xlrd   # local prep only; see module docstring

    if not os.path.exists(RAW):
        print(f"downloading {SRC}")
        req = urllib.request.Request(SRC, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(RAW, "wb") as fh:
            fh.write(r.read())

    sh = xlrd.open_workbook(RAW).sheet_by_name("Municipal Tax Summary")
    # lookups: exact "Muni, County" (for sections) and bare-name+county (for the rest)
    by_exact, by_bare = {}, {}
    for r in range(2, sh.nrows):
        muni = str(sh.cell_value(r, C_MUNI)).strip()
        county = str(sh.cell_value(r, C_COUNTY)).strip()
        if not muni or not county:
            continue
        rec = {"muni": muni, "county": county,
               "bill": sh.cell_value(r, C_BILL), "rate": sh.cell_value(r, C_EQRATE),
               "value": sh.cell_value(r, C_VALUE)}
        by_exact[(muni, county.lower())] = rec
        by_bare[(bare(muni), county.lower())] = rec

    towns = json.load(open(ZIPS))["towns"]
    rows, miss = [], []
    for t in towns:
        name, county = t["name"], t["county"]
        section = name in SECTION_MAP
        rec = (by_exact.get((SECTION_MAP[name], county.lower())) if section
               else by_bare.get((bare(name), county.lower())))
        if not rec:
            miss.append(name)
            print(f"  MISS  {name} ({county})")
            continue
        bill = rec["bill"]
        if not (isinstance(bill, (int, float)) and bill > 0):
            miss.append(name)
            continue
        rows.append({
            "town": name, "county": county,
            "avg_residential_tax": round(bill),
            "effective_rate_pct": round(rec["rate"], 3),   # per $100 of market value
            "avg_residential_value": round(rec["value"]),
            "dca_municipality": rec["muni"],
            "is_section": int(section),
        })

    rows.sort(key=lambda x: x["town"])
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote tax_by_town.csv  {len(rows)}/{len(towns)} towns  "
          f"({sum(r['is_section'] for r in rows)} inherited a parent township)")
    print(f"  source: DCA 20{TAX_YEAR} Property Tax Tables, Municipal Tax Summary")
    if miss:
        print(f"  MISSING ({len(miss)}): {', '.join(miss)} -- resolve by hand")


if __name__ == "__main__":
    main()
