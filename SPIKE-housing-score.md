# SPIKE — HS, the Housing Score

**Status:** ✅ **BUILT** (2026-07-17) — live on `market.html`. This doc is now the
record of *why the weights are what they are*, and the place to change them.

**It is not an ultimatum.** If a house scores 85 and you hate it, the score is wrong
and we retune — that is the intended workflow, not a failure. Every number below is a
dial. See §9 for how to argue with one.

**Ask:** one number, 0–100, for how much *you* would like a house. Not what it's worth
— `offer/index.html` already answers that. This is taste, made explicit.

---

## 1. Can the data support it? Mostly — and I measured exactly how much

Two very different tiers, and the difference decides the whole design.

### Tier 1 — structured fields, already in `listings.csv`

| field | coverage | notes |
|---|---:|---|
| `list_price` | **100%** | the only thing we always know |
| `beds` / `baths` | **98%** | |
| `year_built` | **88%** | |
| `lot_sqft` | **75%** | and the "missing" 25% is mostly condos, which correctly own no land — for **houses** it's 85% |
| `sqft` | **31%** ⚠️ | two thirds of houses don't publish a size (`DEFECTS.md` #5) |

### Tier 2 — the description, which we do **not** currently store

`listings.py` never captured `text`. **It should** — the scraper returns it on **99%**
of listings and it is the only place your amenities exist. Probed live against Scotch
Plains (101 descriptions):

| you asked for | mentioned in | verdict |
|---|---:|---|
| **garage** | **51%** | usable |
| **in-ground pool** | **12%** | usable — and it's your *negative*, which is the useful direction |
| **driveway** | **13%** ⚠️ | see §4 — this one is a trap |
| **central AC** | **7%** ⚠️ | barely differentiates |
| window/wall AC (the anti-signal) | 2% | |

And things you didn't ask about but the text hands us free:

| | mentioned in |
|---|---:|
| deck / patio | 46% |
| basement (finished: 31%) | 45% |
| renovated / updated / remodelled | **41%** |
| fenced yard | 19% |
| "as-is" / "needs work" / "TLC" / investor | **14%** |
| solar | 2% |

---

## 2. The trap in "don't penalise a missing field" — and it's real

Your instinct is right: **not mentioning central AC ≠ not having it.** So a missing
field must never dock a house.

But do that naively and you get a scoring system for **copywriting**. I measured it:

```
  short descriptions (<400 chars)  → median 0.5 features found
  long  descriptions (>900 chars)  → median 3.0 features found
  correlation, length vs features found:   r = +0.41
  correlation, length vs list price:       r = +0.03   ← the tell
```

**A chatty agent's listing collects 6× the bonuses of a terse one for the same house.**
And the +0.03 against price proves length isn't secretly a quality proxy — it's *pure
noise about the agent*, not the house. Left uncapped, HS ranks estate agents.

This is the same failure that already bit us twice: the "best value" sort put every
no-sqft listing on top, and the seasonal curve let a 29-sale bucket overturn a
425-sale one. **The fix is the same each time — never let what we don't know outvote
what we do.**

---

## 3. The formula

```
  HS  =  clamp(0, 100,  BASE  +  FLAVOUR )

  BASE     = 100 × Σ(wᵢ · sᵢ) / Σ(wᵢ)        ... over factors we actually KNOW
  FLAVOUR  = clamp(−12, +12, Σ adjustments)   ... text-mined, capped on purpose
```

**`BASE` is a weighted mean, not a sum.** That's the whole trick: an unknown factor
drops out of the numerator *and* the denominator, so it neither helps nor hurts — it
just makes the remaining factors count for proportionally more. That is exactly "don't
take it into consideration", done arithmetically.

**`FLAVOUR` is capped at ±12**, so the verbosity bias in §2 can move a house by at most
a grade, never rank it.

### BASE factors

