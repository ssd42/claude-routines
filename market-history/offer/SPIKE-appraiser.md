# SPIKE — the appraiser: hand it one listing, get a researched verdict

**Status:** proposal. Nothing built. Expands the TODO card
*"A skill that appraises one listing, and says why"*, and absorbs
*"Estimate what a favourited house will need"* (see §11 — I think they're one skill).

**Ask:** give it one listing and get back a thorough, *researched* appraisal — not a
model answering from memory. It goes and looks things up, in as many steps and
subagents as it takes: comps in the same town first, neighbours second; the features
that actually move a price; the photos; how close it is to things; a value **range**;
2–3 real houses that sold nearby in the last year with **what they asked and what they
got**; three offer tiers; a buy/don't-buy ruling; and a repair budget for move-in and
for a year later. And it must form its view **without ever seeing the asking price**,
then turn around and tell you whether the ask is wrong.

**Revised 2026-07-21 after a design review.** Eleven findings applied: the condition
double-count between the value range and the works estimate (§6), a blinding hole that
exempted the photo stage (§2), a containment rule that forbade the very adjustment the
skill exists to make (§3 stage 7), per-address appraisals in a public repo (§12), an
undefined grading metric and an underpowered sample (§9), plus cost, versioning, key
stability and two factual corrections. Where a decision reversed, the old position is
left visible with the reason — the reasoning is the useful part.

**Verdict: yes — this is the strongest idea on the board, and it is buildable today.
But four of the ten things asked for are not in any dataset we hold, and one of them
(number of prior sales) cannot be faked.** Those are in §7, stated plainly, because a
spike that promises columns we don't have produces a skill that invents them.

---

## 1. The one design decision everything else follows from

**Anchor on the comp engine. Adjust from there. Never price from scratch.**

`engine.js:comps()` is not a heuristic somebody sketched — it's calibrated against
tens of thousands of real NJ sales and graded in public on `backtest.html`. Its
p25–p75 band is *designed* to catch the true price about half the time, and the page
shows live whether it actually does. Its median miss is **9.86%**, down from 10.70%
after the three fixes shipped 2026-07-21 (`TODO.md` → Done).

An LLM asked "what's this house worth" produces a confident number from nothing. It
has no NJ sales in front of it, so it reaches for a plausible-looking figure and
dresses it in reasoning. That number would be *worse* than 9.86% and would not know it.

So the division of labour is fixed:

| | |
|---|---|
| **comps() gives** | the anchor, the band, the tier it had to widen to, whether it borrowed from next door, how many sales it stood on |
| **the skill gives** | the part comps structurally cannot see — condition, road noise, a 1990s kitchen, an original bath, the walk to the station — as an **adjustment with named evidence** |

`TODO.md` already says exactly this and it is right: *"Comps say $720k; the photos show
an original kitchen and it faces a four-lane road, so call it $660–690k, and here's the
evidence for each."*

**Why this matters more than it sounds:** the backtest's own conclusion is that the
residual error *is* condition — "the age ramp only flattened a quarter, and none of the
six worst misses moved. That residual is condition, and condition is not in this data."
Identical houses on paper sold $438k to $951k in one town. The skill is aimed at
precisely the gap the formula has proven it cannot close. That's the whole case for it.

### Reconciling "don't consider the asking price" with the comp anchor

These are compatible, and it's worth being explicit because it looks like a conflict.

`comps()` values a subject off *other houses' sold prices* — `c[4]`, the sold price,
rescaled by $/sqft. **The subject's own ask is never an input.** So anchoring on comps
is not anchoring on the ask. The instruction is satisfied by construction on the
quantitative side; §4 is about enforcing it on the *narrative* side, which is where it
would actually leak.

⚠️ Note the tension with the other board card, *"Stop competing with the asking
price — use it."* That card argues the ask carries most of the signal and we should
predict the *gap*. **These are different products and both should exist.** The
ask-anchored model answers "is this listed right"; the appraiser answers "what is this
worth, independent of what they want for it" — which is the number you need before you
decide what to offer. Building the appraiser does not block that card; it produces the
independent view the gap model would be graded against.

---

## 2. Blinding has to be mechanical, not a promise in a prompt

**If a stage can see the ask, it will anchor on it.** Telling a model "please ignore
the $749,000" is the single least effective instruction in this entire design — the
number is now in its context and every subsequent token is conditioned on it.

So blinding is a **plumbing** property, not a prompt property:

- The stages that form the view (§3, stages 1–6) are handed a **redacted listing
  record**. `last_list_price` and `first_list_price` are *dropped from the dict before
  it's serialised* — not marked "do not read".
- `text` is the seller's prose and it frequently contains the price, "priced to sell",
  "$50k below assessment", and similar. **`text` must be price-scrubbed** by regex
  before it reaches a blinded stage: any `$` figure above ~$50,000, plus
  `list price`, `asking`, `reduced`, `price improvement`.
- `days_on_mls`, `price_changed`, `observations` and `first_seen`/`last_seen` are
  **also blinded**. A house 140 days on market with `price_changed=1` tells you the ask
  is too high without stating it — that's the ask leaking through the back door.
- **The photo stage is the hard case, and an earlier draft of this spike got it wrong.**
  It said the subject's `url` was "fine" because fetching it is post-blind by definition —
  which quietly exempted *the single most important stage* from the rule this whole section
  exists to enforce. Stage 3 produces the condition adjustment; §1 says that adjustment is
  the entire reason to build this. A stage that sees the ask in 48pt type at the top of the
  Realtor page will anchor on it exactly as §2 predicts.
  **So the fetch is a separate, non-model process.** It pulls the gallery, discards the
  DOM, and hands the vision stage **image bytes and nothing else** — no page text, no
  caption, no price. Enforceable the same way the `text` scrub above is: the price is not
  in the payload, so there is nothing to ignore. If a fetcher cannot strip the page, the
  photo stage does not run.
- Only **stage 8** opens the sealed envelope. It receives the formed view *as text it
  cannot change* plus the ask, and its only job is to compare them.

**The verdict artefact should record both**: the blind estimate and the post-ask
commentary, timestamped separately. If we ever suspect leakage, the grader in §9 will
show it as an estimate suspiciously hugging the ask.

> **Practical consequence:** this is why the skill is a **pipeline**, not one long
> prompt. You cannot blind a single context window from itself.

---

## 3. The pipeline

Eleven stages (0–9, plus the adversary at 7b). Each names what it may see. Stages 2–6 fan out to subagents and run
concurrently; everything before stage 8 is blind to the ask.

```
  0  intake        listing row + redaction        →  subject.json (blinded)
  ─────────────────────────────────────────────────────────────────── BLIND
  1  anchor        comps() on the subject         →  band, tier, n, borrowed?
  2  comp-set      subagent per comparable (×3)   →  what each really was
  3  photos        subagent, vision               →  condition, dated/renovated, evidence
  4  prose         subagent, text mining          →  systems, age claims, "as-is" tells
  5  location      subagent, lat/lon + layers     →  road, rail, flood, walk, amenities
  6  holding cost  subagent, tax layer            →  estimated annual carry
  7  reconcile     all of the above               →  VALUE RANGE + adjustments + reasons
  7b adversary     subagent, tries to break 7     →  what would make this wrong
  ─────────────────────────────────────────────────────────────────── ASK REVEALED
  8  vs. the ask   sealed view + list price       →  "poorly listed?" + three tiers
  9  works         photos + REPAIR-COSTS-NJ.md    →  move-in works, year-one works
```

**Stage 0 — intake and redaction.** Takes a `property_key` or `mls_id` from
`listings.csv` (4,542 live rows). Builds two records: `subject_blind.json` (§2) and
`subject_full.json`, which stays sealed until stage 8. Also computes what the row
doesn't carry: `sqft` is on only **28.9%** of live listings, so most subjects arrive
sizeless and the engine's lot-only path does the work (`lot_sqft` **71.7%**,
`year_built` **80.8%**, `beds` **92.4%**, `baths` **92.7%**).

