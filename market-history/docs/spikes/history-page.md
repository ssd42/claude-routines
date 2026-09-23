# SPIKE — the History page (`sold.html`)

**Status:** proposal. Nothing built.
**Scope, set 2026-07-17:** no scraping changes, no geocoding, no map. A search page over
what has already sold. Everything below uses files we already have.

---

## What it is

One page. A search box, a price range, a few filters, and rows — the same look as
`market.html`, but the verb is *sold* instead of *for sale*.

Type a street, an address, or a town. Get every sale we hold, newest first, with the
details the other pages already show: price, beds, baths, sq ft, lot, year, type, and
what it went for **versus its asking price**.

---

## It's cheaper than I told you an hour ago

I said 40,095 sold rows was ~3.1 MB and we should ship only the last 18 months. **That
was wrong, and the fix is free.**

GitHub Pages gzips everything it serves. As compact arrays, all 40,095 rows are **3.9 MB
raw but 0.8 MB over the wire** — smaller than the market page already sends.

So we ship **all of it**. That matters, because a search page that only knows the last
18 months can't answer *"what did this street sell for?"* — which is the whole point.
The subset idea would have quietly broken the feature it was protecting.

---

## The filters

**Search** — address (`12 Maple`), street (`Maple Ave` finds every sale on it — we hold
**16,213 distinct streets**), or town.

**Town** — a multi-select over the 63, same control as the market page.

**Price** — min and max.

**Beds and baths** — min *and max*. Note the market page only has minimums; this one
wants both, so it's a new control rather than a copy.

**Property type** — house / condo / townhouse / multi.

**Sold when** — a date range, plus presets. Real counts:

| preset | sales |
|---|---:|
| last 30 days | 1,147 |
| last 90 days | 3,284 |
| last year | 12,082 |
| everything | 40,095 |

Sorting: newest, cheapest, dearest, most over/under ask.

### Two traps in the filters

**Anchor the presets to the DATA, not to today.** The window ends **2026-07-15** and
today is the 17th. "Last 30 days" measured from *today* silently means the last 28 days
of data. Measure back from the newest sale we hold and say so.

**Match the town on the `town` field, never on the address text.** `10 Cranford Rd` is a
house in **Glen Rock**, and there are `Westfield Ave` addresses in Clark. The analyser
already gets this right; this page must too.

---

## AC and pool — you were right to flag it, and it's worse than "some issues"

**Pool: there is no field.** Not sparse — absent. `sales.csv` has no pool column and
never did.

**AC: 6%.** `ac_type` is filled on 2,280 of 40,095 rows (2,264 central, 16 window).
A filter on it would show you **6% of the market** and hide 94% that probably do have
AC and simply never said.

The reason is worth knowing, because it's fixable *later* and not now: both facts only
ever lived in the **listing description**, and `sales.csv` never stored it. We added
description capture to `listings.py` today — which is why the **market** page can see
pools and this one can't. Backfilling sold rows means re-running `aggregate.py`, i.e.
changing the scrape, which is out of scope.

**My call: leave both out of v1.** A filter that silently hides 94% of the answer is
worse than no filter — it's the same failure as the sort that ranked houses by how
chatty their agent was. If AC matters later, the honest version is a re-scrape that
stores the description, and then it's a real filter rather than a 6% one.

---

## What we won't do, and why it's fine

**No map.** Sold houses have no coordinates — 40,095 rows, not one lat/lon. Pins would
mean geocoding all of them, and that's a data project, not a page.

**A town-bubble map stays possible later** and needs no geocoding — we have 63 zip
centroids and `by_town.csv` already. It's parked, not blocked. If she misses the map
once she's used the search, it's a small follow-up.

**No new scrape.** Everything comes from `share/sales.csv`, which is already built,
already committed, and already public record.

---

## The honest caveats to put on the page

- **Only ~60% of sales have an asking price.** The vs-ask column is blank for the rest —
  deed records carry the sold price and nothing else. Show the count next to any
  average, the way the other pages do.
- **Sq ft is on 37% of rows.** A blank isn't a zero.
- **Deeds lag ~1 year**, so 2025-26 is MLS-only and not yet corroborated.
- **It cannot rot.** Unlike the market page, a 2024 sale is still a 2024 sale next year.
  No staleness stamp needed — just the window: `2023-07-01 → 2026-07-15`.

---

## Build order

1. `build_data.py` bakes `sold.js` — all 40,095 rows as arrays.
2. `sold.html` — search, filters, rows. Reuses the market page's row markup.
3. Link it from both existing pages.
4. Ship it. It's public record, so no ToS question — this one is the easiest of the
   three to deploy.

**Estimate: small.** No new data, no new source, no geocoding, one new page.
