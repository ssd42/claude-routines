# SPIKE — resolve a listing's town from its *location*, not its ZIP

**Status:** proposal. Nothing built. Writing-only, per the ask.

**Ask:** stop labelling a house's town by its ZIP code. ZIP `08812` is mapped to
Green Brook, so all **66** listings in it — including the ones physically in
**Dunellen** — are stamped "Green Brook". Dunellen isn't in our town list at all, so
it has nowhere else to land. Fix the labelling, migrate the data we already have
without a re-scrape, and prove the migration didn't break anything downstream. Plus a
second idea folded in at §8: let a thin town borrow comps from its ZIP-neighbours,
weighted lower.

**Verdict: yes — and the fix is a backfill, not a re-scrape, because we already keep
`lat`/`lon` on 94% of listings.** But "resolve from the point" has three sharp edges
the naïve version walks straight into (some of our "towns" aren't municipalities;
mailing-city is *also* wrong, not just ZIP; a borrowed coordinate is a centroid, not a
rooftop). All three are below, and the testing plan (§7) is the real deliverable — the
whole point is to change 3,900 labels *without silently moving the ones that were
already right*.

---

## 1. The bug, precisely

`listings.py:273` writes `"town": zip_town.get(obs["zip"], "")`, where `zip_town` is a
**one-ZIP-→-one-town** map built first-wins from `zips.json` (same shape as
`aggregate.py:zip_to_town()`). So the town is a property of the *ZIP*, not the house.

```
ZIP 08812  →  "Green Brook"   (first-wins label in zips.json)
   ├─ 1121 N Washington Ave   → really Dunellen   → stamped "Green Brook"  ✗
   ├─ 1074 Shadowlawn Dr      → really Dunellen   → stamped "Green Brook"  ✗
   └─ 106 Greenbrook Rd       → really Green Brook → stamped "Green Brook"  ✓ (by luck)
```

66 listings, all "Green Brook", an unknown split of them actually Dunellen. We keep
`lat`/`lon` on 64 of the 66 — so the ground truth to fix this is *already in the CSV*.

The file already knows this failure mode exists: it hand-patches `07006` (three
Caldwells) and `07960` (two Morristowns) in `_zip_label_rule`. `08812` is the third
case — and the worst, because it doesn't pick the wrong *member* of a shared ZIP, it
invents a membership (Dunellen → Green Brook) across a county line.

## 2. Root cause — ZIP is not municipality, and neither is mailing-city

A ZIP is a USPS mail-delivery route. A municipality is a legal boundary. The relation
is **many-to-many**:

- **one ZIP, many towns** — `08812` delivers to Dunellen borough *and* part of Green
  Brook Twp (Green Brook has no post office of its own; it's split across `08812` and
  `07059`).
- **one town, many ZIPs** — handled on the way in (`towns[].zips` is a list), then
  thrown away by the first-wins reverse map.

The important, non-obvious corollary: **mailing-city is wrong the same way ZIP is.**
A Green Brook house in `08812` has USPS city "Dunellen". So `homeharvest`'s `city`
field — the obvious "just use the city they gave us" fix — carries the identical
defect, merely in the other direction. **The only authoritative answer is the
coordinate against a legal boundary.** That single fact drives the whole design.

## 3. The fix — a resolution chain, best evidence first

Keep ZIP as the **fetch/crawl unit** (unchanged; `listings.py` still loops ZIPs).
Change only how the town is *assigned* to a row, via a confidence-ordered chain:

