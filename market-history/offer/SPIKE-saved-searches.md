# SPIKE — town presets on the town picker

**Status:** proposal. Nothing built. **v2** — v1 of this document designed a
create/rename/delete flow for user-defined groups. That was over-built for the ask and
has been cut; see §1.

**Ask, in his words:**

> *"write a spike for adding saved searches to any pages we can pick towns, i want to
> group a bunch of towns into 2-3 prefix ones and allow em to easier just click them
> when i want to check them specifically."*

and, on reading the first draft:

> *"I don't really want to create saved searches, for now just have them as static and
> when spike 1 lands we can actually save, i just want to have some presets for
> myself."*

**Read:** every page with the town multi-select — `market.html`, `sold.html`,
`backtest.html` — gets a row of **named town presets**, hand-authored in a file. One
click ticks all the towns in a preset instead of re-ticking the same eight every
visit. Two to four of them.

**Verdict: yes, and with the management UI cut it is genuinely tiny** — one new file,
three wiring sites, no data changes, no storage decision to make. The interesting part
of this document is no longer the mechanism; it's §7, which proposes the actual presets
from the actual data.

---

## 1. Static presets, not saved searches

Worth separating the readings, because they're different features with different costs
— and the owner has now picked.

| reading | what it is | verdict |
|---|---|---|
| **Static town presets** | a handful of named town lists, defined in code | **v1. This.** |
| **User-created groups** | save / name / edit your own from the UI | **phase 2**, lands with [`SPIKE-persistence.md`](SPIKE-persistence.md) |
| **Full saved searches** | towns *plus* price cap, beds, baths, sort, status | not planned — see below |

The original sentence said "saved searches" but every concrete word after it was about
towns: *group a bunch of towns*, *click them*, *check them specifically*. The follow-up
settles it: **presets, static, in code.**

The argument against full saved searches isn't effort, it's that **the three pages
don't share a filter vocabulary.** `market.html` has status / type / HS floor /
price-cut / new-in-14-days / buffer; `sold.html` has bed and bath *ranges* and a
sold-date window; `backtest.html` has a comp-quality sort and no price floor at all. A
"saved search" would either be per-page — three separate features wearing one name — or
a lowest-common-denominator subset, which is *towns and maybe a price cap*, i.e. almost
exactly this feature with extra rope.

There's also a cheap half-step already shipped, worth knowing before anyone builds
anything: **`market.html` encodes its entire filter state in the URL hash.** A saved
search on that one page is a browser bookmark. Costs nothing, exists today.

**Forward-compatibility:** phase 2 must not have to migrate anything, so v1's preset
shape is already the shape a user-saved group would take —

```js
{ id: "close-in", name: "close in", towns: ["Westfield", "Cranford", …] }
```

`id` is there so a later user edit can override a shipped preset by id rather than by
matching its display name. A `filters: {}` key can be added later without touching the
reader. That is the entire cost of staying forward-compatible: one field nobody reads
yet.

---

## 2. Where the presets live — and why static is the *right* answer, not a compromise

Two options for v1:

| where | |
|---|---|
| **Baked by `build_data.py` into `data.js`** | Right for anything *derived* from the data (distance bands, transit times). Wrong for a hand-picked shortlist: it means editing Python and re-running the bake to change a list of six strings, and it puts a personal shortlist inside a generated file whose first line says *"do not edit."* |
| **A hand-edited constant in `offer/towns-groups.js`** | A literal list of town names in a small file. Edit it, reload the page, done. No bake step, no Python, no generated-file etiquette. |

**Recommendation: a hand-edited constant in `towns-groups.js`.** The presets are an
*opinion about where to look*, not an output of the sale data, and they belong in a file
that says so. `build_data.py`'s job is turning `sales.csv` into facts; a shortlist isn't
one. (This is the same instinct as the two-grains rule in
[`../CLAUDE.md`](../CLAUDE.md): a thing that describes a *place* doesn't get fused into
the machinery that describes *sales*.)

**"He edits a file to change them" is fine, and shouldn't be apologised for.** He already
edits this repo. The list changes maybe monthly. A management UI for a four-item list
that changes monthly is a worse deal than opening a file — it costs a naming dialog, a
delete confirmation, a storage layer, an empty state, and a merge rule in phase 2, in
exchange for saving an edit that takes fifteen seconds. Ship the file.

**And the thing this buys, which a `localStorage` design could never have:**

> **Static presets are identical on every device by construction, because they ship with
> the page.** Define them once, and the laptop, the phone, and a browser you've never
> opened before all have them.