| factor | w | s(x) | why |
|---|---:|---|---|
| **your town tier** | **14** | `S: 1.0 · A: 0.85 · B: 0.65 · C: 0.4 · D: 0.2 · F: 0` | the only **opinion** in the model — see §13. `unknown`/`unranked` stay null and drop out; they are not an F |
| **price** | **30** | `1.0` to $750k, then linear → `0` at $950k | the hard constraint. ⚠️ Inside your $650k filter this is a **constant** — every house scores 1.0, so the heaviest factor does no ranking work. It's a gate, not a discriminator. |
| **lot** | **16** | `0.35` at 3k → **`1.0` across 6k–14k** → `0.7` at 22k → `0.4` at 1 acre | "bigger is better, too big is a commitment". The plateau contains Farley's 6,599. |
| **schools** | **12** | mean of the elementary/middle/high DOE deciles. `decile 2: 0` → `9+: 1.0` | **real DOE 2024-25 assessment results**, not the ACS adult-degree proxy (§10) |
| **commute to NY** | **12** | `≤35min: 1.0` → `50min: 0.75` → `70min: 0.30` → `0` by 120 | **the one amenity that isn't a nice-to-have.** Real range: 30–119 min, median 50 |
| **beds** | **11** | `<3: 0.25` · `3: 0.80` · `4: 1.0` · `5+: 1.0` | 3 is the floor; the penalty is steep, the reward for 5+ is nil |
| **year built** | **6** | `1900: 0.20` → `2010+: 1.0` | halved — see §5. Condition is scored from the copy instead |
| **shops nearby** | **5** | mean of TJ / Wawa / Seabra miles. `≤2mi: 1.0` → `6mi: 0.6` → `0.1` by 16mi | **low on purpose** — "closer is better, but don't give it many points". Averaged so one distant chain can't sink a town |
| **time on market** | **8** | `≤7d: 0.5` (neutral) → `90d: 1.0` → `150d: 0.6` → `0.25` by 300 | **measured, not assumed** — see §11 |
| **house, not a condo** | **8** | `house: 1.0` · `multi: 0.55` · `attached: 0.2` | |
| **baths** | **9** | `<1.5: 0.25` · `1.5: 0.70` · `2: 0.85` · `2.5+: 1.0` | |
| **house sqft** | **7** | `1000: 0.55` → `1400: 0.85` → `1800+: 1.0` | low weight *because* it's only on 31% — it would otherwise swing the mean wildly between houses that publish it and houses that don't |

### FLAVOUR adjustments (only ever applied when explicitly found)

| signal | pts | found in |
|---|---:|---|
| **renovated / updated** | **+5** | 41% |
| garage | **+4** | 51% |
| central air | **+3** | 7% |
| driveway | **+2** | 13% |
| window/wall AC only | **−3** | 2% |
| **as-is / needs work / TLC** | **−6** | 14% |
| **in-ground pool** | **−8** | 12% |
| finished basement | **+3** | 31% |
| deck / patio | **+2** | 46% |
| fenced yard | **+2** | 19% |

### And two signals only *we* have — from watching, not from the copy

| signal | pts | why we alone can see it |
|---|---:|---|
| **cut its price** | **+4** | we watched it fall between runs; `price_changes` is empty on every sold row |
| **relisted** | **−3** | the days-on-market reset. `listings.py` exists for this |

### And a third number, which matters as much as the score

```
  CONFIDENCE = Σ(wᵢ known) / Σ(wᵢ total)
```

**Never show HS without it.** A house with price+beds+baths only scores on 52% of the
model; one with everything scores on 100%. Two houses at "HS 78" are not the same claim
if one is 52% confident. Show it as `HS 78 · 60% known`, and — the lesson from the
market sort — **rank by HS but break ties on confidence, never the reverse.**

---

## 4. Two of your asks are weaker than they sound, and you should know before we build

