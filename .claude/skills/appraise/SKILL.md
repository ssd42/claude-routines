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
python3 prepare.py "12 Maple Ave" --town Cranford     # stage 0 — blind + sealed records
python3 context.py                                     # stages 1,2,5,6 — all deterministic
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
