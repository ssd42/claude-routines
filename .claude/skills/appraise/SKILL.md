---
name: appraise
description: Appraise one NJ house listing — a researched value range, real recent comparable sales with what they asked and got, three offer tiers, a buy/don't-buy ruling, and a repair budget split into move-in and year-one work. Forms its view WITHOUT seeing the asking price, then says whether the ask is wrong. Use when the user asks what a house is worth, whether a listing is priced fairly, what they should offer, or whether to buy a specific house.
user-invocable: true
argument-hint: "[address, or --key <property_key>] [--photos]"
---

You are appraising **one house**, for a buyer who will walk it himself. Your job is the
part a comp formula structurally cannot do: read condition and context, and say what it
changes and why — with evidence he can check in ten seconds.

Design rationale lives in `market-history/offer/SPIKE-appraiser.md`. Read it if a
judgement call here isn't covered. The rules below are not style preferences; each one
exists because skipping it produces a confident wrong number.

## The three rules that govern everything

**1. Anchor on the comp engine. Adjust from there. Never price from scratch.**
`comps()` is calibrated against ~8,000 real NJ sales and graded in public on
`backtest.html`: median error 9.86%, and the true price lands inside its p25–p75 band
about 48% of the time against a 50% target. You have none of that in your head. If you
produce a number that isn't traceable to the anchor plus named adjustments, you have
invented it.

**2. You do not see the asking price until stage 8.** This is enforced by plumbing —
`prepare.py` drops the price, days-on-market, price-changed and the listing URL from the
blind record and scrubs dollar figures out of the prose. Do not go looking for it. Do not
fetch the Realtor page. If you learn the ask before forming your view, **say so in the
output and stop** — a leaked appraisal is worse than none, because it looks independent
and isn't.

**3. Every claim names its evidence.** "Kitchen looks 1990s — photo 4." "Seller says
'newer roof' — a claim with no date." A sentence that can't name a photo index or a
quoted phrase gets deleted, not softened.

## Run it

```bash
cd market-history/appraise

# stage 0 — PREFER fetch.py: drop any listing link (or a plain address) and it works
python3 fetch.py "https://www.zillow.com/homedetails/12-Maple-Ave-Cranford-NJ-07016/123_zpid/"
python3 fetch.py "12 Maple Ave, Cranford, NJ 07016"

# stage 0 — prepare.py is the older path: looks the house up in our own listings.csv
python3 prepare.py "12 Maple Ave" --town Cranford

python3 context.py                                     # stages 1,2,5,6 — all deterministic
python3 photos.py                                      # stage 3 survey — every photo, small
python3 photos.py --detail 5 11 17                     # stage 3 detail — the ones that matter
python3 save.py                                        # archive + write the de-identified grade row
```

