# TODO — the house-hunt board

A mini Trello for `market-history/`. Nothing here is committed to; it's a parking lot for
ideas so they stop living in chat.

**For Claude:** check this file now and then — when a session is winding down, or when the
user asks "what's next?" — and *offer* one of these. Don't start any of them unprompted.
Move a card between sections as it progresses, and keep the open questions honest: most of
these are under-specified on purpose and need a decision from the owner first.

Sections: **Ideas** (not thought through) → **Ready** (spec'd enough to build) →
**Doing** → **Done**.

---

## Doing

*(empty)*

---

## Ready

*(empty)*

---

## Ideas

### Stop competing with the asking price — use it
The single biggest idea to come out of the backtest, and it reframes the whole tool.

Our estimate misses the true sale price by about **10.7%**. Just believing the asking price
misses by **4.0%**. That looked like a failure until you see how the big firms do it: their
published error is roughly 2% for a house that's on the market and 7% for one that isn't —
same model, same company. The difference is that when a house is listed, they feed the
model *the asking price*. It carries most of the signal, because someone walked the house.

**So stop producing a from-scratch price and then comparing it to the ask.** Predict the
**gap** instead — "worth about 8% under what they're asking, and here's how sure we are."
That is the question you actually have, and it's the one the tool is best placed to answer.

**Why it's not just cosmetic:** it changes what the page says, not only how accurate it is.
And the backtest can grade it directly — does a house we call underpriced actually sell
above its ask? If that holds, the tool earns its keep even at 10% error. If it's flat, it
doesn't, and that is worth knowing.
**Open questions:** does the ask become an input to one blended number, or stay a separate
opinion shown beside ours? What do we show for a house that isn't for sale?
**Size:** medium. **Do after:** the three fixes above, so the measurement stays clean.

### Find what the same house sold for last time
The biggest missing ingredient, and the one that would help most with the thing we're
blindest to.

What a house sold for in 2019, carried forward by how its town has moved since, beats any
comparable sale — because it's the *same house*, with the same kitchen and the same roof.
It quietly encodes condition, which is exactly what we cannot see and what explains most of
our worst misses. Identical houses on paper sold from $438k to $951k in one town; nothing
we hold explains that spread, but a prior sale price would go a long way.

**The catch:** our records hold only the most recent sale per property. The state's annual
sales files carry the full history, so the data exists — but it's a new source to pull and
merge, not an afternoon's work.
**Size:** large — highest ceiling on this list, wrong thing to start before the cheap wins
are banked.


### Let a model learn the price instead of us hand-tuning the rules
Feed everything we scrape into a trained model and see if it beats the comp formula.

**The honest sizing first:** only ~6,900 sales carry the full set of fields, which
splits to **5,700 to train on and 1,160 to test**. That is small — small enough that
a neural net is the wrong tool. On tabular data at this size, gradient boosting beats
neural nets reliably. Same idea, better-suited machine, and it's what most real
valuation models actually run.

**Two traps that would waste the effort.** Feed it the asking price and it will score
~4% error by mostly learning "sold ≈ ask" — impressive-looking and useless, because it
assumes the ask is right, which is the thing we're trying to check. So: one model that
never sees the ask ("what's it worth"), and one that predicts sold-over-ask ("will it
go above"). And split the data **by date**, not at random — a random split leaks 2026
sales into training and flatters the score.

**Where it would run.** Training needs real libraries, so it's a local offline step
like the other fetch scripts, never the cloud routine. The result ships as plain
numbers baked into the page — no runtime dependency, nothing to install to browse.

**What to expect:** maybe 7–9% against today's 9.9%. Real but not transformative,
for the same reason everything else plateaus — condition isn't in the features.

**Start with the cheapest version:** ridge regression on today's fields, an hour,
graded on the backtest. If a straight line can't beat the comps, boosting probably
won't either, and that's an hour spent instead of a week.

**Fits naturally with:** a rewrite onto a real framework and a server, if that ever
happens — at which point the model could retrain on a schedule instead of by hand.
**Size:** medium for the real version, an hour for the probe. **Do after:** the
ask-anchoring card above.

### A skill that appraises one listing, and says why
Hand Claude a single listing and get back an estimate *with its reasoning* — "the
kitchen photos look 1990s", "it backs onto Route 22", "0.8mi to the station, uphill".

**Why this is the strongest idea on the board.** Every plateau this session has come
down to the same thing: the formula cannot see condition, and condition is most of
what separates two houses identical on paper — one town had them selling from $438k to
$951k. But that information isn't missing from the world, only from our columns. It's
sitting in the listing photos and the description, which a model can actually read.

**It must adjust our number, never replace it.** The comp engine is anchored to
thousands of real sales and is honestly calibrated; an LLM asked for a price from
scratch will produce a confident number from nothing. So the shape is: comps give the
anchor, the skill gives an adjustment and the reasons. "Comps say $720k; the photos
show an original kitchen and it faces a four-lane road, so call it $660–690k, and
here's the evidence for each."

**Guardrails, same as the repair-estimate card below — this is the project's oldest
rule and it bites hardest here.** Ranges, never point estimates. Every claim names the
photo or phrase it came from, so you can check it. Anything it's guessing gets said
out loud. And it never sees the asking price before forming a view, or it will simply
agree with it.

**Two things we could feed it that we don't use yet:** listings carry coordinates, so
*this house* to *that station* is computable rather than the town-level average we
show now — same for a big road. And the description text already ships in the data.

**Why a skill and not a button on the page.** The pages are static, on a public repo,
with no server and no secret — they cannot call a model, and no amount of wanting will
change that. A skill runs locally or on the routine and writes its answer into the
repo, which is exactly how everything else here already works.

**Open questions:** every listing, or only favourites? Does its verdict get committed
so we can grade it against the eventual sale — which the backtest could do for free?
**Overlaps heavily with** "Estimate what a favourited house will need" below; these
may be one skill with two outputs rather than two. **Size:** medium.

### Suggest more towns like the ones I already track
We track 63 towns that came from one original list. There are ~565 NJ municipalities — we
may be missing good ones purely because nobody put them on the list.

**Sketch:** build a profile from the towns already rated S/A in `tierlist/tiers.json`
(price band, school decile, commute, tax rate, appreciation, lot size), then score every NJ
municipality against it and surface the closest matches we don't already track. Statewide
coverage already exists for most inputs: DCA tax (all 565 munis), Zillow/FHFA (all ZIPs),
Census income, and `nj_records` sales are statewide.

**Open questions:** which towns define "like the ones I like" — S tier only, or the whole
list? Hard constraints (max commute, max price) vs. soft similarity? How many suggestions,
and does a suggestion need a reason attached ("like Cranford, but 12% cheaper")?
**Size:** medium. Needs a statewide town table; today we only bake our 63.

### Persistence across devices
Today every page's state (filters, and later favourites/notes) is `localStorage` — per
device *and* per browser. Laptop and phone don't share anything.

**The hard constraint:** the site is **static on GitHub Pages** and the repo is **public**,
so there's no server and no secret can live in the page. That rules out the obvious "write
to a store with an API key" answer.

Options worth weighing (a spike, not a decision):
- **URL-encoded state** — partly done already (the market page encodes filters in the URL).
  Zero infra; you move state by sharing a link. Doesn't scale to long notes.
- **Export/import a JSON file** — zero infra, manual, clunky, but honest.
- **A hosted KV / tiny backend** (Cloudflare Workers KV, Supabase) — real sync, but adds
  infra, auth, and a secret; breaks the current "no server, no secrets" property.
- **A per-device token in `localStorage` writing to a private gist** — token never enters
  the repo. Pragmatic middle ground; think through the failure and leak modes.

**Spiked, and decided:** [`offer/SPIKE-persistence.md`](offer/SPIKE-persistence.md) — a
Cloudflare Worker + Workers KV under a random unguessable id kept in the browser, plus
export/import a JSON file so nothing is trapped. No login. Answers the open questions below.

**Open questions:** is this just you + partner (2 devices, low stakes)? Is "share a link"
enough, or do we need true background sync? Willing to run *any* infra?
**Size:** spike first. **Blocks:** favourites + notes below.

### Favourite a house, and a notes page for AI to help
Star a listing; a separate page lists the starred houses with free-text "what I liked /
what I didn't" per house, structured so AI can compare them and help you decide.

**Why:** there's nowhere to record a reaction to a *specific* house right now — comparisons
live in your head, and the reason you passed on something is gone a week later.

**Design notes to get right:**
- A favourite needs an identity that survives re-scrapes — `property_key` / `mls_id`.
- **Snapshot the listing at favourite-time** (price, address, beds/baths, photo). When it
  delists, the note has to still make sense.
- Keeping delisted favourites is a feature, not garbage: "houses we lost, and what they
  went for" is real signal about what we can actually win.

**Open questions:** notes per house only, or per town too? Should the AI see the comps and
HS alongside your notes when helping? **Depends on:** persistence, above — otherwise your
notes are trapped on one device.
**Size:** medium-large.

### Estimate what a favourited house will need
**What you'd see:** star a house, and on the next scheduled run it comes back with a rough
budget for what it probably needs — something like *"likely $45k–$85k: kitchen looks original
($31k to refresh, $60–90k to gut), radiators and no AC (+$10–25k), oil heat — get a tank sweep
before anything else."* Then two favourites can be compared honestly: a $700k house needing
$80k of work against a $760k one that's done.

**Why Claude and not code.** The signal is mostly in the listing's own prose, and it's fuzzy:
*"charming original details"* often means an untouched 1940s kitchen; *"newer roof"* is a claim
with no date; *"freshly painted"* sometimes hides more than it says. Rules and regex can't weigh
that. Claude can — and can say *which phrase* it inferred from, which is what makes the answer
checkable. It reads two things: the listing, and [`REPAIR-COSTS-NJ.md`](REPAIR-COSTS-NJ.md).

**How it would work.** A scheduled run reads the favourites, and for each one hands Claude the
listing (description text, year built, heating/AC type, beds/baths/sqft, lot) plus the cost doc,
and gets back line items with ranges, the phrase or fact each was inferred from, and a
confidence. Output is written per house and committed — the repo is already the database.

**The thing to get right — don't let it invent precision.** This is the project's oldest rule
and it applies hardest here: an LLM will cheerfully turn *"needs TLC"* into `$62,400`. Rules
for the output: **ranges only, never point estimates**; every line must name what it was
inferred from; anything it's guessing at must say so; and it must total to a **range with a
floor and a ceiling**, not an average.

Three known weaknesses to design around:
1. **The listing is the seller's marketing** — it omits problems by construction, so any
   text-driven estimate is systematically optimistic. It should say so, every time.
2. **Facts beat prose.** *Year built + heating type* are more reliable than adjectives: a 1928
   house with no updates mentioned very likely has 100-amp service, possible knob-and-tube,
   asbestos pipe wrap, radiators and no AC, and maybe a buried oil tank. Lead with those priors
   and treat the description as weaker evidence on top.
3. **It has never seen the house.** The honest framing is *"what to budget for and what to ask
   the inspector"* — never *"this house needs $60k."*

**Open questions:** only new favourites, or re-run everything when the cost doc changes? Does it
also read your notes on the house? Should it flag the single highest-risk item (usually the oil
tank) separately from the budget? **Depends on:** favourites existing, above.

### Map page — more fields — DEPRIORITIZED
**Status:** deprioritized 2026-07-20. The ask was "*think about* more fields for the maps
page" — a question, not a decision. The specific fields below are **Claude's suggestions
that were offered and passed on** (when asked to pick, the owner chose property taxes only,
which is built and shipped). Keep them here as options to react to later, not as a plan.
Three are nearly free because `share/by_town.csv` already rolls them up per town; they'd
just need a metric entry + palette on `map.html`:

- **Sold-vs-ask %** (`median_sold_vs_ask_pct`) — bidding heat / negotiating room. Already
  shown in the town card, just not as a choropleth.
- **Days on market** (`median_dom`) — pace, and therefore leverage.
- **% selling at or under ask** (`pct_at_or_under_ask`) — how often you can actually get a
  deal, not just the average.

A bit more work, computable from `sales.csv`:
- **Price per sqft (median)** — the honest cross-town value number. Raw median price
  conflates "expensive town" with "town of big houses".
- **Price-cut share among active listings** — leading indicator of softening.
- **Housing stock character** — median lot, median sqft, median year built.

Already spiked, deliberately NOT shown yet (see `SPIKE-hs-location-factors.md`):
- **Crime** (§3) and **airport/highway/rail noise** (§4). Both are HS inputs only. Crime
  especially is close to a wealth proxy, and a "safety" colour on a map reads as gospel.
  Decide deliberately before putting either on the page.

**Size:** the first three are small. **Open question:** the metric strip already scrolls on
a phone at 7 metrics — do we group these under a "market heat" submenu rather than adding
six more buttons?


---

## Done

### Finish the three fixes the backtest turned up — DONE 2026-07-21
All three shipped, each measured on the backtest before and after.

1. **Condos priced off houses.** A thin town used to fall through to pricing a home
   against a different *kind* of home. Attached stock ran 10.5% too dear; now 1.9%.
   The fix was mostly an ordering change — borrowing from next door was already
   type-matched, so it belongs above the pooled fallback, not below it.
2. **Borrowing inflated big houses.** We re-scaled borrowed sales by a town's blended
   price per square foot, which really describes its *typical* house — 21–29% off for
   large ones. Now measured inside size bands. Borrowed estimates land inside their
   own stated range 53% of the time, up from 46%.
3. **How old a house is now counts.** Comps match within 15 years, widening to 30,
   then dropped. **This was the only one of the four changes that moved the overall
   number for real** — 10.49% → 9.86% median error, and it survives a significance
   test where the others were noise.

Honest total: 10.70% → 9.86% across all four. Two ways of being *wrong* are gone,
which matters more than the average. What did **not** get fixed is old houses — the
age ramp only flattened a quarter, and none of the six worst misses moved. That
residual is condition, and condition is not in this data.

### Decide whether "How right are we?" goes public — DONE 2026-07-21
Published. It's linked from the front page and copied by the deploy step, candour
about losing to the asking price included.



- **NJ repair-cost reference** — written: [`REPAIR-COSTS-NJ.md`](REPAIR-COSTS-NJ.md). What common
  work costs in Union/Essex/Morris/Somerset/Middlesex, with 45 sources and lead-gen marketing
  numbers labelled as such. Covers the asks (central AC, modernising a kitchen, roof) plus the
  NJ-specific ones that decide deals — buried oil tank, radon, asbestos, the 100→200A panel,
  historic-district windows, pool removal. Ends with an empty table to log **your own quotes**,
  which will beat every published average in it. *(2026-07-20)*
  Still open, now tracked as its own card above: feeding these numbers into an estimate for a
  favourited house.


- **"New — last 14 days" on the market page** — already built and live. Uses
  **days-on-market**, not `first_seen`, deliberately: with first-seen, a house listed in
  2024 that we only started tracking recently looks as new as one listed yesterday. It also
  warns that new listings are a thin slice when the filter is on. *(confirmed 2026-07-20)*
