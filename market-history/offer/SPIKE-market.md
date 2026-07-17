# SPIKE — "On the market": browse live listings, click one, price it

**Status:** proposal. Nothing built.

**Ask:** filter the current market by town (optional, multi-select) and price range,
see the houses that are actually for sale right now across the 53 towns in
`zips.json`, then click one and land in the existing offer analysis with everything
pre-filled.

**Verdict: yes, and it is far cheaper than it looks — we already own every moving
part.** But there is one constraint that shapes the whole design, and one data
property that makes this fundamentally unlike everything else in `market-history`.
Both are below, before the fun bit.

---

## 1. Feasibility: one word

`aggregate.py:626` already does this:

```python
df = scrape_property(location=z, listing_type="sold", date_from=..., date_to=...)
```

**`listing_type="for_sale"` is the same call, same library, same 53 zips, same field
mapper.** `homeharvest` is already installed. There is no new source, no new
dependency, no new auth. I probed it live against Clark (07066):

| | |
|---|---|
| **57 active listings** in one zip | → 53 towns ≈ **2,500–3,000** listings |
| `list_price` | **100%** |
| `lot_sqft` | **89%** |
| `year_built` | 88% |
| `beds` / `full_baths` | 98% |
| **`sqft`** | **47%** ⚠️ |
| `list_date`, `days_on_mls` | 100% |
| `primary_photo`, `property_url` | 100% |
| `text` (description) | 98% |
| **`latitude` / `longitude`** | **100%** ⚠️ see §6 |

Clark's live market: **57 listings, $389,900 – $1,750,000, median $785,000.**

---

## 2. The constraint that shapes everything: the page cannot fetch

**A `file://` page cannot make network requests.** It can't call Realtor.com, and it
can't even `fetch()` a local CSV (that's why `data.js` is a `<script>` global — see
`SPIKE.md` §7). And `listing_scrape` **403s datacenter IPs — it is local-only**
(`CLAUDE.md`), so this can never be a cloud routine either.

So **the button cannot go and get listings.** What it can do is filter a snapshot
that was baked earlier. Concretely:

```
  python3 listings.py          # you, in a terminal, on your own IP. Fetches + bakes.
  open market.html             # the button filters what listings.js already holds
```

**Say the quiet part on the page:** it is not "houses on the market **now**", it is
"houses on the market **as of the last fetch**". A prominent, honest stamp —
*"snapshot: 2 days ago — re-run `listings.py` to refresh"* — and it should get
visibly stale-looking past ~3 days. Anything else is a lie the user acts on.

---

## 3. The data contract is inverted, and this is the real design problem

Everything in `market-history` today is **immutable history**: a house that sold for
$625,000 in March 2024 sold for $625,000 in March 2024, forever. That is why
`sales.csv` can be additive, idempotent, committed, and re-read for three years.

**Listings are perishable.** They are not facts, they are *claims about the present*
that rot. The probe proves it — of Clark's 57 "for sale" rows:

| status | n | |
|---|---|---|
| `FOR_SALE` | 44 | genuinely available |
| `PENDING` | **12** | **already has an accepted offer** |
| `CONTINGENT` | 1 | effectively spoken for |

**23% of what Realtor.com returns as "for sale" is already gone.** Default to
`FOR_SALE` only, and if pendings are shown at all, show them greyed and labelled —
never silently in the list, or you'll drive to a house that's sold.

This inversion has consequences the rest of the repo has never had to think about:

- **A stale snapshot is worse than no snapshot** — an absent list makes you re-run;
  a two-week-old list makes you plan around a house that's under contract.
- **Nothing here is authoritative.** `sales.csv` is the DB. Listings are a *view*
  with a timestamp, and should look like one.

### But there is a genuine prize hiding in this

[`../DEFECTS.md`](../DEFECTS.md) records that **`price_changes` is empty on every one
of the 38,025 rows** — "price-cut history was never captured", and it's the single
thing we most want when judging a rich ask (93 Gaywood, asking 5% over its comps —
did it later cut? *we cannot say*).