**Driveway (+2, 13%) is close to useless.** Practically every detached NJ house has a
driveway; the 87% that don't mention it aren't driveway-less, they just didn't say. So
this scores *"the agent bothered to type the word"*. I'd **drop it** — or, better,
infer it: `garage ⇒ driveway`, which lifts it to 51% coverage and is nearly always true.

**Central AC (+3, 7%) barely moves anything.** 93% of houses get nothing, so it can't
differentiate. Keep it (it's free and it's real when present), but expect it to decide
almost nothing. **The 2% that mention window units are the more valuable signal** — that
one is a genuine negative and it's *deliberately* stated.

**The in-ground pool penalty is the best amenity signal you have.** 12% coverage, and
sellers *always* advertise a pool — nobody hides one. So absence really does mean
absence here, unlike AC. This is the one text field where a missing mention is close to
informative.

---

## 5. Where your stated taste and your revealed taste disagree

**You want newer. Your favourite house is from 1950.**

524 Farley — the best of 30+ open houses — is a **1950** build on a **6,599 sqft** lot.
Under the formula above it scores **0.50** on the year factor, dragging its own HS down
by roughly 6 points. The house you loved is penalised by the rule you gave me.

I think the resolution is that **"newer" is a proxy for "not a project"** — you don't
want 1950s wiring and a 1950s kitchen; you don't specifically want a 2015 build. If so,
the honest factor isn't `year_built`, it's **condition**, and the text gives us a decent
read on it: **41% say renovated/updated** and **14% say as-is/needs work/TLC**.

**Proposal:** cut `year_built` to **w=6**, and add to FLAVOUR:

| | pts | found in |
|---|---:|---|
| renovated / updated / remodelled | **+5** | 41% |
| as-is / needs work / TLC / investor | **−6** | 14% |

That would score 524 Farley on *what it is* rather than *when it was poured*. **Tell me
if I've read that wrong** — it's the biggest judgement call in the doc.

---

## 6. Questions I actually need answered

1. **Where does "too big" start?** I've put the plateau at 6k–14k sqft, half-marks near
   an acre. Farley's 6,599 sits at the bottom of the plateau — if you want *bigger* than
   Farley, the peak should move. Is a **half-acre (21,780)** still good, or already a
   chore?
2. **Is `year_built` really the thing, or is it condition?** (§5.)
3. **$650k or $750k?** Your filter default says $650k; you said $750k is where it breaks.
   I've used $750k as the cliff — so a $740k house scores full marks on price while
   being invisible in your default list.
4. **Do these matter, and how much?** They're free and reasonably covered:
   finished basement (31%) · deck/patio (46%) · fenced yard (19%) · multi-family (would
   you rent a unit?).