**Stage 1 — anchor.** Run `comps()` exactly as `analyser.html` does. Capture not just
`mid/lo/hi` but the honesty fields the engine already emits and the page already
prints: `tier`, `n`, `degraded`, `lotDropped`, `eraDropped`, `famDropped`, `thinFam`,
`borrowed`, `borrowedComps`. **These are inputs to the reconciler, not footnotes.** A
`thinFam` result (6–9 sales, coverage ~38% against a target 50%) deserves a *wider*
final range; a clean `t1` set of 30 deserves a tighter one. If comps refuse outright,
the skill says so and the whole appraisal is downgraded to "insufficient local
evidence" — it does **not** substitute its own guess.

*Same town first, neighbours second — already true and already correct.* `comps()`
never crosses a town line on its own; `compsBorrow()` is the explicit secondary rung,
capped at **5 neighbours within 8 miles**, weight decaying with distance
(`BORROW_NEIGHBOURS`, `BORROW_MAX_MI`, `BORROW_MIN_W`), and it re-anchors borrowed
sales onto *this* town's price shelf rather than importing the neighbour's level. The
owner's requirement #1 is the engine's existing behaviour; the skill's job is to
**report which rung fired**, because "we had to borrow from Warren" is material.

**Stage 2 — one subagent per comparable.** Pick the 3 nearest-in-shape recent sales
from the comp set and send one agent each to establish what that house actually *was*:
its listing text if we hold an `mls_id`, its ask, its sold price, its days on market,
and whether it was renovated or tired. This is the stage that turns a row of numbers
into "that one had a new kitchen and still went 3% under ask."

**Stage 3 — photos.** The condition stage, and the reason this beats a formula. See
§5 — it is also the most constrained stage in the design.

**Stage 4 — prose.** `text` is on **93.0%** of live listings. Mine it for what our
columns don't have: heating type, central air, garage count, roof age claims, remodel
claims, "as-is", "estate sale", "handyman special", "newer roof" (a claim with no
date — treat as a claim, never a fact). **`TODO.md`'s weakness #1 governs this stage:
the listing is the seller's marketing, it omits problems by construction, so anything
derived from prose is systematically optimistic and must say so every time.**

