// TOWN PRESETS — named sets of towns, one click, on every page with a town picker.
// Loaded by market.html, sold.html and backtest.html AFTER data.js. Plain globals, no
// module: these pages open from file://, which blocks ES modules.
//
// See SPIKE-saved-searches.md for the reasoning. The short version:
//
//   * The presets are STATIC and hand-edited, right here in this file. There is no
//     "save as group" button, no naming dialog, no delete. Editing a file to change a
//     four-item list is cheaper than a management UI, and it is not a compromise --
//     because they ship with the page, they are identical on the laptop, the phone and
//     a browser you have never opened before, with no storage and no sync. When
//     SPIKE-persistence.md lands, YOUR OWN saved groups join these; these stay.
//
//   * Clicking a chip EXPANDS it into ticked towns, rather than holding a "filtering by
//     close-in" mode. `picked` stays the single source of truth on all three pages, so
//     nothing else -- the filter, the URL hash, save/restore, the count line -- has to
//     learn a second concept. A shared market.html link then carries the TOWNS, so the
//     recipient sees what you saw, instead of a preset name that resolves against
//     whatever version of this file their page happened to load.
//
//   * Clicking a second chip REPLACES the selection. Shift-to-add is a desktop habit and
//     invisible on a phone; if a union is wanted often it costs one line below.
//
// ── EDITING THIS LIST ──────────────────────────────────────────────────────────────
// Add, remove, reorder freely -- a name and a list of towns is the whole schema. Two
// rules worth keeping:
//   1. A town name must match data.js exactly, or it is silently skipped. `check()` at
//      the bottom logs any that don't, so open the console after editing.
//   2. Prefer a preset whose membership is a MEASURED fact (a distance, a price band, a
//      train time) over one that encodes an opinion about which towns are good. Opinions
//      are fine in `shortlist` -- it is yours -- but a shipped preset that quietly ranks
//      towns turns a judgement into a filter, which is the thing layers/README.md refuses
//      to do with amenities for the same reason.
"use strict";

const TOWN_PRESETS = [
  {
    id: "trifecta",
    name: "trifecta",
    // The owner's own three. This one is an OPINION, not a query -- nothing measured
    // picks exactly these -- and that is entirely fine, because it is his file and his
    // shortlist. The only rule is that it must not pretend otherwise: it is not called
    // "the best towns", and it is not derived from tierlist/tiers.json, because a
    // hand-assigned grade dressed as data quietly becomes a filter over a judgement.
    // (Note: the data spells it "Scotch Plains".)
    towns: ["Scotch Plains", "Colonia", "Clark"],
  },
  {
    id: "s-tier",
    name: "S Tier",
    // The S row of tierlist/tiers.json as of its 2026-07-20 edit, in its own order
    // (best first -- that file says order within a tier is meaningful).
    //
    // Copied, deliberately NOT read from that file at runtime. Two reasons. The tier list
    // is a scratch tool that rewrites itself in full on every edit and nothing in the
    // pipeline reads it; wiring a shipped page to it would make an offhand re-rank
    // silently change what this button does. And these pages open from file://, which
    // cannot fetch a local JSON at all. So: re-copy this list when you re-rank, and the
    // chip keeps meaning what it meant when you set it.
    //
    // This one is openly a judgement -- the file it came from calls itself "Opinion, not
    // data" -- and the name says so, which is the whole test. A preset may encode your
    // opinion of a town; it just must not be dressed up as a measurement.
    towns: ["Westfield", "Cranford", "Scotch Plains", "Chatham", "Glen Rock", "Montclair",
            "Mountain Lakes", "Essex Fells", "Clark", "Glen Ridge", "Basking Ridge",
            "North Caldwell", "Watchung", "Short Hills", "Warren", "Madison",
            "Franklin Lakes", "Caldwell", "Colonia", "Bridgewater", "Cedar Grove"],
  },
  {
    id: "luxury",
    name: "Luxury",
    // Towns whose MEDIAN single-family sale since Jan 2025 is $1m or more, most expensive
    // first. 20 of 75, from Short Hills ($2.40m) down to Mountainside ($1.005m). Every
    // town here had at least 15 house sales in the window, so none of these is a median
    // off a handful of trades.
    //
    // Median, not average, and the difference is not academic: on the average the list
    // grows to 32 towns and picks up Scotch Plains, Caldwell and Berkeley Heights --
    // places where a few big sales drag the mean over $1m while a typical house trades
    // far below it. Scotch Plains is in `trifecta` precisely because it is affordable;
    // a "Luxury" chip that included it would be measuring the wrong thing.
    //
    // Unlike `trifecta` and `S Tier` this one is a QUERY, not an opinion -- anyone can
    // recompute it. Re-derive it when the data moves: single-family sales, sold_date >=
    // 2025-01-01, at least 15 per town, median >= 1e6.
    towns: ["Short Hills", "Franklin Lakes", "Essex Fells", "Summit", "Chatham",
            "Millburn", "Montclair", "Westfield", "Livingston", "Glen Ridge",
            "Mountain Lakes", "Madison", "Basking Ridge", "Mendham", "Bernardsville",
            "South Orange", "Glen Rock", "Maplewood", "Watchung", "Mountainside"],
  },
  // Add more the same way -- a name and a list of towns is the whole schema:
  //   { id: "commute", name: "one-seat", towns: ["Metuchen", "Maplewood"] },
];