5. ~~Should HS include commute / shops?~~ **ANSWERED — yes, and the rule is amended.**
   `layers/README.md` said amenities are *colour, never a filter, never rank a town*.
   HS breaks that, deliberately, on the owner's explicit call (2026-07-17). The line
   that survives:

   > **Amenities never touch what a house is WORTH. They may touch whether you WANT it.**

   The comps and the seasonal factor in `index.html` are still forbidden from seeing a
   shop — pricing a house by its groceries would be a real error. HS is a *preference*
   score and is allowed to. Commute carries **w=12** (it's a daily cost); the three
   shop layers share **w=5** between them, averaged.

---

## 7. What was built

| | |
|---|---|
| ✅ | **`listings.py` now captures `text`** — verbatim, trimmed to 900 chars, re-read every run. Stored raw rather than pre-parsed for the reason `DEFECTS.md` learned with `bldg_desc`: the garage parser was wrong for months and fixing it needed a full re-scrape, because the source string had been thrown away. Now a pattern fix re-applies offline. **98% of listings carry one.** |
| ✅ | **`hsFor()` in `engine.js`** — the shared engine, so `market.html` and `index.html` can never disagree about a score. |
| ✅ | **market.html**: HS badge on every row, sort by HS, min-HS filter (60+ / 75+). |
| ✅ | **The working is shown.** Click any score → every factor, its 0–100, its weight, and what was *left out for being unstated*. |

### The ceiling bug, caught before it shipped

First run put **seven houses at exactly HS 100** — a ceiling precisely where the
ranking has to do its work. Cause: a strong house reached base ~95, +12 flavour, and
clamped. Base is now scaled to **88**, so structured data alone can never exceed 88 and
**100 means "excellent fundamentals AND everything we want is actually mentioned"**.
Result: **23–98 across 1,782 houses, 71 distinct scores, one house at the top.**

---

## 9. How to argue with it

It is a preference model, so "wrong" only means *wrong for you* — and that's a bug
report, not a disagreement.

1. Open the house's breakdown on the row. It names every factor, its score, its weight,
   and what was skipped.
2. Tell me the house and what's wrong: *"this scored 85 and the lot is a postage
   stamp"* → the lot curve is off. *"this scored 60 and I love it"* → something it has
   isn't being counted.
3. The weights live in `HS_FACTORS` / `HS_FLAVOUR` at the top of `offer/engine.js`.
   They are two plain tables. Changing one is a one-line edit and a rebuild.

**Retuning is the point.** A score nobody argues with is a score nobody is reading.

---

## 8. The thing I'd want you to hold onto

This is the first number in this project that is **about you rather than about the
market**. Everything else — comps, the seasonal factor, the price index — can be
checked against reality and shown to be wrong. **HS cannot.** There's no ground truth;
if it says 82 and you hate the house, the score is wrong by definition and the only fix
is to change the weights.

So it should be **easy to change and easy to see through** — hence §7.5, hence the
confidence number, hence the ±12 cap. The failure mode isn't a bad formula. It's a
formula you stop questioning because it looks like a measurement.


---

## 10. Schools — why the obvious file was the wrong file

The repo already had `layers/education/` and it *looks* like a schools layer. It isn't.
It's **ACS Table B15003 — Educational Attainment for the Population 25 Years and Over**:
the share of *adults* with a degree. That measures the neighbours, not the schools.

Measured before using it:

```
  bachelors% vs median household income   r = +0.87   (explains 75% of the variance)
  bachelors% vs median sold price         r = +0.76
```

**It is the income map with a different label.** Folding it into HS would have
(a) double-counted price, which already carries w=30, and (b) encoded class sorting as
a quality judgement — which is exactly what `share/README.md` caveat 5 forbids:
*"never present them as a quality ranking."*

So HS uses **`layers/schools/`** instead: NJ DOE 2024-25 statewide assessment results,
district deciles 1–10, elementary / middle / high scored separately and averaged.
Actual test results.

**Its own caveat, which is real:** the rating is a **district proxy keyed to a ZIP**,
and schools are assigned by *attendance boundary*. One ZIP can span districts at
different levels — **Garwood's elementary is Garwood Boro; its high school is Clark
Township.** Two houses on one street can feed different elementary schools. It's a
town-level signal; for an actual house, check the boundary. 52 of 53 towns have a
rating (Westfield has no row — and the weighted mean simply drops it).

---

## 11. Time on market — the data contradicted my first instinct

I assumed *longer sit = more leverage, monotonically*. Then I measured it, across the
active listings we're watching:

| days on market | n | cutting price |
|---|---:|---:|
| 0–7 | 399 | 3.0% |
| 8–30 | 634 | 3.6% |
| 31–60 | 399 | **4.8%** ← peak |
| 61–120 | 300 | 1.7% |
| **121+** | 142 | **1.4%** ← collapses |

**A house that has sat four months is not cutting — it's stubborn, or it's broken.**
Motivation peaks in the 1–3 month window and then dies. That matches the instinct that
prompted this ("either really bad or forgotten") and contradicts mine, so the curve
follows the data: fresh is **neutral** (no leverage, no information), 90 days is the
peak, and it decays after.

⚠️ **The honest confound:** the 121+ group may look non-cutting because the ones that
*did* cut already sold and left the market. That's survivorship, not proof. Three days
of observation can't separate them. More weekly runs will.

---

## 12. Still missing (ranked)

1. **Flood zone** — listings carry lat/lon on 100% of rows and FEMA's NFHL is public.
   93 Gaywood sits partly in an AE zone and we'd never know. This should be a hard
   penalty and it's genuinely buildable.
2. **Rail proximity** — same unlock. The line behind 63 Lyons is invisible to us, and
   backing onto an active line is a real, permanent minus.
3. **vs-comps into HS** — `market.html` already computes the gap; a house $50k under
   comps should outrank one $50k over. Currently you're doing that arithmetic by eye.
4. **Lot *shape*, not just area** — 6,599 sqft as Farley's 50×132 is a backyard; as
   100×66 it isn't. MOD-IV carries `LAND_DESC` ("50 X 132").
5. **Confidence is shown but never scored** — a 55%-known HS 80 currently ranks beside
   a 100%-known HS 80. It breaks ties and nothing more. Deliberate for now; revisit.


---

## 13. The tier list — the only opinion in the model, and the tension it exposes

`tierlist/tiers.json` is hand-ranked in `tierlist/tierlist.html`. All 53 towns:
**S 14 · A 12 · B 20 · C 6 · D 1 · F 0.** It's the one input here that isn't measured,
and it's weighted **14** — above schools and commute, below only price.

### It earns that weight because it isn't a copy of something we already have

Checked before wiring it in:

| tier vs | r |
|---|---:|
| commute | −0.29 |
| schools | +0.41 |
| shops | −0.34 |
| distance from Westfield | −0.37 |
| **town median price** | **+0.50** |

Mostly independent, so it adds taste rather than re-weighting a number already in the
model. If it had come back at r=+0.8 against schools it would have been schools wearing
a hat, and would not deserve its own weight.

### The tension it exposes, which is worth staring at

> **The towns you rank highest are the ones you can least afford.**

| tier | towns | houses for sale | **≤$650k** | town median |
|---|---:|---:|---:|---:|
| **S** | 14 | 286 | **15 (5%)** | $1,003,000 |
| A | 12 | 284 | 39 (14%) | $725,000 |
| B | 20 | 538 | 105 (20%) | $709,500 |
| C | 6 | 136 | 51 (38%) | $682,500 |
| **D** | 1 | 38 | **27 (71%)** | $533,750 |

**Six of your fourteen S-tier towns have literally zero single-family houses at or
under $650k right now:** Chatham (median $1.25M), Glen Rock ($975k), Essex Fells
($1.45M), Glen Ridge ($1.1M), **Short Hills ($2.21M)**, Madison ($1.03M).

So the tier factor mostly does its work *inside* A/B/C — which is where your budget
actually lives. The S-tier weight is close to decorative at $650k, and that is a fact
about the market, not about the formula.

### And your other instinct — "crappy if they're in my price range" — is real

| a sold house priced at… | n | median sqft |
|---|---:|---:|
| **<60% of its town's median** | 756 | **1,303** |
| 60–85% | 1,768 | 1,560 |
| 85–115% | 3,067 | 1,900 |
| >115% | 4,751 | 3,000 |

**A house at under 60% of its town's median is a third smaller than a typical one
there.** "Affordable in a dear town" really does mean "the compromised end of it".

**I did not add this as a factor, deliberately.** HS already penalises exactly what
makes those houses cheap — `sqft` (w=7), `year built` (w=6), and the `as-is` flavour
(−6). A separate "cheap for its town" penalty would be double-counting the same
compromise, and it would also punish a genuine bargain for being a bargain. The
market page's **vs-comps** already does the honest version of this: it compares a house
to *similar-sized* houses in the same town, so it catches "cheap for what it is" rather
than "cheap because it's small".