That dissolves the tension the first draft agonised over. `localStorage` groups would
have been per-device — the exact problem
[`SPIKE-persistence.md`](SPIKE-persistence.md) exists to fix — so they'd have been stuck
behind sync, or shipped knowingly broken on the phone. **Static presets have no such
dependency: they are cross-device on day one, with no infrastructure at all.** That is a
positive reason to ship presets first, not a compromise while we wait for something
better.

**Phase 2**, when the sync layer lands: the page reads shipped presets *and* user presets
from the synced blob, unions them by `id`, and gains the create / rename / delete
surface. Nothing in v1 gets rewritten — the reader gains a second source.

---

## 3. A preset expands into ticks, or stays a mode?

Two behaviours, and they diverge more than they look.

**(a) Expand-on-click.** Clicking *close in* ticks its towns in the existing menu. After
that there is no such thing as a preset — just nine ticked towns, which you can untick
one of, or add a tenth to.

**(b) Preset as a filter mode.** The page holds "I am filtering by *close in*" and
resolves the town list at query time. The chip stays lit.

**Recommendation: (a), expand-on-click.** The argument, properly:

- **It adds no new state.** `picked` is already a `Set` of town names on all three pages,
  already persisted (`market.html` / `sold.html`), already URL-encoded on `market.html`,
  already the thing `filtered()` reads. Expansion is `picked = new Set(preset.towns)` and
  a redraw. **Mode (b) introduces a second source of truth for "which towns"**, and every
  place that currently reads `picked` — the filter, the button label, `save()`,
  `restore()`, the URL hash, the results-count line, `reset` — has to learn about it. The
  whole footprint of the feature doubles for a behaviour nobody asked for.
- **The URL stays honest.** `market.html` shares state by putting it in the hash. Under
  (a) a shared link carries the *towns*, and the recipient sees exactly what you saw.
  Under (b) it carries a *preset name*, which resolves only against whatever version of
  the file the recipient's page loaded — so the link either breaks or silently means
  something else. Static presets soften that (both pages ship the same file), but it
  re-breaks the moment phase 2 adds user presets.
- **(b)'s one genuine advantage is a liability here.** A live preset means editing "close
  in" retroactively changes every view that referenced it. For a saved report that's a
  feature; for "show me these towns right now" it means the same bookmark quietly answers
  a different question next month. This repo's discipline is *say what you're looking
  at*; a filter that changes underneath you fails that.
- **It's predictable.** You click the chip, nine boxes tick, you can see all nine and
  adjust one. Nothing is hidden. Mode (b) has to answer "what happens if I untick a town
  while a preset is active?" and every answer is a small surprise.

**The one thing (a) loses**, worth naming: clicking a chip is a *transition*, not a
*state*, so the page can't afterwards say "you're looking at close-in" — only "9 towns".
Cheap mitigation, no new state: after expanding, compare `picked` against each preset
and, on an exact match, label the button **"close in"** instead of "9 towns" and light
that chip. Untick one town and it falls back to "8 towns" and the chip dims — which is
exactly right, because it isn't that preset any more.

**Clicking a second chip replaces the selection.** Add-on-shift is the familiar
convention and is undiscoverable on a phone. If a union is wanted often, it's a fourth
preset — which now costs one line in a file.

---

## 4. UI

Keep it inside the control that already exists. The picker is a button (`#towns-btn`)
with a dropdown (`#towns-menu`) that already carries an actions row (`select all` /
`clear`) above the checkboxes. **Nothing inside the dropdown changes.**

```
  Towns  optional — all if none picked
  ┌──────────────────────────────────────┐
  │ 9 towns                              │  ← #towns-btn (shows the preset name on exact match, §3)
  └──────────────────────────────────────┘
  [ close in ] [ ~$700k ] [ one-seat ]      ← NEW: chips. The entire feature.
  ┌──────────────────────────────────────┐
  │ select all · clear                   │  ← unchanged
  │ ☑ Westfield          0mi · 57        │
  │ ☑ Clark              2mi · 41        │
  │ …                                    │
  └──────────────────────────────────────┘
```

- **Chips sit under the button, outside the dropdown, always visible.** The whole ask is
  "easier just click them" — burying them one tap deep defeats it. Three or four chips is
  one line; wrap on a phone.
- **No create button. No naming dialog. No delete. No long-press menu.** Cut entirely.
  The presets come from the file.
- **Styling:** reuse `.acts button` and the `.seg button.on` segmented-control look the
  pages already use for status / type / HS. An active chip is `.on`. No new visual
  language, barely any new CSS.