**Snapshot the listings daily and we build that dataset ourselves.** Each dated
snapshot is a price observation; diff them and you have the price-cut history, the
list→pending lag, and the withdrawn-and-relisted games — none of which exist in any
source we have. **That argues for committing dated snapshots** (`listings/<date>.json`,
~500KB) rather than gitignoring them like `raw/`.

> **Recommendation: commit them.** The repo is the DB (root `CLAUDE.md`), the files
> are small, and today's perishable listing is tomorrow's irreplaceable price-cut
> record. Gitignoring them throws away the one dataset we can't buy.

---

## 4. Architecture

Two pages, one shared data bake, one link between them.

```
market-history/
  listings.py            # LOCAL ONLY. fetch for_sale x 53 zips -> listings/<date>.json
  listings/<date>.json   # committed. the perishable snapshot, dated (see §3)
  offer/
    market.html          # NEW: browse + filter. The "button".
    listings.js          # generated: window.MARKET = {fetched, listings:[...]}
    index.html           # unchanged: the single-house analyser
    build_data.py        # extended: also bakes listings.js from the newest snapshot
```

**Why a second page rather than a tab on `index.html`:** they are different jobs.
`index.html` answers *"is this one house priced right"*; `market.html` answers *"what
is there"*. Cramming a 2,500-row list into the analyser would wreck a page that is
currently one clean idea. Separate pages, one link.

**The link is the whole point, and it is already built.** `index.html` already
persists its state to the URL hash (added for refresh-survival). So a listing row
just becomes:

```
  market.html  →  index.html#{"town":"Clark","ask":"735000","sqft":"2109",
                              "beds":"3","baths":"2.5","lot":"15085","street":"29 Rutgers Rd"}
```

Click a house → the analyser opens with comps, the seasonal factor, the lot context
and the fragility line already computed for it. **No new analysis code at all.**

---

## 5. The filters

- **Price range** — two inputs, or a dual slider. The primary filter; always visible.
- **Towns** — multi-select over the 53 in `zips.json`, **optional** (empty = all).
  Default sort closest-first by `dist_mi_from_westfield`, which `zips.json` already
  carries and `by_town.csv` is already sorted by.
- **Status** — `FOR_SALE` only by default (§3).
- Worth having, nearly free: **beds/baths minimum**, and **`days_on_mls`** (a house
  sitting 90 days is a different conversation from one listed Tuesday).

**Deliberately NOT a filter: the amenity layers.** Seabra / Trader Joe's / Wawa
distance and commute are colour, never filters — that's the contract in
`layers/README.md` and `share/README.md` caveat 5. Show them on the row; never let
them remove a house from the list.

### What each row shows

Address · town · **ask** · beds/baths · sqft (or "—") · lot · days on market ·
photo · and the one thing no listing site gives you:

> **vs. comps: −$31K** — computed live from `data.js`, the same comp engine as the
> analyser.

That column is the reason to build this instead of using Zillow. Zillow shows you
the ask. Only we can show you the ask *against what similar houses in that town
actually sold for*, seasonally adjusted, from 38,025 real sales.

---

## 6. Two things the probe turned up that change what's possible

**a) `latitude`/`longitude` are on 100% of listings.** Our **sold** rows have no
coordinates at all — that's the blocker behind [`FOLLOWUPS.md`](FOLLOWUPS.md) #3b
(rail proximity, e.g. the line behind 63 Lyons) and #4 (flood). For *listings* that
blocker is simply gone: we could compute distance-to-rail and flood-zone per house on
day one. **Caveat: we could show it, but not price it** — the comp side still can't
say what a track-adjacent house is worth, because the sold rows can't be geocoded to
compare against. So it's a flag, not an adjustment. Still worth having: "⚠️ 80m from
the NEC" on a row you were about to drive to.

**b) `sqft` is 47% filled — and the lot-only mode already covers it.** Half the
listings won't carry a house size, which would have been fatal a week ago. But the
analyser now takes **house size OR lot size or beds/baths**, and `lot_sqft` is on
**89%** of listings. So a sqft-less listing still gets a real (coarser) answer, and
the page already says exactly how coarse. That is a lucky fit, not a plan — but it
means this ships without a data gap.