**Stage 5 — location, and this is genuinely new.** `lat`/`lon` are on **94.6%** of
live listings. Every location number the pages show today is **town-grain** — the
Wawa, the Trader Joe's, the Seabra, the commute are identical for every house in the
town (`layers/README.md`: *"town-to-store, not house-to-store"*). With coordinates we
can compute **this house** to **that station / that four-lane road / that flood
polygon** for the first time. `layers/geo/` and `layers/flood/` are already here.

⚠️ **But it stays a flag, never a price adjustment** — for the reason
`SPIKE-market.md` §6a already worked out: our **sold** rows carry no coordinates
(`sales.csv` has no `lat`/`lon` at all), so we cannot measure what a track-adjacent
house sells for. We can say *"80m from the NEC"*; we cannot say *"−$40k for it."*
The reconciler may widen its range downward on that evidence and must label it a
judgement, not a measurement.

⚠️ **And amenities never touch what a house is WORTH.** That is the line in
`layers/README.md` §60–74, and the only sanctioned exception is HS, which is taste.
Seabra/TJ/Wawa distance goes in the *narrative* ("groceries are 4 miles away"), never
into the value range. Proximity to a **station** and to a **highway/rail** is a
different animal — that's a physical property of the house, not a preference — but
with no geocoded sold comps we still can't price it, so it lands in the same bucket:
say it, don't spend it.

**Stage 6 — holding cost.** See §8. Taxes are town-grain only, so this stage produces
an *estimate with the word "estimate" welded on*.

**Stage 7 — reconcile.** The only stage that writes a number. Takes the anchor and
every subagent's findings and produces **a range**, with each adjustment carrying the
photo or the phrase it came from. Rules: no point estimates; every adjustment named
and sourced; a weaker comp set (stage 1's flags) widens the band rather than tightening
the story; and **any departure from the comp band names its evidence.**

⚠️ An earlier draft required the final range to *contain* the comp band. That was wrong
twice over. The band is p25–p75 — half of all outcomes fall outside it by construction —
so containment forces the output to be at least as wide as the comps and, with a "widen
when in doubt" default, straight to a range too broad to make an offer against. And a
gut-renovated house genuinely belongs **above p75**, which containment makes structurally
unreachable. The rule is about justification, not geometry: move wherever the evidence
says, and show the evidence.

**Stage 7b — the adversary.** A subagent whose only instruction is *try to refute this
estimate.* It gets the range and the evidence and hunts for: comps that were actually a
different kind of house, photo inferences that are one bad angle, prose taken as fact,
a `borrowed` or `thinFam` set being read as solid. Its output ships in the verdict as
**"what would make this wrong."** This is cheap, it is the highest-value stage per
token, and it's the structural version of the project's oldest rule.

**Stage 8 — the ask.** Now, and only now, the price. Reports the gap, and whether the
house is poorly listed in either direction. Emits the three tiers (§6).

**Stage 9 — the works.** §10.

---

## 4. What it may weigh — feature by feature, against what we actually hold

The owner named eleven things. Here they are honestly scored. Sources: I read
`listings.csv` (4,542 rows) and `sales.csv` (47,207 rows) directly.

| feature | live listing | sold comps | how the skill gets it |
|---|---|---|---|
| beds | ✅ 92.4% | 57.8% | column |
| baths | ✅ 92.7% | 57.7% | column |
| house sqft | ⚠️ **28.9%** | 37.2% | column when present; else lot-only comps |
| lot sqft | ✅ 71.7% | 85.5% | column — and comps already filter on it (`LOT_TOLS`) |
| year built | ✅ 80.8% | 96.0% | column — comps already match era (`ERA_TOLS` 15y→30y→dropped) |
| central air | ❌ **no column** | 5.7% (`ac_type`) | prose + photos only |
| heating | ❌ **no column** | ❌ none | prose + photos only |
| garage (count / bays) | ❌ **no column** | 54.5% (`garage`) | prose + photos only on the subject |
| roof rebuilt when | ❌ **nowhere** | ❌ nowhere | prose claim or photo, never a fact |
| remodelled when | ❌ **nowhere** | ❌ nowhere | prose claim or photo, never a fact |
| prior sale count | ❌ **impossible today** | ❌ | see §7 |
| property taxes | ❌ per-house | ❌ | town-grain estimate only, §8 |
| overall appeal | — | — | photos, §5 |
| proximity | ✅ lat/lon 94.6% | ❌ no coords | §3 stage 5 — flag, not adjustment |

**The pattern is the point:** everything the comp engine already uses is a real column
with decent fill; everything the owner wants *added* is either prose, a photo, or
absent. That is exactly why this is a skill and not a code change. Rules and regex
cannot weigh *"charming original details"*; a model can, and can name the phrase it
inferred from, which is what makes the answer checkable.

---

## 5. The photos — the best stage and the most constrained

This is the stage that justifies the whole build, and it has three hard limits.

**a) We hold exactly one image per listing.** `photo` (95.1%) is a single thumbnail
URL. One exterior shot tells you the roof line, the siding, the setback, the driveway,
the street — genuinely useful, and enough to say "the exterior is tired". It tells you
nothing about the kitchen, which is where most of the condition variance lives.