- **No empty state to design** — if the file has presets, chips show; if someone empties
  it, the row is absent and the page is exactly what it is today.
- **`backtest.html` needs a caveat.** Its town list is built from `priced` — only houses
  it could grade — so **a preset can name a town that page has no rows for**. Expand it
  anyway and show the miss inline: *"close in — 6 of 9 towns have graded sales here."*
  Silently dropping three towns from a preset on one page is the kind of small lie this
  project keeps refusing to tell.

---

## 5. Three pages, one control — duplicate or share?

The root [`../../CLAUDE.md`](../../CLAUDE.md) forbids cross-routine coupling.
**`market-history` is ONE routine**, so sharing code between its own pages breaks no rule
— `engine.js` is already shared by several. The independence rule is about `house-hunt`
vs `market-history`, not about files inside one folder.

So it's a plain engineering call, and the honest accounting:

**Today the picker is copy-pasted three times.** `drawTowns()` exists in all three files
with real drift: `market.html` has `select all`, `backtest.html` doesn't; `market.html`
counts listings, `sold.html` counts sales, `backtest.html` counts graded houses; and
`market.html` and `sold.html` persist `picked` to `localStorage` while **`backtest.html`
persists nothing at all** (zero `localStorage` references — reload it and your towns are
gone).

| | cost |
|---|---|
| **Duplicate the preset code too** | ~40 lines × 3, *including three copies of the preset list itself* — so editing a preset means editing three files, and the third one gets missed. |
| **Share `towns-groups.js`** | one definition of the presets, one render, one expand. Couples the three pages to one small file. |

**Recommendation: a shared `towns-groups.js`, deliberately narrow.** It owns *only* the
preset list, the chip rendering, the expand-into-a-`Set`, and the name-match for the
label. It does **not** own `drawTowns()`, the counts, or the menu markup — each page
keeps its own, drift and all.

Why that line: the preset logic is **identical** on all three pages (it's just names →
town lists), while `drawTowns()` is genuinely different on each. Extracting the identical
part is free; extracting the different part means inventing configuration to re-create
differences that exist for good reasons. And with static presets the sharing argument is
stronger than it was — the *data* now lives in the shared file too, and a hand-edited
list duplicated three times is a list that will be wrong in two of them.

⚠️ **It must be a plain `<script>` assigning a global, not an ES module.** `file://`
blocks module imports (see [`SPIKE.md`](SPIKE.md) §7) — the same constraint that made
`data.js` a global instead of a fetch.

**Bonus worth taking while in there:** give `backtest.html` the `localStorage` save /
restore the other two have. ~10 lines, same `offer-*` key pattern. Right now that page
forgets your towns on every reload, which makes it the page most in need of one-click
presets and the least able to keep the result.

---

## 6. Deferred to phase 2

Most of what a "what I'd cut from v1" section would have listed is now cut by definition.
What remains, and what it's waiting on:

- **Creating, renaming and deleting presets from the UI** — lands with
  [`SPIKE-persistence.md`](SPIKE-persistence.md), which gives them somewhere to live that
  isn't one device. The v1 shape (§1) already accommodates them.
- **Filter state inside a preset** (price cap, beds, sort) — see §1. The `filters` key is
  reserved and unused.
- **Sharing a preset by URL.** `market.html` already shares the *towns*, which is the
  thing that matters.
- **Auto-suggested presets** ("towns you pick together a lot") — needs usage history we
  don't keep, built on a sample of one person's clicks.
- **Preset colours, icons, ordering, drag-to-reorder.** It's three chips.
- **Presets on `map.html`** — it shows all towns at once and has no picker, so a preset
  would highlight rather than filter. Different feature, same word.

---

## 7. Proposed starter presets

**These are a starting point for him to edit, not a verdict on where to live.** They're
drawn from `window.OFFER_DATA.towns` in `data.js` (`dist` = miles from Westfield, plus
`transit`, `school`, `appr`) and from the comp universe, filtered to his stated target: a
**3-bed, ~1.5-bath house around $700k**.

Method, so the membership is checkable: for each town I took sold **houses** with
**exactly 3 beds and ≤2.5 baths** from the comp universe, and used the **median sale
price** and the **share landing in $600–800k**. Towns with fewer than ~7 such sales are
excluded as too thin to place — the same n-threshold discipline as everywhere else here.

### ① `close in` — within 5 miles of Westfield