---

## 7. Honest costs

| | |
|---|---|
| **Fetch time** | 53 zips, sequential, ~2–4s each ≈ **2–4 min** per refresh. Not instant; it's a coffee-length command, not a button. |
| **Payload** | ~2,500 listings × ~14 fields ≈ **400–600 KB**. `data.js` is already 506 KB. **Load `listings.js` only on `market.html`** — don't make the analyser carry it. |
| **Photos** | remote `rdcpix.com` URLs. Fine on `file://` (no CSP), but they're the whole page weight. Lazy-load; consider thumbnails only. |
| **Freshness** | manual. It is a command you remember to run. A cron can't help — **local-only IP** (`CLAUDE.md`). |

---

## 8. What I'd cut from v1

- **No `seen.json`-style state, no "new today", no Slack.** That was the dead
  `house-hunt` routine's job. This is a *browser*, not a scout — it has no memory and
  needs none. (Learnings from house-hunt are fair game; its code is not — the
  independence rule in the root `CLAUDE.md` forbids reading across routines anyway,
  and the fetcher we need already lives in `aggregate.py`.)
- **No saved searches / favourites.** The URL hash already makes any view a
  shareable, bookmarkable link. That's enough.
- **No map.** Tempting with lat/lon on 100% of rows, but it's a big lift and a list
  sorted by distance-from-Westfield answers the same question.

---

## 9. Open questions — decide before building

1. **Commit the snapshots or gitignore them?** I argue **commit** (§3) — the
   price-cut dataset we can't otherwise get is worth 500KB a day. But it is
   churn in a public repo, and it's a real reversal of the "`raw/` is transient"
   rule. **Your call; it's the one genuinely contentious decision here.**
2. **Does `listings.py` live in `market-history/` or become its own routine?** It
   fetches, so it's arguably a sibling of `aggregate.py`. But it feeds `offer/`, and
   cross-routine reads are banned — so it must live **here**. I'd put it at the root
   next to `aggregate.py`, sharing nothing but the pattern.
3. **Pendings: hide, or show greyed?** 23% of the feed. I'd show them greyed with a
   filter toggle — seeing that a house you liked just went pending is *information*.
4. **Do we snapshot on a schedule?** Can't be cloud (local-only IP). A local cron on
   your laptop could, but only when it's awake. Realistically: manual, and the page
   nags when the snapshot is old.

---

## 10. Scope

| step | what |
|---|---|
| 1 | `listings.py` — copy `fetch_listing_scrape`'s mapper, flip to `for_sale`, add `lat/lon/photo/url/days_on_mls/status`, write `listings/<date>.json` |
| 2 | `build_data.py` — bake newest snapshot → `offer/listings.js` |
| 3 | `market.html` — filters (price, towns, status, beds), rows, photo, sort-by-distance, staleness stamp |
| 4 | the **vs-comps** column — reuse `comps()` from `index.html` (extract to a shared `<script>`, or duplicate ~40 lines; **do not** import across pages via module, `file://` blocks ES modules too) |
| 5 | row click → `index.html#<state>` |
| 6 | Sanity: a pending house must never appear in the default list; a sqft-less listing must still analyse via lot; the staleness stamp must go loud past 3 days |

**Estimate: small.** The fetcher exists, the analyser exists, the link mechanism
exists. The genuinely new code is one filtered list view and one bake step.

---

## 11. The one thing that worries me

The tool's whole discipline so far is **"never state a number you can't stand
behind"** — thin buckets refuse, borrowed indices get flagged, sqft fragility is
printed on the face of the page.

A live-market browser is the first thing here that will be **wrong through no fault
of its own** — a house goes under contract an hour after the fetch and the page keeps
cheerfully offering it. There is no version of this that's always right.

So the staleness stamp isn't decoration, it's the same contract as everything else:
**say how much you know, and how old it is.** If we build this, that stamp is the
first thing on the page, not the last.