**b) More photos means fetching the Realtor listing page** (`url`, 95.6%). And
`CLAUDE.md` records that **`listing_scrape` 403s datacenter IPs — local only.** So the
photo-heavy stages **cannot run in the cloud routine, ever.** This is not a preference,
it's the same constraint that keeps `sales.csv` hydration on the owner's laptop.

**c) Sold comps have no images at all.** `sales.csv` carries no `photo` and no `url`.
The owner asked to look at *images of comparable houses* — to do that we'd have to
re-fetch each comp's Realtor page by `mls_id`, which is present on **66.1%** of sales
in the last 12 months. So: possible, local-only, one fetch per comp, and it fails
outright on a third of them.

> **Design position:** photos are **opt-in and per-house**, not part of every run.
> `--photos` fetches the subject's gallery; `--photos-comps` additionally fetches the
> comps'. Default is the single thumbnail. That keeps the common case fast and cloudable
> and reserves the expensive path for a house you're serious about — which matches the
> owner's own phrasing: *"for a few houses, actually look at the images."*

**What a photo stage may and may not conclude.** May: "the kitchen has oak cabinets and
laminate counters, consistent with a 1990s install — photo 4". May not: "the kitchen
needs $31,000 of work" *as a photo finding*. The cost belongs to stage 9, off
`REPAIR-COSTS-NJ.md`, and it comes out as a range. Every photo claim names its photo
index. A claim that can't name one gets dropped.

---

## 6. The output contract

Verbatim to what was asked, in this order. This is the artefact; nothing else ships.

1. **Value range.** `$X – $Y`. Never a point. Alongside it: the comp anchor it started
   from, how many sales that stood on, which tier fired, and whether it borrowed.
2. **2–3 real comparables sold in the last ~12 months**, each with **ask and sold**,
   the gap in %, days on market, and one line on what that house was.
   ✅ **Ask and sold are both guaranteed here, and an earlier draft got this wrong.**
   It warned that only 66.2% of sales since 2025-07-01 carry both a list and a sold
   price. True of the raw sales file — and irrelevant at this point in the pipeline,
   because these comparables come from the **comp set**, and `build_data.py:114` skips
   any row whose `sold_vs_ask_pct` is null. Every comp the engine will hand us therefore
   has both prices by construction. The 66.2% figure only bites if we ever source a
   comparable from outside `comps()`, which §3 stage 2 does not.
3. **Three offer tiers**, in his words:
   - **"a really good deal"** — buy below this and you're winning
   - **"exactly what I think it's worth"** — the centre of the range
   - **"above this, only if you really like it"** — the stretch

   These derive **from the blind range and from nothing else** — not the ask, and *not*
   the works estimate. Good ≈ the low end, fair ≈ the centre, stretch ≈ the high end.
   Tune the exact placement on the backtest, don't hand-wave it.

   ### ⚠️ Why the works estimate is NOT subtracted here — the double-count

   An earlier draft set *good ≈ the low end minus the works floor*. That charges you
   twice for the same kitchen, and it is the most expensive error this design could
   ship: **stage 7 already marked the value down** for the dated kitchen it saw in the
   photos, and **stage 9 then prices fixing that same kitchen.** Subtract one from the
   other and a $31k minor-kitchen remodel comes off a $700k house twice — 4.5%, about
   half the total error budget the comp engine operates in.

   So the contract, and every stage is built to it:

   | | |
   |---|---|
   | **The value range is AS-IS** | what this house, in the condition the photos show, is worth today. Condition is *already* priced in. |
   | **The works numbers are CASH** | what you will additionally spend. Shown beside the range, never arithmetic on it. |

   That keeps §11's comparison intact and makes it sharper, not weaker: a $700k as-is
   house needing $80k and a $760k as-is house that's done are both honestly valued, and
   the works lines tell you the cash difference between living in them. If you want an
   all-in figure, it is stated as its own labelled number — *"$700–740k, plus $60–95k of
   work to move in"* — and never folded back into the range or the tiers.
4. **Ruling.** Buy / don't buy / buy only under conditions — with the conditions named
   ("subject to a tank sweep and a Level 2 chimney inspection").
5. **Move-in works** and **year-one works**, each a range, each line naming its
   evidence. §10.

Plus, always: **"what would make this wrong"** from stage 7b, and a **confidence** that
reflects the comp set's honesty flags, not the model's mood.

---

## 7. What was asked for that the data cannot support

Stated plainly, because the alternative is a skill that hallucinates these.

### a) Number of sales since the house was built — **not available, and not fudgeable**

`market-history/CLAUDE.md` on `nj_records`: *"Holds the latest sale per parcel → a home
sold twice in the window shows once."* One row per parcel, most recent deed only. There
is no prior-sale field anywhere in `sales.csv`.