| tier | source | when | confidence | `town_source` |
|---|---|---|---|---|
| 1 | **point-in-polygon** — `(lat,lon)` in NJ municipal boundary | 94% of rows | authoritative | `polygon` |
| 2 | **`homeharvest` city** (needs a new column — we don't store it today) | no coords | low — shares the mailing-boundary flaw (§2) | `city` |
| 3 | **ZIP first-wins label** (today's behaviour) | no coords, no city | last resort | `zip` |
| — | **MOD-IV `MUN_NAME`** (deed rows, `aggregate.py`) | already authoritative | authoritative | `mun_deed` |

**Add a `town_source` column** to `listings.csv` (and, for symmetry and auditing, to
the merged sales). It is the same honesty contract as the seasonal index's `borrowed`
flag: never state a town you can't stand behind without saying how you got it. The
page can grey a `zip`/`city`-sourced town the way it greys a pending listing.

**The one new ingredient: municipal boundary polygons.** We hold only
`layers/geo/zip_centroids.json` today. We need NJ municipal boundaries as GeoJSON
(NJGIN / NJ Office of GIS publishes "Municipal Boundaries of NJ", ~565 features,
public/cloud-safe — same provenance class as `nj_records`). Clip to our counties to
keep it small. It lands in `layers/geo/` as a new town-grain reference file; it is
config-grade reference data, not a sale layer, so it never enters the scrape merge.

Point-in-polygon over ~3,900 points is milliseconds with a bounding-box pre-filter; a
tiny ray-casting function in stdlib is enough (no shapely — cloud image is
stdlib-only, and shapely is a heavy dep for one predicate).

## 4. Sharp edge #1 — half our "towns" aren't municipalities

This is the edge that breaks a naïve point-in-polygon and it must be designed for, not
discovered in prod. Several target "towns" are **sub-municipal**:

- **`section_of` CDPs** — Basking Ridge (part of Bernards Twp), Colonia (Woodbridge),
  Cedar Knolls & Towaco (Hanover/Montville). Municipal polygons resolve these to their
  *parent*, erasing a distinction we deliberately track (`CLAUDE.md` "section_of"
  note, currently subset by the dirty `ZIP5`).
- Point-in-polygon against municipal boundaries would silently collapse Basking Ridge
  → "Bernards Township". That's a *different* wrong answer, not a fix.

**Design response:** resolution returns the **legal municipality**, and a second,
optional **section refinement** runs only for the handful of `section_of` towns, using
a CDP polygon (Census publishes CDP boundaries) or, failing that, the existing ZIP
subsetting kept explicitly as the section rule. The canonical identity of a row is
`(municipality, section?)`. Our display "town" is the section when one applies, else
the municipality. This has to be spelled out in `zips.json` per town, replacing the
implicit first-wins map with an explicit `municipality` + optional `section` per entry.

Net: `zips.json` stops being "ZIP → label" and becomes "here are the municipalities
(and sections) we target, and the ZIPs to crawl for each." The ZIP list stays; its job
shrinks to *crawl target only*.

## 5. Points of failure (the ones that will actually bite)

1. **Borrowed coordinates.** Realtor sometimes returns a ZIP- or street-centroid, not
   a rooftop point. A ZIP-centroid for a shared ZIP resolves to whichever municipality
   the centroid happens to sit in — reintroducing the exact bug, invisibly. **Detect
   it:** flag rows whose `(lat,lon)` equals (within ε) a known ZIP centroid, or where
   many rows in a ZIP share one point; downgrade those to `town_source=zip` rather than
   trusting a fake `polygon`. This is the failure most likely to pass tests and still
   be wrong.
2. **Name reconciliation.** Boundary source ("Green Brook Township"), MOD-IV
   (`GREEN BROOK`), and our list ("Green Brook") must map to one canonical key. Suffix
   noise (Township/Boro/Borough/City/Twp), the two Caldwells vs North/West, "Township
   of X" ordering. A bad join here mislabels *everything* in a town, so the canonical
   map is itself a tested artifact (§7), not a runtime `.replace()`.
3. **Points in water / on a border / in a polygon gap.** Coastal or riverside points
   can fall outside every polygon. Resolution must *refuse* (drop to tier 2/3 + flag),
   never snap to "nearest polygon" — nearest is how you label a house across the river.
4. **Non-target municipalities appearing.** Once honest, points resolve to
   municipalities we don't target (Dunellen, Piscataway…). Today they're silently
   absorbed; after the fix they're visible. Policy decision required (§9): keep as
   first-class, keep as "other", or drop — but *explicitly*.
5. **Boundary drift.** NJ municipal consolidations are rare but real (e.g. Princeton
   2013). The boundary file has a vintage; record it in the file's `_source`, same as
   every layer, and a stale file is a known, dated limitation, not a mystery.
6. **The 6% with no coordinate** never improve past tier 2/3. They are exactly the
   rows most likely to be mislabeled and least likely to be caught — so they must be
   *countable* (a `town_source` histogram in the build log) and visibly flagged, not
   averaged into confidence silently.

## 6. Migration — backfill, don't re-scrape

The whole point: we don't need a residential-IP fetch to fix history.

1. **Add the resolver** (`resolve_town(lat, lon, zip, city) -> (town, source)`), the
   boundary file, and the canonical name map.
2. **Backfill `listings.csv` in place:** for every existing row, recompute `town` from
   coordinates; write the new `town` and a new `town_source`; **keep the old value in
   an audit sidecar** (`state/town_migration.json`: `property_key → {old, new,
   source}`) so the change is reversible and reviewable before anyone trusts it.
   Idempotent and additive, like every other run here.
3. **Re-bake** `offer/listings.js` from the corrected CSV (`build_data.py`, no network).
4. **Deed side:** `MUN_NAME` already wins, so `sales.csv` towns shouldn't move —
   assert that (§7a). Stamp them `town_source=mun_deed` for symmetry.
5. **Rebuild `share/`** (`build_share.py`) so `by_town.csv` and the amenity/transit
   joins pick up the corrected town set. New target municipalities (if Dunellen goes
   in) need a `dist_mi` and an amenity row, or they render blank — decide in §9.

No new scrape. `listings.py`'s *writer* changes for future runs; the *history* is
repaired by the backfill over data we already committed.

## 7. Testing — the actual deliverable

Changing 3,900 labels is only safe if we can prove which ones *should* move and that
the rest didn't. Five layers, cheapest first.

### 7a. Invariants — "past assumptions still hold" (must be 0 or it's a bug)
- **Row count conserved.** `n(before) == n(after)` for `listings.csv` and `sales.csv`.
  Migration relabels; it never drops or adds a row.
- **Deed towns frozen.** Every `mun_deed` row's town is byte-identical before/after.
  If a deed town moved, the resolver is overreaching into authoritative data.
- **Whitelist closure.** Every resulting town is a known municipality or a declared
  `section_of`. Zero towns outside the canonical set. (This alone would have caught
  "Green Brook" holding Dunellen — Dunellen would have appeared and failed closure.)
- **Determinism.** Same `(lat,lon)` → same town across two runs and across the two
  code paths (listings resolver vs any deed cross-check). No coordinate resolves two
  ways.
- **No silent centroids.** Count of `polygon`-sourced rows that sit on a ZIP centroid
  is 0 (or all such rows are downgraded to `zip`). Guards failure #1.

### 7b. Correctness — a golden set (hand-labelled, committed as a fixture)
20–30 addresses with their *true* municipality, chosen to hit every trap:
- the `08812` split (Dunellen borough addresses vs Green Brook Twp addresses must
  resolve to **different** towns — the headline assertion);
- both shared-ZIP patches (`07006` three Caldwells, `07960` two Morristowns);
- a `section_of` (Basking Ridge must stay Basking Ridge, **not** Bernards Township);
- a riverside/edge point that *should* refuse to tier 2;
- a known-rooftop and a known-centroid coordinate.
Assert resolver output == hand label (or == "refuse" for the edge case).

### 7c. Reconciliation — "calculations still compute, and shifts are explained"
The risk isn't just wrong labels; it's a *comp bucket silently changing membership*.
- **Per-town comp counts, before vs after.** Every delta must be attributable to
  relabeled rows: `Δcount(town) == +arrivals − departures` from the audit sidecar.
  An unexplained swing = a resolver bug.
- **Unaffected towns are byte-identical.** A town that gained/lost no rows must
  produce an identical `by_town.csv` row and identical comp output. (Diff the
  regenerated `share/` against the prior commit; only affected towns may differ.)
- **No town silently crosses the THIN line the wrong way.** Flag any town that was
  ≥THIN before and is <THIN after (we just made a working comp bucket refuse) — that's
  acceptable only if the departures were genuinely mislabeled, and the sidecar proves
  which.

### 7d. A free correctness oracle — cross-source agreement
Where a **listing and a deed exist for the same property** (`property_key` ∩
`address_norm`), `polygon(listing)` and `MUN_NAME(deed)` are two independent answers to
the same question. Every disagreement is either a boundary/name bug or a MOD-IV quirk —
log them all. This costs nothing (both datasets are in hand) and is the strongest test
we have: the deed record is the ground truth the boundary must match.

### 7e. Regression guard, going forward
Commit a small fixture of `(lat,lon)` → expected town and a stdlib test that runs the
resolver over it. A boundary-file swap or a refactor that moves a town then fails
loudly instead of shipping a silent relabel. This is what turns the spike into
something that stays fixed.

**Acceptance:** 7a all zero; 7b all pass incl. the 08812 split; 7c every delta
explained by the sidecar; 7d disagreements reviewed and each attributed; 7e green.

## 8. Folded-in idea — let a thin town borrow ZIP-neighbours, weighted lower

Your instinct is right and it connects directly: **"Green Brook" is *already* an
accidental, unflagged, unweighted borrow** — it's been pricing Dunellen houses into
Green Brook's bucket this whole time. §1–7 make the pooling *stop being secret*. §8
then does the same pooling *on purpose*: correctly, down-weighted, and flagged.

There's a precedent to copy exactly: the seasonal index already borrows the regional
curve when a town is too thin and sets `borrowed=true` so the page can say so
(`engine.js:indexIsBorrowed`). Comps should borrow the same way.

**The mechanism:**
- When a town's own bucket is below `THIN`, widen the pool to **neighbour towns**,
  each comp down-weighted by `w < 1`.
- Replace the plain median/quartiles (`quart()`) with a **weighted** quantile so an
  own-town sale counts fully and a borrowed one counts partially.
- Gate on **effective sample size** (Σ weights), not raw count, with a **floor on
  own-town count** so we never price a town *entirely* off neighbours without saying
  so. `borrowed`/`famDropped` already exist as flags to model this on.
- Surface it on the row: *"12 comps — 4 from Dunellen (neighbour), weighted 0.5;
  treat loosely"*, the same register as "no sq ft on this listing — treat loosely".

**"Same ZIP" is the right *strongest* tier but too narrow on its own.** Two towns
share a ZIP precisely because they're adjacent (they share a post office) — so
same-ZIP is a principled, high-weight neighbour signal. But most thin towns *don't*
share a ZIP with anyone, so same-ZIP alone helps only the shared-ZIP handful. Generalise
to **nearest-N towns by centroid distance** (we already have `zip_centroids.json`),
with same-ZIP as the top weight tier and distance-decay below it.

**The real risk to design around: borrowing imports a different price level.** Green
Brook (Somerset) and Dunellen (Middlesex) share `08812` but sit at different $/sqft.
Naïve pooling biases the estimate toward the neighbour. So borrow the **shape**
($/sqft distribution), then **re-anchor** to the target town — the same move the
borrowed seasonal index makes (borrow the curve, apply it to this town's level). A
town-level offset or a $/sqft rescale, not a raw price pool. **This is the part to
prototype and validate before trusting, and it is *downstream* of the migration** —
you cannot honestly borrow across "towns sharing a ZIP" until the town labels are
correct. Migration first; weighted borrowing second.

**It stays a nice-to-have, never a filter** (`layers/README.md` contract): a borrowed
estimate colours a row and is flagged; it never removes or hard-ranks a house.

## 9. Open questions — decide before building

1. **Is Dunellen (and other newly-visible municipalities) in or out?** Today they're
   laundered into a neighbour. Once resolved honestly they appear as themselves, with
   no `dist_mi`, no amenity row, no deed sales (we don't query them in `nj_records`).
   Options: promote to first-class targets (add to crawl + deed + `dist_mi` + amenities),
   bucket as "other / not a target town", or drop. **This is the one product call that
   blocks the rest** — the migration surfaces these rows no matter what; we just choose
   their label.
2. **CDP boundaries for `section_of`, or keep the ZIP-subset rule?** Census CDP
   polygons are cleaner but add a second boundary file and more name-reconciliation.
   The existing ZIP subset is dirty (per `CLAUDE.md`) but known. Prototype both on
   Basking Ridge.
3. **Backfill in place, or write a parallel `town_v2` column first?** In-place with an
   audit sidecar is cleaner long-term; a shadow column lets both run side-by-side for a
   week before cutting over. I lean in-place + sidecar (reversible, and the sidecar
   *is* the diff), but it's a public repo and this churns `listings.csv`.
4. **Boundary source of record.** NJGIN municipal boundaries vs Census TIGER county
   subdivisions — both public/cloud-safe. Pick one, pin its vintage in `_source`.
5. **Weighted-borrow: ship with the migration, or as a follow-on?** They're separable.
   The migration is a correctness *fix*; the borrow is a coverage *feature* that
   depends on it. I'd land and verify the migration alone (§7 green), *then* build §8
   against corrected data — otherwise you're validating a borrow on labels you're
   simultaneously changing.

## 10. Scope

| step | what | note |
|---|---|---|
| 1 | boundary file → `layers/geo/nj_municipal_boundaries.json` (+ vintage) | new cloud-safe reference |
| 2 | `resolve_town()` + canonical name map + centroid-coordinate detector | stdlib ray-cast, no shapely |
| 3 | rework `zips.json`: explicit `municipality`/`section`/crawl-`zips` per town | replaces first-wins map |
| 4 | backfill `listings.csv` (+ `town_source`, + `state/town_migration.json` sidecar) | idempotent, reversible |
| 5 | `build_data.py` re-bake; `build_share.py` rebuild `share/` | no network |
| 6 | tests 7a–7e incl. committed golden + regression fixtures | the deliverable |
| 7 | market page: grey/annotate non-`polygon` towns; decide Q1 rendering | honesty stamp, reused |
| 8 | *(follow-on)* weighted ZIP-neighbour borrow + weighted quantile + row flag | after §7 green |

**Estimate:** migration itself is **small–medium** — the resolver is tiny, the boundary
join is standard, and there's no re-scrape. The cost is entirely in §4 (sections), §5
(centroid detection + name reconciliation) and §7 (proving it). The weighted borrow is a
**separate medium** and should not ride in on the migration's commit.

## 11. The thing that worries me

The migration will make the data *more correct* and some numbers *move* — a town's
comp count changes, a median shifts, a house you were watching relabels. If we can't
point at the audit sidecar and say *"these 41 Dunellen rows left Green Brook, here they
are"*, a correct fix will read as a regression. **So the sidecar and 7c (every delta
explained) aren't optional polish — they're how a correctness fix survives contact with
someone who trusted the old, wrong number.** Same discipline as the rest of the tool:
when the answer changes, show your work.
