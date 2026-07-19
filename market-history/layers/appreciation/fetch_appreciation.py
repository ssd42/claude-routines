#!/usr/bin/env python3
"""Per-town home-price APPRECIATION, a CONSENSUS of two independent mix-controlled indexes.

    python3 layers/appreciation/fetch_appreciation.py

Writes layers/appreciation/appreciation_by_town.csv -- one row per town: appreciation over a
~3-year window, reconciled from the two credible sources, plus each source so the number is
auditable.

WHY A CONSENSUS. Appreciation is the metric people read hardest on the map, so one source is
not enough. Three were checked:
  * Zillow ZHVI (by ZIP)      -- smoothed "typical home value" index. Covers all 63 towns.
  * FHFA HPI (by ZIP)         -- repeat-transactions index (the same homes over time). ~61/63.
  * our own 40k sold records  -- REJECTED: raw median $/sqft is mix-dominated noise (Verona
                                 read -1%/yr, Scotch Plains +14% -- the same mix-shift the
                                 internal size-controlled index exists to avoid). Not a source.
Zillow and FHFA both control for mix and agree within ~3 pts/yr, but FHFA runs ~2 pts higher
(methodology). Neither is ground truth, so we AVERAGE the two (annualized) -- a 2-source
reconciliation, the same discipline the sales pipeline uses. Each source and the spread are
kept in the CSV, so a big disagreement is visible, not laundered into one confident number.

SOURCES (both free, key-less):
  Zillow ZHVI: https://files.zillowstatic.com/research/public_csvs/zhvi/
               Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv   (~120 MB, monthly)
  FHFA HPI:    https://www.fhfa.gov/hpi/download/annual/hpi_at_zip5.xlsx  (~40 MB, annual)

LOCAL PREP, like the tax layer: big downloads + an .xlsx parse (needs openpyxl). Runs by
hand; commits only the tiny per-town CSV. CI/build read that CSV, never this file.

METHOD. Everything is reduced to an ANNUALIZED rate so the two windows are comparable, then
averaged; the displayed total is that blended rate compounded over WINDOW_YEARS.
  * Zillow: latest month vs the same month WINDOW_YEARS earlier, per ZIP, avg over a town's ZIPs.
  * FHFA:   latest annual HPI vs WINDOW_YEARS earlier, per ZIP, avg over a town's ZIPs.
"""
import csv
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, os.pardir, os.pardir)
ZIPS = os.path.join(ROOT, "zips.json")
OUT = os.path.join(HERE, "appreciation_by_town.csv")

ZHVI_RAW = os.path.join(HERE, "zhvi_zip.csv")       # gitignored (~120 MB)
FHFA_RAW = os.path.join(HERE, "hpi_at_zip5.xlsx")   # gitignored (~40 MB)
ZHVI_URL = ("https://files.zillowstatic.com/research/public_csvs/zhvi/"
            "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv")
FHFA_URL = "https://www.fhfa.gov/hpi/download/annual/hpi_at_zip5.xlsx"
WINDOW_YEARS = 3


def _download(url, path, label):
    if os.path.exists(path):
        return
    print(f"downloading {label}\n  {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as fh:
        fh.write(r.read())


def zillow_annualized():
    """zip -> annualized rate over the last WINDOW_YEARS, and the end month label."""
    _download(ZHVI_URL, ZHVI_RAW, "Zillow ZHVI (~120 MB)")
    with open(ZHVI_RAW) as f:
        rd = csv.reader(f)
        hdr = next(rd)
        zi, si = hdr.index("RegionName"), hdr.index("State")
        months = [i for i, h in enumerate(hdr) if h[:2] == "20" and "-" in h]
        end_i = months[-1]
        end_m = hdr[end_i]
        start_pref = f"{int(end_m[:4]) - WINDOW_YEARS}{end_m[4:7]}"
        start_i = next((i for i in months if hdr[i].startswith(start_pref)), months[0])
        out = {}
        for row in rd:
            if row[si] != "NJ":
                continue
            try:
                s, e = float(row[start_i]), float(row[end_i])
            except ValueError:
                continue
            if s > 0 and e > 0:
                out[row[zi]] = (e / s) ** (1 / WINDOW_YEARS) - 1
    return out, end_m


def fhfa_annualized():
    """zip -> annualized rate over the last WINDOW_YEARS from FHFA ZIP5 HPI (or {} on failure)."""
    try:
        import openpyxl
        _download(FHFA_URL, FHFA_RAW, "FHFA HPI ZIP5 (~40 MB)")
        rows = list(openpyxl.load_workbook(FHFA_RAW, read_only=True).active.iter_rows(values_only=True))
    except Exception as e:
        print(f"  ! FHFA unavailable ({e}); Zillow-only")
        return {}
    hpi = {}   # zip -> {year: HPI}
    for r in rows[6:]:
        if r[0] is None or r[1] is None or r[3] is None:
            continue
        hpi.setdefault(str(r[0]).zfill(5), {})[int(r[1])] = float(r[3])
    latest = max(y for h in hpi.values() for y in h)
    out = {}
    for z, h in hpi.items():
        a, b = latest - WINDOW_YEARS, latest
        if a in h and b in h and h[a] > 0:
            out[z] = (h[b] / h[a]) ** (1 / WINDOW_YEARS) - 1
    return out


def main():
    import json
    import statistics as st

    zill, end_m = zillow_annualized()
    fhfa = fhfa_annualized()
    towns = json.load(open(ZIPS))["towns"]

    rows, miss = [], []
    for t in towns:
        zr = [zill[z] for z in t["zips"] if z in zill]
        fr = [fhfa[z] for z in t["zips"] if z in fhfa]
        za = st.mean(zr) if zr else None
        fa = st.mean(fr) if fr else None
        parts = [x for x in (za, fa) if x is not None]
        if not parts:
            miss.append(t["name"])
            continue
        blend = st.mean(parts)                       # annualized consensus
        total = (1 + blend) ** WINDOW_YEARS - 1       # compounded to the ~3yr total shown
        rows.append({
            "town": t["name"],
            "appr_pct": round(100 * total, 1),        # blended TOTAL over the window (map value)
            "appr_annual_pct": round(100 * blend, 1),
            "zillow_annual_pct": round(100 * za, 1) if za is not None else "",
            "fhfa_annual_pct": round(100 * fa, 1) if fa is not None else "",
            "n_sources": len(parts),
            "spread_pts": round(100 * (max(parts) - min(parts)), 1) if len(parts) > 1 else 0,
            "window_years": WINDOW_YEARS,
            "asof": end_m,
        })

    rows.sort(key=lambda x: x["town"])
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    both = sum(1 for r in rows if r["n_sources"] == 2)
    sp = st.median([r["spread_pts"] for r in rows if r["n_sources"] == 2])
    print(f"\nwrote appreciation_by_town.csv  {len(rows)}/{len(towns)} towns")
    print(f"  {both} blended (Zillow+FHFA), {len(rows)-both} Zillow-only  | median source spread {sp} pts/yr")
    print(f"  window: {WINDOW_YEARS}yr, as of {end_m}")
    if miss:
        print(f"  MISSING ({len(miss)}): {', '.join(miss)}")


if __name__ == "__main__":
    main()
