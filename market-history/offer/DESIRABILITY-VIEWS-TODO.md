# Desirability page — three views

High-level only. No implementation detail here; decide the mechanics when we build.

## Why

The page answers one question today ("which parts of this town are the nice
parts?") but not the two I actually shop with: *how expensive is this
neighborhood in real dollars*, and *how does it compare to neighborhoods in
other towns*. Three views, one shared map, a toggle between them.

---

## View 1 — Town-relative (what we have now)

Keep it exactly as it is. Colors run red→green across the neighborhoods of a
single town, scaled to that town alone. Good for "within Cranford, which pocket
is the good one." This becomes the default view; nothing about it changes.

## View 2 — Absolute dollars

Same map, same neighborhoods, but the color now means a real price, not a rank.
Red = cheap, green = expensive, with ~$800k sitting at the middle of the
spectrum. A neighborhood that's the best part of a cheap town should read as
mid/low here even though View 1 paints it green — that difference is the point.

Then drop the active for-sale listings on top, so I can see at a glance whether
what's on the market is landing in the expensive pockets or the cheap ones.

**Open question — the scale.** A plain linear ramp from $0 to $1.6M wastes most
of the color range, because almost everything we care about is $400k–$1M, and a
few towns run to $2.4M and would peg the top. Worth trying a scale that spends
most of its color between roughly $500k and $1.1M and compresses the tails, so
the high-end towns still show as "very expensive" without flattening everything
below them into one shade. Pick the exact shape when we can look at the real
distribution.

## View 3 — All towns, one scale

The hard one. Every neighborhood we have data for, across every town, colored on
a single shared scale so they're directly comparable to each other.

What I'm hunting: a house inside my price range that sits in a neighborhood that
is otherwise expensive — a cheap house in a good area, rather than a fairly
priced house in an average one. That's only visible when the towns are on the
same scale.

Needs thought: our coverage isn't equal across towns, and a neighborhood in a
town with thin data shouldn't be presented with the same confidence as one with
lots of sales. Decide how to handle the thin ones (show them differently, or
hold them back) before building.

---

## Shared

- One toggle, three views, map state (zoom/position) survives the switch.
- Listings overlay available on all three, not just View 2.
- Legend has to change with the view — a rank legend and a dollar legend are
  different things and shouldn't look alike.

---

# Towns to add

Extend the page north/west into the Morris–Somerset side:

- New Providence
- Berkeley Heights
- Chatham
- Madison
- Stirling
- Millington

Basking Ridge is already on the page, so it's off this list. West Orange was added
on 2026-09-25 (1,058 single-family sales, 97 for sale) and is live.

Things to sort out before building them:

- **Stirling and Millington aren't towns.** They're sections of Long Hill
  Township, same as Gillette which we already have. Sales data is recorded by
  township, so decide whether they each get their own page entry or whether the
  right move is one Long Hill entry with all three inside it.
- **Chatham is two places** — the Borough and the Township are separate
  municipalities with separate tax rates. Pick one, or carry both, but don't
  silently blend them.
- These towns are pricier than most of what's on the page now. They're a good
  stress test for the View 2 dollar scale and a big part of why View 3 matters —
  if the shared scale works, a cheap pocket of Chatham or Berkeley Heights is
  exactly the thing I'm looking for.