**What it would take:** the state's **SR1A annual sales files**, which carry full
history. That is already a board card — *"Find what the same house sold for last time"*,
sized **large**, and described there as *"the biggest missing ingredient"* and *"the
highest ceiling on this list."* It is a new source to pull and merge, not an afternoon.

**Worth saying why it matters — and why it is explicitly NOT this skill's problem.** A
prior sale price is the same house with the same kitchen and the same roof, so it encodes
condition rather than guessing at it. Tempting to make this skill wait for it.

**Decided 2026-07-21: it doesn't.** Two reasons. Houses turn over about **1.9% a year** —
of 4,542 live listings we hold a prior sale for **401 (9%)**, and even a ten-year pull
would reach roughly a third. So it is a minority feature, not a foundation, and building
the skill around a column that is blank for two thirds of houses would be designing for
the exception. Second and more simply: **the skill reads what the pipeline already
hydrates on its normal cadence, and adds no sources of its own.** If a prior-sale column
appears later it is one more input to stage 4, and nothing in this design has to change
to use it.

### b) Roof rebuild date — **nowhere in any dataset**

Not in `listings.csv`, not in `sales.csv`. Only routes: the listing says *"newer roof"*
(a claim with no date, per `REPAIR-COSTS-NJ.md`), or the photo shows shingle condition,
or a municipal permit lookup. **Permits would be the real answer** — NJ towns publish
construction permit records, and a roof permit is dated and public. That's a genuine new
source and a candidate spike of its own; it would also settle remodels (below) and would
catch the thing `REPAIR-COSTS-NJ.md` flags as expensive and knowable: **how many shingle
layers are up there**, a $1,000–$3,000 swing, and two layers means tear-off is mandatory.

### c) Remodel dates — **same story**

Photos and prose only. `REPAIR-COSTS-NJ.md` is blunt that *"charming original details"*
often means an untouched 1940s kitchen. A permit feed would fix this properly.

### d) Central air, heating type, garage bays on a **live** listing — **prose only**

`sales.csv` has `garage` (54.5%) and `ac_type` (5.7%) — those are *sold* rows, and
`CLAUDE.md` notes ac_type is best-effort text mining already. **`listings.csv` has
none of the three as columns.** So for the house you're actually buying, these come
from the description and the photos, at prose-level confidence. Given the owner
specifically ties AC and heating to holding cost, this is a real gap and worth naming
every single run.

**Cheapest fix available:** `listings.py` already fetches these listings; HomeHarvest
exposes more description-derived fields than we currently persist. **Before building
the skill, check whether garage/AC/heat can simply be *added as columns* at fetch
time.** If they can, that's an afternoon and it removes an entire class of guessing.
Do that first.

### e) Images of comparable sold houses — **possible but local-only and lossy**

§5c. No `photo`/`url` on `sales.csv`; requires a per-comp Realtor fetch keyed on
`mls_id`, present on 66.1% of recent sales, from a residential IP.

---

## 8. Property taxes — he's right that they matter, and here's the honest version

The ask: taxes should count, because what a house *offers* (central air, heating,
garage) interacts with what it *costs to hold*. That's a genuinely good instinct and
nothing in the tool does it today.

**What we have:** `layers/tax/tax_by_town.csv` — **75 towns**, with
`avg_residential_tax`, `effective_rate_pct`, `avg_residential_value`. Town-grain, from
NJ DCA, refreshed yearly (`CLAUDE.md`). Basking Ridge: avg $14,733, effective rate
1.605%, avg assessed $873,237.

**What we don't have:** this house's assessment, and therefore this house's bill. Two
houses in one town with the same rate pay wildly different amounts.

**So the honest derivation is:** `estimated annual tax ≈ effective_rate_pct ×
(the comp-derived value estimate)`. That is defensible — the effective rate is exactly
the ratio of tax to market value, which is what makes it the right multiplier — but it
is **an estimate built on an estimate**, and it must be labelled as such every time.
The real number is on the listing or the town's tax record; the skill should say
*"verify on the listing — this is derived."*

**Where it belongs in the output:** in the **holding-cost** paragraph and, if anywhere,
in the *ruling* — never in the value range. Two reasons. First, a town's tax level is
already priced into that town's sale prices, so subtracting it again double-counts.
Second, it's town-grain, and `layers/README.md`'s contract is unambiguous: town-grain
data ships as its own file, is a nice-to-have, and never becomes a score or a filter.
**Taxes inform whether you want it and what you can afford monthly. They do not move
what it's worth.**

> Nice concrete output, and new: *"$785k ask, ~1.605% effective → roughly $12,600/yr,
> about $1,050/mo on top of the mortgage. No central air; adding it is $10–25k because
> it's a radiator house (REPAIR-COSTS-NJ, radiators section)."* That single sentence is
> the interaction he described, and it's computable today.

---

## 9. How we'd know it's any good

**Run it on houses that already sold, with the outcome hidden.** `backtest.html`
already does exactly this for the comp engine, and the same trick works here with no
new machinery.

The design:

- Sample sold houses from the last 12 months that carry `mls_id` (66.1%) so the
  listing page and photos can be re-fetched **as they were**.