/* Does the current selection exactly equal a preset? Used to label the button "close in"
   instead of "9 towns" and to light the chip. Untick one town and it stops matching --
   which is right, because it is not that preset any more. Compared against what the page
   can actually OFFER, so backtest.html (whose list omits towns with no graded sales)
   still lights the chip when it holds everything it could hold. */
function presetMatch(picked, available) {
  for (const p of TOWN_PRESETS) {
    const want = available ? p.towns.filter(t => available.has(t)) : p.towns;
    if (want.length && want.length === picked.size && want.every(t => picked.has(t)))
      return p;
  }
  return null;
}

/* Expand a preset. `available` is the set of towns this page can offer, or null for
   "all of them". Returns the new selection AND the towns that were asked for but are not
   on this page -- backtest.html only lists towns with gradeable sales, so a preset can
   genuinely lose members there and the page has to say so rather than quietly tick 7 of 9. */
function applyPreset(preset, available) {
  const have = preset.towns.filter(t => !available || available.has(t));
  const missing = preset.towns.filter(t => available && !available.has(t));
  return {picked: new Set(have), missing};
}

/* Draw the chip row. `el` is the container, `picked` the live Set, `available` the towns
   this page offers (or null), `onPick(preset)` fires on click. Styling leans on whatever
   the host page already uses for its segmented controls -- `.seg button` / `.on` -- so
   this adds no new visual language. */
// Not an injection guard -- everything here is hand-written above -- but this file is
// meant to be edited, and a town or preset name carrying an apostrophe or an ampersand
// would otherwise break out of the title attribute and mangle the row.
const escAttr = s => String(s == null ? "" : s)
  .replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function drawPresetChips(el, picked, available, note) {
  if (!el) return;
  const active = presetMatch(picked, available);
  const chips = TOWN_PRESETS.map(p => {
    const shown = available ? p.towns.filter(t => available.has(t)) : p.towns;
    if (!shown.length) return "";            // nothing of this preset exists here
    // The chip name alone is opaque -- "trifecta" tells you nothing about what it does or
    // which towns it holds. So the row is LABELLED, each chip lists its towns underneath,
    // and the hover title repeats them in full. A control you have to click to understand
    // is a control you won't use.
    // Three names fit on a chip; twenty-one do not, and a chip that wraps to five lines
    // is worse than one that says nothing. Preview a few, count the rest, and let the
    // hover title carry the full list.
    const PREVIEW = 3;
    const label = shown.length <= PREVIEW + 1
      ? shown.join(" · ")
      : shown.slice(0, PREVIEW).join(" · ") + ` +${shown.length - PREVIEW} more`;
    return `<button type="button" data-preset="${escAttr(p.id)}"
      class="${active && active.id === p.id ? "on" : ""}"
      title="Pick these ${p.towns.length} towns: ${escAttr(p.towns.join(", "))}"
      >${escAttr(p.name)} <i>${escAttr(label)}</i></button>`;
  }).join("");
  el.innerHTML =
    `<span class="preset-lab">Town presets</span>` +
    `<span class="preset-hint">one click picks a group</span>` +
    chips + (note ? `<span class="preset-note">${escAttr(note)}</span>` : "");
}

const presetById = id => TOWN_PRESETS.find(p => p.id === id) || null;

/* Editing check. Any town named above that data.js has never heard of would silently
   tick nothing, so say it out loud rather than let a chip look broken. */
(function check() {
  if (typeof window === "undefined" || !window.OFFER_DATA || !window.OFFER_DATA.towns) return;
  const known = window.OFFER_DATA.towns;
  const bad = [];
  for (const p of TOWN_PRESETS)
    for (const t of p.towns) if (!(t in known)) bad.push(`${p.name}: "${t}"`);
  if (bad.length)
    console.warn("towns-groups.js — town names not in data.js, these will be skipped:\n  "
                 + bad.join("\n  "));
})();