**`fetch.py` is the entry point to reach for** (its own docstring: *"the version that should have
existed first"*). It takes a **Zillow, Redfin, Realtor or plain-address** input, uses the link
**only to extract an address** — nothing is fetched from the site pasted — and writes the price
straight to the sealed record. It is a **non-model process**, which is what keeps the blinding
plumbing rather than instruction. It falls back to `listings.csv` when the scrape is
rate-limited, so a house we already hold still appraises offline.

**Running more than one house in a session:** `run/` is a **single shared working directory** —
the next `fetch.py` overwrites the previous subject, and `photos.py` overwrites `run/photos/`
**in place** (the `--detail` pass replaces the survey image at the same filename, it does not
write a subdirectory). So: **finish and `save.py` each house before starting the next.** Once
archived, the images live under `appraisals/<key>/<date>/photos/` and can be re-read there — do
that rather than re-fetching when a photo claim is challenged later.

**Note the `|` in `<property_key>`** (e.g. `271valleyrd|07066`). It breaks unquoted shell paths
and IDE links — always quote it.

**Cropping is part of stage 3.** PIL is available. Small print on floor plans and small objects in
exteriors need it:
```python
from PIL import Image
im = Image.open('run/photos/16.jpg'); box = (215, 225, 415, 300)
im.crop(box).resize(((box[2]-box[0])*5, (box[3]-box[1])*5), Image.LANCZOS).save('/tmp/x.png')
```

`context.json` now holds the comp anchor with its honesty flags, three real recent sales
with ask and sold, house-level flood zone and store distances, and an estimated holding
cost. Read it. **Do not recompute any of it in your head.**

If `anchor.failed` is set, the engine could not price this house from its own town's
sales. **Do not substitute a guess.** Say "insufficient local evidence for a range" and
continue with everything else — the works estimate and the location findings don't need a
price anchor. This happens on ~13% of houses, concentrated in small expensive towns.

## Then work the stages

**Stage 3 — photos. LOOK AT ALL OF THEM BEFORE YOU PRICE ANYTHING.**

> This rule exists because of a real failure on 2026-07-21. The appraisal read 14 of 36
> photos, never opened an upstairs bedroom, and produced a confident range of $615–665k
> against a $599,900 ask — calling the house underpriced. The owner then pointed out that
> both upper bedrooms are steeply slanted Cape knee-wall rooms with built-in drawers, that
> the outlets are two-prong, and that the basement smells musty and runs a dehumidifier.
> Four more images moved the range to $565–608k. **The number was not wrong because the
> reasoning was bad. It was wrong because it was formed from 39% of the evidence.**

Non-negotiable before any range is produced:

- **Download and view every photo**, not a sample. If there are 36, look at 36.
- **You must have seen, or explicitly stated you could not find: every bedroom, every
  bathroom, the kitchen, the main living space, the basement or mechanical room, and the
  exterior front and rear.** A bedroom you did not open is not "not mentioned in the
  listing" — it is a room you failed to inspect.
- **State the count in the output**: "read 36 of 36 photos." A thin pass must be *visible*,
  never silent. If you priced off 14, say 14 and mark the range provisional.
- Pay specific attention to what listing prose systematically hides: ceiling slopes and
  knee walls in any 1.5-storey house, outlet type (two-prong means ungrounded branch
  wiring no matter how new the panel looks), visible ductwork or its absence, radiators,
  water staining, and what the mirrors reveal in adjacent rooms.

**THE FLOOR PLAN IS THE MOST VALUABLE IMAGE IN ANY GALLERY. Look for it first.**

> Added 2026-08-17. On a Clark ranch the last two images were floor-plan pages, and one line of
> small print — `TOTAL: 1316 sq. ft · 1st floor: 1010 sq. ft · EXCLUDED: BASEMENT 474…` — decided
> the entire appraisal. The listing published **no sqft**, so the comp engine fell to a lot-only
> tier and anchored at **$670,198** against a comp set of 1,357–2,344 sqft. The house is **1,010
> sqft above grade.** Nothing else in 17 photos came close to mattering as much.

- **Scan the gallery for plan pages before reading rooms.** They are usually last, often small
  files, and they frequently carry **stated square footage and every room dimension.**
- **Pull them with `--detail` and crop in.** The totals line is set in small type; at survey size
  it is unreadable. Use PIL to crop and upscale — `Image.crop().resize(..., LANCZOS)`.
- **Read the EXCLUDED AREAS line, not just the total.** NJ appraisal convention excludes
  below-grade area from headline sqft, so a marketed total that folds in finished basement is not
  the number a lender's appraiser will use. That gap is often the whole story on a flip.
- **When there is no plan, say size is unverified** and let the band stay wide. Do not reconstruct
  a number from massing and then lean on it.

**RE-PULL ANY CONDITION READ THAT ENTERS THE RANGE. The survey pass runs pessimistic.**

> Added 2026-08-17, from three errors in one session, all in the same direction — the 640px survey
> pass makes things look worse than they are:
> - Read vertical **staining** on a stucco rear; at full size most of it was **pergola shadow**.
> - Read a floor as **stripped to subfloor**; at full size it was **worn, soiled carpet**.
> - Nearly missed an **outdoor AC condenser** entirely — it was a grey smudge beside a hot tub
>   until the owner pushed back and it was cropped at 5×, revealing the louvred coil, the service
>   disconnect on the wall above and the lineset running down.

The survey pass tells you **what a room is**. It does not tell you **what condition it is in.**
Anything that becomes an adjustment must be re-pulled at `--detail` and, if still ambiguous,
cropped and upscaled. **State the correction when a detail pass reverses a survey read** — those
reversals went the seller's way twice and the buyer's way once, so the bias is real and worth
showing.

**THE STRUCTURED RECORD AND THE PHOTOS EACH LIE IN DIFFERENT DIRECTIONS.** Reconcile, don't pick:
- `ac_type` was **null on all three houses**; one of them plainly had central air. **A null column
  is "not recorded", never "not present".**
- **Do not infer fuel from an appliance.** A gas range was read as natural gas; the MLS said
  **propane**, which is a different running cost, means no gas main, and puts the *oil* tank
  question back on the table for a pre-1960 house.
- The MLS listed a **sump pump** that appears in no photograph. Absence of evidence in a gallery
  is not evidence of absence — and a sump under a *finished* basement is a major finding.

**What photographs cannot tell you, ever** — say so rather than implying otherwise:
smell, damp, noise, how a room feels at its actual size, or what is behind a finished
wall. On that same house I wrote "no visible water staining" from a basement photo and
credited the house for it; the basement smelled musty. **You cannot smell a photograph.**
Anything in that category belongs in "what would make this wrong," not in the confident
part.

Only with `--photos`. The subject's thumbnail is in the blind
record and resolves to an image, so it is safe. A full gallery means the Realtor page,
which carries the price — so a **separate fetch step** must hand you images only. If you
cannot get images without seeing the page, skip this stage and say the appraisal is
photo-blind. Never fetch the listing page yourself.
What you may conclude: "oak cabinets, laminate counters, consistent with a 1990s install
— photo 4." What you may not: a dollar figure. Costs belong to stage 9.

**Stage 4 — prose.** Mine `text` for what the columns lack: heating, central air, garage,
roof and remodel claims, "as-is", "estate sale", "handyman special". `garage` and
`ac_type` are now real columns but thin (56% and 8%), so prose is still the fallback.
**The listing is the seller's marketing — it omits problems by construction, so anything
you take from it is systematically optimistic. Say that every time.**

**Stage 5 — location.** Already computed. Flood zone and store distances are house-level
and genuinely new; transit is town-level and the packet says so. **None of these may move
the value range** — `market-history/layers/README.md` is explicit that amenity layers are
never filters or scores. They go in the narrative and the ruling.

> **Terrain, when a buyer asks about grading, drainage or a sloped yard** (added 2026-08-17).
> USGS 3DEP serves elevation through a **keyless public API**, and North Jersey returns
> **1-metre LiDAR** — fine enough to characterise a suburban lot:
> ```
> https://epqs.nationalmap.gov/v1/json?x=<lon>&y=<lat>&units=Feet&wkid=4326
> ```
> Sample a grid (`lat/lon` are in the blind record), fit a plane, and report **relief across the
> parcel** and **slope % and aspect**. On a Clark lot this returned ~4 ft of relief at a uniform
> ~4% — which settled the buyer's question, because it showed **a slope, not a mound**: nothing to
> cart away, so levelling means cut-and-fill plus retaining.
>
> **Two caveats to state every time:** 3DEP is a **bare-earth** model, so the house is filtered out
> and its footprint interpolated; and check the returned `AcquisitionDate` — the Clark tile was
> flown **2014**, so recent spoil piles or regrading are simply not in it.
>
> **This is context, not valuation.** Like every other location layer, it may not move the range.

**Stage 7 — reconcile.** Produce the range. Rules: no point estimate; every adjustment
names its evidence; a weaker comp set widens the band rather than tightening the story —
check `anchor.thinFam`, `degraded`, `eraDropped`, `famDropped`, `lotDropped`. Depart from
the comp band wherever the evidence says, including above it, and show the evidence.

**Stage 7b — adversary.** Before writing the verdict, argue against your own estimate.
Which comps were a different kind of house? Which photo inference rests on one bad angle?
What did you take from marketing as fact? **These objections ship in the output**, under
"what would make this wrong" — not resolved away.

**Stage 8 — the ask.** Now read `subject_sealed.json`. Compare, and say plainly whether
the house is mispriced in either direction.

> ### ⚠️ `days_on_mls` IS PER-MLS-NUMBER, NOT PER-PROPERTY. It understates badly.
> Added 2026-08-17. A Clark house reported **33 days**. Its real exposure was **~205 days across
> four MLS numbers and two selling campaigns**, including a listing that was **withdrawn unsold**
> and a five-month gap for a renovation. Every relist resets the counter.
>
> **This value is written into every row of `appraisal-grades/`**, so the committed track record
> currently carries a misleadingly low number on any house that has been relisted. Treat it as a
> **floor on market exposure, never a measurement.**
>
> **After unsealing, always check the full price history** before drawing any conclusion about
> why a house hasn't sold:
> - `listings.csv` → the `spell` column is our own relisting counter, but it only counts spells
>   **we have observed** — it starts at 1 for anything first seen recently.
> - `sales.csv` → prior sales of the same address. This is how a **flip** is identified, and it is
>   the single most valuable thing at stage 8: purchase price, purchase date, and what the beds/
>   baths were *then* (a "3bd/1.0ba" purchase now marketed as 2 baths tells you where the second
>   bathroom came from — and if it's below grade, it barely counts).
> - The buyer's own Zillow/Redfin history if offered — **it will contain campaigns our data never
>   saw.** Ours began mid-campaign on that Clark house and showed one price cut; the full record
>   showed nine.
>
> **Do not build a narrative on an absence in our data.** On that house an over-confident theory
> ("contracts dying at appraisal") was constructed, then retracted on partial evidence, then had
> to be un-retracted when the full history arrived. **Say what our data covers and where it stops.**
> The tell that no deal ever died: there was **no `Pending` event in either campaign** — the house
> had never gone under contract at all.

**Stage 9 — the works.** Using photos, prose and `year_built`, against
`market-history/REPAIR-COSTS-NJ.md`: what it needs to **move in**, and what it will want
**a year later**. Ranges only. Lead with the priors — a 1928 house with no updates
mentioned likely has 100-amp service, possible knob-and-tube, asbestos pipe wrap,
radiators and no AC. Flag the **oil tank separately as a gate on the ruling**, never as a
line in a total: the range runs $1,600 to $150,000+ and the sweep costs $150–500 before
you're emotionally committed.

## The output, in this order

1. **Value range** `$X–$Y`, with the anchor it started from, how many sales it stood on,
   which tier fired, and any honesty flags.
2. **2–3 real comparables** from `context.json` — address, sold date, **ask and sold**,
   the gap, and one line on what that house was.
3. **Three offer tiers**, derived from the range and nothing else:
   *a really good deal* / *what I think it's worth* / *only if you really like it*.
   **Do not subtract the works estimate here.** Stage 7 already marked the house down for
   what the photos show; stage 9 prices fixing that same thing. Subtracting both charges
   twice for one kitchen. The range is **as-is**; the works number is **cash you'll
   spend**, quoted beside it, never inside it.
4. **Ruling** — buy / don't buy / buy only if, with the conditions named.
5. **Move-in works** and **year-one works**, each a range, each line naming its evidence.
6. **What would make this wrong** — stage 7b, verbatim.
7. **Confidence** — from the comp set's flags and the photo coverage, not from how the
   writing feels. State both: "93 comps, tightest tier, no flags · read 36 of 36 photos."
8. **Photo coverage**, always, as a line of its own. A range built on a partial read is
   an opening position, not a conclusion, and the page must say which it is.

## Writing it down

Write to `market-history/appraise/appraisals/<property_key>/<date>.md` and `.json`, and
**save the images you looked at** beside them, numbered to match your citations — a
"photo 4" reference is worthless in six months when that URL is dead.

**That directory is gitignored and must stay that way.** `property_key` is literally the
address, and the file contains adverse commentary on someone's home plus the maximum this
buyer would pay. Committing it publishes both, permanently. Only the de-identified row in
`appraisal-grades/` — hashed key, town, shape, numbers, flags, pipeline version — is ever
committed.

## What you must not do

- Fetch the listing page, or look up the address on any listing site, before stage 8.
- Produce a point estimate anywhere.
- Turn "needs TLC" into a number. It will read as authoritative and it is invented.
- Let a store distance or a school rating move the value range.
- Fill a gap with a plausible guess. "Not recorded" is an answer; a made-up roof age is
  a lie that looks like data.
- **Quote a repair cost that is not in `REPAIR-COSTS-NJ.md`.** If the document has no
  section for it, say so and say what it would take to get one — that gap is itself a
  finding. This is how the damp-basement section came to be written.
- Produce a range having looked at part of the gallery. See stage 3.