- Feed the skill the listing, blind to both the ask *and* the sale price.
- Compare **the skill's range** against **comps() alone** on the same house.

**The metric has to be defined before anyone spends money, and an earlier draft
contradicted itself here.** §6 says the output is a range and *"never a point"* — you
cannot compute a median absolute error against an interval. Both are needed and they
answer different questions:

| | |
|---|---|
| **`point`** in the JSON | the centre of the range, carried for grading only. §6's no-point rule is about what the human reads, not what the file stores. Graded against the engine's **9.86%** median absolute error. |
| **coverage + width** | did the true price land in the range, and how wide did the range have to be to catch it. A range that catches 90% by being $400k wide has not beaten a band that catches 48% at $90k. |

**Grade it PAIRED, not as two separate medians.** Compare skill-versus-comps *on the
same house* and test the sign of the difference. This matters enormously at this sample
size: the engine's own era change was a 0.63pt move that only became defensible through
a paired bootstrap and a sign test over 1,352 rows.

⚠️ **And be honest about what a small sample can detect.** Per-house absolute error on
this data has a standard deviation around 14pt. Unpaired at n=100, the 95% interval on
median error is roughly ±3pt — **and the improvement we are hunting is 1–2pt.** So an
unpaired read at this sample size can detect a catastrophe and not much else. Paired
testing recovers most of that power because the two estimates share the house, the town
and the market. **State the detectable effect before running it**, and if the answer is
"we could not tell a 1.5pt win from noise", that is worth knowing before the bill, not
after.

**Three things this grades that nothing else can:**
1. Does the photo stage *actually* pick up condition, or does it just add noise with
   confident prose attached?
2. Does blinding hold? An estimate that hugs the ask suspiciously well is leakage.
3. Do the three tiers mean anything — did houses offered at the "good deal" tier
   actually trade there?

**Measure the cost of one appraisal before designing anything around it.** Nine stages
with fan-out to six subagents, some of them vision — nobody has written down what a
single run costs, and that number decides whether the 50–100 house grade below is a
rounding error or a real bill. It also decides §13's cut of batch mode, which is
currently argued on intuition. **Run one house, record the tokens, put the figure in
this document.** It is an hour's work and it governs three other decisions.

⚠️ **Two honest caveats.** (a) Re-fetching an old listing gets today's page, not the
page as it stood — photos and text usually persist, but delisted properties rot, so the
sample is biased toward what's still up. (b) This is expensive: a full pipeline per
house, against a backtest that runs thousands. **Grade on 50–100 houses, not the whole
set**, and accept wide error bars on the verdict. A cheap, honest measurement beats an
unmeasured skill by a mile.

---

## 10. The works estimate — move-in, and one year later

This is the *"Estimate what a favourited house will need"* card, and it drops in as
stage 9 essentially unchanged. Inputs: the photos, the prose, `year_built`, and
`REPAIR-COSTS-NJ.md`.

**The split he asked for is the right one and it isn't cosmetic:**

- **Move-in** — what must be done before or immediately after you take the keys.
  Safety, systems, habitability, and anything a lender or insurer forces. *(Panel to
  200A if the inspection flags it, $2,500–$4,500. Oil tank sweep, $150–$500 — and
  `REPAIR-COSTS-NJ.md` is explicit that this happens **before** you're emotionally
  committed, because the tail runs to $100,000+.)*
- **Year one** — what you'll want once you've lived in it. Kitchen, baths, AC, the
  deck. *(Minor kitchen remodel ~$31,419 keeping the boxes, the only interior project
  in the 2025 report returning ~100%.)*

**The rules, straight from the card and from `REPAIR-COSTS-NJ.md`'s own preamble:**
ranges only, never a point estimate; every line names the phrase or photo it came from;
anything it's guessing says so; totals are a floor **and** a ceiling, never an average.
An LLM will cheerfully turn *"needs TLC"* into `$62,400` — that is the failure mode this
whole section exists to prevent.

**And the three known weaknesses stay in the output, every run:**
1. The listing is marketing — it omits problems by construction, so any text-driven
   estimate is systematically **optimistic**.
2. **Facts beat prose.** Year built plus heating type outrank adjectives: a 1928 house
   with no updates mentioned very likely has 100-amp service, possible knob-and-tube,
   asbestos pipe wrap, radiators and no AC, and maybe a buried tank. Lead with the
   priors; treat the description as weaker evidence on top.
3. **It has never seen the house.** The honest framing is *"what to budget for and what
   to ask the inspector"* — never *"this house needs $60k."*

**One NJ-specific thing worth wiring in as a hard flag rather than a line item:** the
oil tank. `REPAIR-COSTS-NJ.md` calls it the deal-killer, with a range from $1,600 to
$150,000+ depending on groundwater. It should surface **separately from the budget**,
as a gate on the ruling, not as a number folded into a total.

---

## 11. One skill or two? — one skill, two outputs

The board asks this directly. **One skill.**

