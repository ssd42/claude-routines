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

### Map page — more fields
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

## Ideas

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

### NJ repair-cost reference
A doc of what common NJ home work actually costs: roof, HVAC, electrical panel, windows,
kitchen, bath, foundation/waterproofing, sewer line, **oil tank removal** (very NJ),
asbestos / knob-and-tube, chimney.

**Why:** it turns "needs work" into a number, so an as-is listing can be compared honestly
against a renovated one. Eventually the analyser could adjust an ask by estimated
remediation instead of just flagging `as-is`.

**Sourcing:** regional contractor averages to start, and — better — **your own quotes as
they come in**, which are real local prices. Flag which is which; a national average is not
a Union County quote.
**Open questions:** static reference doc, or a data layer the analyser consumes? Do we log
your real quotes over time?
**Size:** doc first (small), layer later.

---

## Done

- **"New — last 14 days" on the market page** — already built and live. Uses
  **days-on-market**, not `first_seen`, deliberately: with first-seen, a house listed in
  2024 that we only started tracking recently looks as new as one listed yesterday. It also
  warns that new listings are a thin slice when the filter is on. *(confirmed 2026-07-20)*