> **Westfield · Garwood · Cranford · Fanwood · Scotch Plains · Mountainside · Clark ·
> Springfield · Watchung**

**Why they belong together:** purely `dist ≤ 5` from `zips.json` — the anchor the town
picker already sorts by. This is the home-turf list, and it's a measured fact, not a
preference. It includes Westfield at a **$950k** median 3-bed, well over budget — correct
for a *distance* preset, and exactly why ② exists separately.

### ② `~$700k` — where a 3-bed actually lands in his range

> **Cranford · Fanwood · Scotch Plains · Springfield · Warren · Metuchen**

**Why they belong together:** each has a median 3-bed / ≤2.5-bath house sale between
$600k and $800k *and* at least 40% of such sales landing inside that band — Cranford
$760k (64% in band), Fanwood $718k (67%), Scotch Plains $715k (42%), Springfield $652k
(46%), Warren $751k (45%), Metuchen $625k (46%). This is the "$700k is a normal price
here, not a stretch or a bargain" list. It deliberately drops Westfield ($950k median)
and Colonia ($565k): in one you're at the bottom of the market, in the other you're at
the top.

### ③ `one-seat` — a direct train, under 50 minutes, 3-beds under $800k

> **Metuchen · Maplewood · Montclair · Wayne · Glen Ridge**

**Why they belong together:** each has a station in town, a verified sub-50-minute
**one-seat** ride (Metuchen 45 min on the NEC straight to Penn; Maplewood 40, Montclair
45 and Glen Ridge 35 on Midtown Direct; Wayne 38), and a median 3-bed at or under ~$785k.
**This preset is the deliberate contrast to ① and ②** — Westfield, Cranford, Fanwood and
Scotch Plains are all Raritan Valley Line, which per `transit.notes` has **no peak
one-seat ride to NY** and changes at Newark Penn every time. If commute is the day's
question, this is a genuinely different set of towns, and that's the case for having it
one click away.

⚠️ **Glen Ridge has too few graded 3-bed sales to place on price** — it's in on transit
alone. Left in because it's a real candidate, flagged because the price claim doesn't
cover it.

### ④ `shortlist` — the one he should write himself

> *(empty — for him to fill)*

**Flagged: this is the judgement one.** ①–③ are each a filter over a measured number —
distance, sale price, train minutes — and anyone can check the membership. A shortlist is
an opinion, and that is completely fine **as his own preset in his own file.** What it
must not do is dress up as data: don't name it "the good ones", and don't derive it from
`tier` in `tierlist/tiers.json`, which is a hand-assigned grade, not a measurement. Same
reason [`../layers/README.md`](../layers/README.md) keeps amenity layers as colour and
never as filters — a shipped preset encoding our opinion of a town would quietly become a
filter over a judgement.

**Caveats that apply to all of the above:** the comp universe is ~18% of sales (the rest
lack sqft / beds / baths), medians on 7–20 sales move around, and none of this knows
anything about condition. These lists are a decent starting cut, not a ranking.

---

## 8. Scope

| step | what |
|---|---|
| 1 | `offer/towns-groups.js` — the `PRESETS` constant (§7), render chips, expand into a `Set`, exact-match naming for the button label. A global, not a module. ~40 lines. |
| 2 | Wire into `market.html` — chip row under `#towns-btn`; a click sets `picked` and calls the page's own `save()` + `drawTowns()` + `render()`. |
| 3 | Same wiring in `sold.html` and `backtest.html`; add `backtest.html`'s missing localStorage save / restore (§5). |
| 4 | Sanity: **(a)** a preset naming a town absent from `backtest.html` expands to the towns that exist and *says* it dropped some; **(b)** expanding then unticking one town makes the label fall back from "close in" to "8 towns"; **(c)** a shared `market.html` URL still carries towns, not a preset name; **(d)** `reset` clears the selection and the chips stay. |

**Estimate: small.** One new file, three wiring sites, no data changes, no storage layer,
no bake step.

---

## 9. Open questions

1. **Are ①–③ the right three?** §7 is a proposal off the data, not a decision. The names
   matter as much as the membership — a chip has to say what it means in two words.
2. **Does ① want Westfield in it?** It's the anchor of the distance measure and the one
   town in the ring where his budget doesn't reach the median 3-bed. Keeping it is
   consistent (it's a distance preset); dropping it is more useful. His call.
3. **In phase 2, whose presets are they?** If two people share a synced space, one
   person's shortlist becomes both people's. For a shared house hunt that's probably
   right — but it should be a decision, not a side effect of storing them in the same
   blob.