The works estimate and the appraisal read the same inputs (photos, prose, year built),
share stage 0 and stages 3–4 wholesale, and — decisively — **the appraisal is wrong
without the works number.** *"Worth $700–740k"* and *"needs $80k"* are not two facts,
they're one: a $700k house needing $80k of work is a different deal from a $760k house
that's done, which is the exact comparison the works card was written to enable.
Splitting them means running the expensive photo stage twice and risking two documents
that disagree about the same kitchen.

Fold the works card into this spike. Keep `--works-only` as a flag if a fast repair
budget is ever wanted on its own.

---

## 12. Where it runs, and what it writes

**Not a button on a page.** `SPIKE-market.md` §2 settled this and it hasn't changed: the
pages are static, on a **public** repo, served from `file://` or GitHub Pages, with no
server and no secret. They cannot call a model. No amount of wanting changes it.

So: **a local skill** (`market-history/appraise/`), invoked on one listing, writing its
verdict into the repo — which is exactly how everything else here works. The repo is the
DB (root `CLAUDE.md`).

**Two directories, and the split is not negotiable.**

```
  market-history/
    appraisals/                     # GITIGNORED — never committed, but KEPT FOREVER locally
      <property_key>/               # property_key IS the address: "103|emeraldvalley|07920"
        2026-07-21.md               # the human artefact — the §6 contract, in order
        2026-07-21.json             # range, tiers, evidence, comp ids, works
        2026-07-21-photos/          # THE IMAGES IT SAW, archived at run time
          01.jpg … 12.jpg           # numbered to match the "photo 4" citations in the md
        outcome.json                # appended when the house sells: ask, sold, date, gap
    appraisal-grades/               # committed — de-identified, numbers only
      2026-07-21.jsonl              # {subject: sha256(property_key)[:12], town, beds,
                                    #  baths, sqft, built, range_lo, range_hi, point,
                                    #  comp_mid, comp_lo, comp_hi, works_lo, works_hi,
                                    #  flags[], pipeline_version, model, photo_mode}
```

**Why the appraisals themselves must stay local.** An earlier draft filed this under
"a taste call about what a public repo should carry." It is not a taste call, it is a
one-way door, and root `CLAUDE.md` already states the operative rule in its own words:
*"Anything committed here is world-readable forever (git history keeps it even after a
later deletion)."* That was written about secrets and it governs this identically.

What we would otherwise be publishing, permanently and searchably, at a **real street
address** — `property_key` is literally `address|zip`, so the directory name is the
address — is three separate problems:

1. **Adverse commentary about a third party's home.** "Original kitchen, tired exterior,
   probable knob-and-tube" attached to a named property somebody lives in and is selling.
2. **Your negotiating position.** §6 item 3 publishes *the most you would pay.* A seller's
   agent who searches the address finds your ceiling before you offer.
3. **No delete.** Git history means removing it later doesn't remove it.

**And nothing is lost.** §9's grader needs numbers, not prose or addresses — so the
committed record carries a hashed subject key, the town, the shape of the house, the
range, the comp anchor and the flags. That grades every question in §9 and identifies
nobody. The readable appraisal lives on the laptop, where it is genuinely useful and
harms no one.

**Dated, per-run, both sides.** The appraisal is a *claim made on a day* against a market
that moves, and §9's grader needs the verdict as it stood rather than as later revised.

**Archive the photos with the verdict.** Every photo claim cites an index — *"oak cabinets
and laminate counters, photo 4"* — and that citation is worthless in six months if photo 4
is a dead Realtor URL on a delisted house. Listings rot; that is the same rot §9 flags for
retrospective grading. So the images are copied into the run directory at fetch time and
numbered to match the citations. Cheap (a dozen JPEGs), and it is the difference between a
verdict you can audit later and one you can only re-read.

**Append the outcome when the house sells.** A verdict with no result cannot tell you how
you did — and *"look back and see how we did"* is the whole reason to keep these. When a
watched listing closes, write `outcome.json` beside the verdict: what it asked, what it
sold for, the date, and the gap against our range. `sales.csv` already picks these up, so
this is a join, not a new fetch. **That file is what turns a folder of opinions into a
track record**, and it is the local twin of the de-identified row in `appraisal-grades/`.

**Cloud or local?** Split by stage. Stages 0–2 and 5–8 are pure computation over
committed CSVs — cloud-safe. **Stages 3 and 9 need photos, and photos mean Realtor,
which 403s datacenter IPs.** So the default cloud-capable run is text-and-comps-only and
says so on its face; the photo-grade appraisal is a local command. **A verdict must
record which mode produced it** — a no-photo appraisal claiming condition insight would
be the worst bug this thing could have.

**Every record carries what produced it.** `pipeline_version`, the `model` id, and
`photo_mode` (`none` | `thumbnail` | `gallery`) are required fields, not nice-to-haves.
§9 grades verdicts against sales that close months later, and the pipeline will have
changed by then — §14 Q3 anticipates exactly that. Without a version stamp you are
comparing three different appraisers and calling it a trend. This is free now and
unrecoverable in hindsight.

