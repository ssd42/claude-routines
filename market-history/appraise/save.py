"""Archive one finished appraisal, and record a de-identified row for grading.

    python3 save.py

Two destinations, and the split is the whole point (SPIKE-appraiser.md §12):

  appraisals/<property_key>/<date>/    GITIGNORED. The readable verdict, the context, the
                                       sealed record, and the images actually looked at,
                                       numbered to match the "photo 4" citations. Kept
                                       forever, locally, because a citation into a dead
                                       Realtor URL is worthless in six months.

  appraisal-grades/<date>.jsonl        COMMITTED. Numbers only, subject key HASHED. This
                                       is what the backtest grades later. property_key is
                                       literally "75|lancaster|07067" — the address — so it
                                       never leaves this machine in the clear.
"""
import hashlib, json, shutil, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "run"


def main():
    ctx = json.loads((RUN / "context.json").read_text())
    sealed = json.loads((RUN / "subject_sealed.json").read_text())
    blind = json.loads((RUN / "subject_blind.json").read_text())
    vp = RUN / "verdict.json"
    if not vp.exists():
        sys.exit("no verdict.json — nothing to archive yet")
    v = json.loads(vp.read_text())

    key = blind.get("property_key") or f"{blind['address']}|{blind.get('zip','')}"
    key = key.lower().replace(" ", "")
    stamp = date.today().isoformat()
    dest = HERE / "appraisals" / key / stamp
    dest.mkdir(parents=True, exist_ok=True)

    for f in ("verdict.json", "context.json", "subject_blind.json",
              "subject_sealed.json", "report.html"):
        if (RUN / f).exists():
            shutil.copy2(RUN / f, dest / f)
    photos = RUN / "photos"
    n_photos = 0
    if photos.exists():
        shutil.rmtree(dest / "photos", ignore_errors=True)
        shutil.copytree(photos, dest / "photos")
        n_photos = len(list((dest / "photos").glob("*.jpg")))

    anc = ctx.get("anchor") or {}
    rng = v.get("range") or [None, None]
    row = {
        "date": stamp,
        # hashed: the plain key IS the street address
        "subject": hashlib.sha256(key.encode()).hexdigest()[:12],
        "town": ctx["subject"].get("town"),
        "beds": ctx["subject"].get("beds"), "baths": ctx["subject"].get("baths"),
        "sqft": ctx["subject"].get("sqft"), "year_built": ctx["subject"].get("year_built"),
        "property_type": ctx["subject"].get("property_type"),
        "range_lo": rng[0], "range_hi": rng[1],
        "point": (rng[0] + rng[1]) / 2 if rng[0] and rng[1] else None,
        "comp_mid": anc.get("mid"), "comp_lo": anc.get("lo"), "comp_hi": anc.get("hi"),
        "comp_n": anc.get("n"), "comp_tier": anc.get("tier"),
        "comp_failed": bool(anc.get("failed")),
        "flags": [k for k in ("degraded", "lotDropped", "eraDropped", "famDropped",
                              "thinFam", "borrowed", "noSize") if anc.get(k)],
        "ask": sealed.get("last_list_price"),
        "days_on_mls": sealed.get("days_on_mls"),
        "works_move_in": (v.get("works", {}).get("move_in", {}) or {}).get("total"),
        "works_year_one": (v.get("works", {}).get("year_one", {}) or {}).get("total"),
        "photos_seen": n_photos,
        "photos_available": len(blind.get("photos") or []),
        "revisions": v.get("revisions", 1),
        "pipeline_version": "0.1.0",
        "model": "claude-opus-4-8",
        # filled in later, when the house actually sells — this is what makes the
        # whole archive a track record instead of a folder of opinions
        "outcome": None,
    }
    grades = HERE / "appraisal-grades"
    grades.mkdir(exist_ok=True)
    with open(grades / f"{stamp}.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")

    print(f"archived : {dest}")
    print(f"  files  : verdict, context, blind, sealed, report, {n_photos} photos")
    print(f"  photos : {n_photos} of {row['photos_available']} available "
          f"({n_photos/max(1,row['photos_available'])*100:.0f}% coverage)")
    print(f"grade row: {grades / (stamp + '.jsonl')}  (subject hashed, no address)")
    print(f"  range  : ${rng[0]:,} – ${rng[1]:,}   ask ${row['ask']:,.0f}"
          if rng[0] else "  range  : none")


if __name__ == "__main__":
    main()