**`property_key` is stable, and I checked rather than assumed.** `listings.py:81` derives
it as `address_key + zip` — deterministic from the address, so it survives a re-scrape and
won't fragment a house's history across runs. 4,535 distinct keys over 4,542 live rows;
the handful of collisions are unit-level addresses that normalise together, which is worth
knowing before it becomes a directory name but doesn't break anything. Note the corollary
that drives the split above: **a deterministic key built from the address is not an
anonymous identifier.** Hence the hash on the committed side.

**Secrets:** none. Every input is a committed CSV or a public listing page. If a paid
data source ever enters (a permit API, say), it's an env var on the routine, referenced
by name, never in a tracked file. Root `CLAUDE.md`, unchanged.

---

## 13. What I'd cut from v1

- **Comp photos** (§5c). One fetch per comp, 66.1% hit rate, local-only, and the
  marginal insight over the subject's own photos is small. Ship subject photos; add comp
  photos when the subject-photo stage has proved itself on the backtest.
- **A per-house tax lookup.** Tempting to scrape the municipal tax record for the real
  bill. It's a new source per town, 75 different websites, for a number that's usually
  printed on the listing anyway. Use the effective-rate estimate (§8), label it, move on.
- **Permit lookups** (§7b/c). This is the *right* answer for roof and remodel dates and
  it deserves its own spike — but it's a new statewide source and it would swallow v1.
- **Running it over all 4,542 live listings.** The pipeline is nine stages with fan-out;
  at that volume it's a bill, not a feature. **One house at a time, on demand** — the
  same shape as the analyser. Batch mode only if the backtest says the verdicts are good.
- **Any automatic Slack post or scheduled run.** House-hunt's scout is deprioritised
  (`MEMORY`, 2026-07-13). This is a thing you *ask*, not a thing that arrives.
- **A numeric "appeal score."** He asked for overall appeal, and the temptation is to
  emit `appeal: 78`. Resist it. HS already exists for taste, it's the one sanctioned
  exception in `layers/README.md`, and a second competing score would be genuinely
  confusing. **Appeal here is prose with evidence attached**, feeding the ruling.

---

## 14. Prerequisite — DONE 2026-07-21

**`garage`, `ac_type` and `solar` are now persisted columns on `listings.csv`.** They
were never missing from the feed — `listings.py` fetched them on every run and dropped
them when building the row. Three lines.

Fill on the current pull: **garage 56%, ac_type 8%, solar 1%.** So garage is genuinely
usable, ac_type is a bonus where present, and solar is noise. Stage 4 still mines the
prose for all three, because 92% of rows have no `ac_type` — but where the column *is*
filled it is unambiguous, and an unambiguous structured field beats inferring the same
thing from a seller's adjectives.

⚠️ **The columns are empty until the next local scrape.** Realtor 403s datacenter IPs,
so `listings.py` only runs on the laptop — the same constraint as everywhere else.

---

## 15. Open questions — need a decision before building

1. **Does the skill fetch photos by default, or only on `--photos`?** I argue opt-in
   (§5): it forces local-only, it's the slowest stage, and most runs don't need it. But
   condition is the *whole point*, so a default-blind appraiser may be a worse product.
   **This is the one call that changes the shape of the thing.**
2. **Do the verdicts get committed?** I argue **yes** (§12) — the backtest can grade
   them for free and a dated claim is worth keeping. But it's churn in a public repo
   with a real address in every filename. *(No secret involved; it's a taste call about
   what a public repo should carry.)*
3. **How wide should the final range be?** The comp band is p25–p75 by construction —
   about half the time it's wrong, on purpose. Should the skill's range be *wider*
   (honest about condition uncertainty on top) or *narrower* (the photos genuinely
   resolved something)? I lean wider by default and narrower only on strong evidence,
   but this should be **set by the backtest, not by opinion**.
5. **What happens when `comps()` refuses?** It does, deliberately, on thin towns and odd
   sizes. Does the skill decline to appraise, or proceed on borrowed comps with a loud
   caveat? I'd decline for the *range* and still ship the works estimate and the
   location findings — those don't need a price anchor.
6. **Sequencing against the two other board cards.** *"Stop competing with the asking
   price"* is smaller and independently valuable; *"Find what the same house sold for
   last time"* would make this skill materially better (§7a). Does the appraiser go
   first, or after one of them?

---

## 16. The thing that worries me

Every other number in this project is checkable. Comps are graded in public on
`backtest.html`, the seasonal factor comes off real sold-vs-ask, thin buckets refuse to
answer, borrowed indices get flagged on the face of the page.

**This skill produces the first output here that reads as authoritative and is mostly
judgement.** *"The kitchen looks 1990s"* is an opinion in the grammar of a fact. Stack
six of them and you get a range that looks as solid as the comp band underneath it and
is not.

Three things hold that in check, and none is optional: **every claim names its photo or
its phrase**, so it can be checked in ten seconds; **the adversary stage ships its
objections in the output**, not in a log; and **§9 grades the whole thing against houses
that already sold** — so if the adjustments are noise dressed as insight, we find out
from data rather than from vibes.

If we build this and skip the grader, we will have built a very persuasive way to be
wrong.
