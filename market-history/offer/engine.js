// SHARED COMP ENGINE — loaded by BOTH index.html (the analyser) and market.html
// (the browser). It lives here so the two pages CANNOT disagree: if the market list
// says a house is $31k under comps and the analyser says something else when you
// click it, that's the worst bug this tool could have. One engine, one answer.
//
// Depends on: data.js (window.OFFER_DATA) loaded first.
// Exports (as globals, because file:// blocks ES modules): D, $, MONTHS, THIN, usd,
// usdK, pctStr, digits, med, quart, TIERS, indexFor, indexIsBorrowed, comps,
// compsExact, flipPoint, lotContext, factor.
"use strict";

const D = window.OFFER_DATA;
const $ = id => document.getElementById(id);
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const LIST_TO_CLOSE = 63;            // median days, list -> close (share/README)
const THIN = D.thin;                 // under this a bucket answers nothing

const usd = n => "$" + Math.round(n).toLocaleString("en-US");
const usdK = n => n >= 1e6 ? "$" + (n/1e6).toFixed(2).replace(/0$/,"") + "M"
                           : "$" + Math.round(n/1e3) + "K";
const pctStr = p => (p >= 0 ? "+" : "") + p.toFixed(2) + "%";
const digits = s => { const v = parseFloat(String(s).replace(/[^0-9.]/g, "")); return isNaN(v) ? null : v; };
const med = a => { const s=[...a].sort((x,y)=>x-y), h=s.length>>1;
  return s.length%2 ? s[h] : (s[h-1]+s[h])/2; };
const quart = a => { const s=[...a].sort((x,y)=>x-y);
  return [med(s), s[s.length>>2], s[(3*s.length)>>2]]; };

/* ── the LEVEL estimator: comparable homes, pooled across all months ──────────
   Tolerance ladder. Stop at the first tier holding >= THIN comps. Never falls
   back to another town — that answers a different question. */
const TIERS = [
  {id:"t1", tag:"sqft ±15% · beds ±1 · baths ±1",  sq:.15, bd:1,  ba:1},
  {id:"t2", tag:"sqft ±25% · beds ±1 · baths any", sq:.25, bd:1,  ba:99},
  {id:"t3", tag:"sqft ±25% · any beds or baths",   sq:.25, bd:99, ba:99},
];
/* Every tier stays anchored to the subject's SQ FT. There is deliberately no
   "town-wide average $/sqft" tier: a town's blended $/sqft comes off its typical
   ~1,500sqft houses, and multiplying it by a 9,000sqft house returns a confident
   number about a house unlike anything in the sample. If nothing in the town is
   within ±25% of this size, the honest answer is that we don't know. */
/* Three ways to handle the fact that a 2023 sale is priced in 2023 dollars —
   median $/sqft ran $328 (2023) -> $389 (2026), roughly +19% across the window.

   idx    (default) every sale, each scaled to today's price level by D.priceIndex.
          Keeps the full sample AND removes the stale-price drag. Strictly more
          data than `recent` for the same recency correction.
   recent only the last two years. Honest, but it drops ~57% of the comps, and
          68% of town/size queries fall under the 10-comp floor as a result.
   raw    every sale at face value. Understates today's level; here for comparison.

   Only the LEVEL is affected. The seasonal factor is a PERCENTAGE vs ask —
   scale-free — so market drift doesn't bias it, and restricting its years would
   just gut n for nothing. */
/* The index is the TOWN's own wherever the town has the sales to measure one
   (46 of 53 do). This matters far more than it looks: across the same window
   Green Brook rose 8.5% and Maplewood 54.4%. Using the regional +19% on Colonia —
   which really rose ~11% — inflated its comps by tens of thousands. The 7 towns
   too thin for their own curve borrow the regional one, and the page SAYS so. */
const indexFor = town => D.townIndex[town] || D.priceIndex;
const indexIsBorrowed = town => !D.townIndex[town];
function ppsfOf(c, mode, ix) {
  const raw = c[4] / c[1];
  return mode === "idx" ? raw * (ix[c[6]] || 1) : raw;
}
/* Comps match on whatever you gave us. Both HOUSE sq ft and LOT sq ft are optional;
   supply either, or both, and the engine uses what it has.

   * with house sq ft  -> value each comp at its $/sqft, scaled to this house's size.
   * without it        -> value each comp at its sold price directly. Coarser (it can't
                          adjust for a size gap) so the size filter has to do the work.

   The lot is used the moment it's present -- there is no switch. It is genuinely
   informative: at a fixed house size these two sit on lots bigger than ~86% of their
   town's sales, and ignoring that pooled them with land half their size, understating
   both. But towns value land very differently (the big-lot half sells +4% higher in
   Colonia, +48% in Basking Ridge), so lot is a FILTER -- match like with like -- never
   a blanket adjustment.

   Lot tolerance widens before the house filter does: size is the dimension we least
   want to relax. If nothing in the town sits on a comparable lot, the lot is DROPPED
   and the page says so. */
const LOT_TOLS = [0.30, 0.50];
const LOT_ONLY_TOLS = [0.20, 0.35, 0.50];

/* "Match exactly" — the tightest filter the data allows, with the 10-comp floor
   DISABLED. Everywhere else the tool refuses to answer from a handful of sales; here
   you've asked to see them anyway, so it answers and shouts about the sample size.
   No widening ladder: if there are 3 matches, you get 3 matches, clearly labelled.
   Two houses is not a market -- treat it as a sighting, not a finding. */
const EXACT = {id:"x", tag:"sqft ±10% · beds exact · baths exact", sq:.10, bd:0, ba:0};
const EXACT_LOT = 0.20;

function compsExact(town, sqft, beds, baths, mode, lot) {
  const ix = indexFor(town);
  const mult = c => (mode === "idx" ? (ix[c[6]] || 1) : 1);
  const valOf = c => sqft ? (c[4] / c[1]) * mult(c) * sqft : c[4] * mult(c);
  const hit = D.comps.filter(c =>
    c[0] === town &&
    (mode !== "recent" || D.recentYears.includes(String(c[6]))) &&
    (beds  === null || c[2] === beds) &&
    (baths === null || c[3] === baths) &&
    (!sqft || Math.abs(c[1] - sqft) / sqft <= EXACT.sq) &&
    (!lot  || (c[7] && Math.abs(c[7] - lot) / lot <= EXACT_LOT)));
  if (!hit.length) return {failed:true, strict:0, exact:true, none:true};
  const [mid, p25, p75] = quart(hit.map(valOf));
  return {
    tier: {id:"x", tag: [sqft ? EXACT.tag : "beds exact · baths exact",
                         lot ? `lot ±${EXACT_LOT * 100}%` : null].filter(Boolean).join(" · ")},
    n: hit.length, mid, lo: p25, hi: p75,
    ppsf: sqft ? med(hit.map(c => (c[4] / c[1]) * mult(c))) : null,
    bySize: !!sqft, exact: true, lotTol: lot ? EXACT_LOT : null,
    borrowed: mode === "idx" && indexIsBorrowed(town),
    sales: hit.map(c => ({sqft:c[1], beds:c[2], baths:c[3], year:c[6], lot:c[7], month:c[8],
                          vsAsk:c[5],
                          sold:c[4], today: c[4] * mult(c),   // the SAME sale, at today's prices
                          val:valOf(c)}))
      // newest first: a 2026 sale tells you more about today than a 2023 one, and it
      // needs no index adjustment either. Ties break on price, high to low.
      .sort((a, b) => b.year - a.year || b.month - a.month || b.sold - a.sold),
  };
}

/* `fam` (optional): "house" | "attached" | "multi". When given, comps are matched to
   it first -- a Chatham single-family sold at $629/sqft where a Chatham condo sold at
   $482, so pricing a condo against a pooled median that is mostly houses makes it look
   $150k underpriced when it isn't. If the type-matched set is too thin we widen to the
   pooled set and FLAG it (`famDropped`), same as every other tier here: widen, say so,
   or refuse. Costs ~26% of queries at the tight tier, which is the price of not being
   confidently wrong about 1,600 attached homes. */
function comps(town, sqft, beds, baths, mode, lot, fam) {
  if (!sqft && !lot && beds === null && baths === null) return null;
  const ix = indexFor(town);
  const mult = c => (mode === "idx" ? (ix[c[6]] || 1) : 1);
  // dollars for THIS house: rescale by $/sqft when we know its size, else take the
  // comp's own sold price
  const valOf = c => sqft ? (c[4] / c[1]) * mult(c) * sqft : c[4] * mult(c);

  let wantFam = fam || null;
  const ok = (c, t, lt) =>
    c[0] === town &&
    (mode !== "recent" || D.recentYears.includes(String(c[6]))) &&
    (!wantFam || c[9] === wantFam) &&
    (beds  === null || Math.abs(c[2] - beds)  <= t.bd) &&
    (baths === null || Math.abs(c[3] - baths) <= t.ba) &&
    (!sqft || Math.abs(c[1] - sqft) / sqft <= t.sq) &&
    (lt === null || (c[7] && Math.abs(c[7] - lot) / lot <= lt));

  const build = (hit, t, lotTol) => {
    const [mid, p25, p75] = quart(hit.map(valOf));
    return {tier:t, n:hit.length, mid, lo:p25, hi:p75,
            ppsf: sqft ? med(hit.map(c => (c[4] / c[1]) * mult(c))) : null,
            degraded: t.id !== "t1", lotTol, lotDropped: !!lot && lotTol === null,
            bySize: !!sqft, fam: wantFam, famDropped: !!fam && !wantFam,
            borrowed: mode === "idx" && indexIsBorrowed(town)};
  };

  // try the whole ladder type-matched; only if NOTHING clears it do we pool the types.
  const ladder = () => {
    if (!sqft && lot) {
      // NOT the TIERS ladder here. Its tolerances are sqft-shaped and its last rung
      // drops beds/baths entirely -- harmless when sqft anchors the set, catastrophic
      // without it: `t3` collapsed to "any house in this town on a similar lot" and
      // priced a 1-bed Chatham flat off 13 quarter-acre HOUSES at a $1.64m median,
      // reporting it as $1.5m underpriced. With no sqft, beds and baths are the only
      // shape we have, so they never get dropped.
      for (const lt of LOT_ONLY_TOLS)
        for (const t of [{id:"L1", tag:"lot-matched · beds ±0 · baths ±0.5", bd:0, ba:.5},
                         {id:"L2", tag:"lot-matched · beds ±1 · baths ±1",   bd:1, ba:1}]) {
          const hit = D.comps.filter(c => ok(c, t, lt));
          if (hit.length >= THIN) { const r = build(hit, t, lt); r.noSize = true; return r; }
        }
      return null;
    }
    if (!sqft) {
      for (const t of [{id:"b1", tag:"beds ±0 · baths ±0.5", bd:0, ba:.5},
                       {id:"b2", tag:"beds ±1 · baths ±1",   bd:1, ba:1}]) {
        const hit = D.comps.filter(c =>
          c[0] === town &&
          (mode !== "recent" || D.recentYears.includes(String(c[6]))) &&
          (!wantFam || c[9] === wantFam) &&
          (beds  === null || Math.abs(c[2] - beds)  <= t.bd) &&
          (baths === null || Math.abs(c[3] - baths) <= t.ba));
        if (hit.length >= THIN) { const r = build(hit, t, null); r.noSize = true; return r; }
      }
      return null;
    }
    if (lot) {
      for (const lt of LOT_TOLS)
        for (const t of TIERS) {
          const hit = D.comps.filter(c => ok(c, t, lt));
          if (hit.length >= THIN) return build(hit, t, lt);
        }
    }
    for (const t of TIERS) {
      const hit = D.comps.filter(c => ok(c, t, null));
      if (t.id === "t1") strictN = hit.length;
      if (hit.length >= THIN) return build(hit, t, null);
    }
    return null;
  };

  let strictN = 0;
  let r = ladder();
  if (!r && wantFam) { wantFam = null; r = ladder(); }   // pool the types, and flag it
  if (r) return r;
  return {failed:true, strict:strictN, noSize:!sqft};

}

/* ── how fragile is the verdict? ─────────────────────────────────────────────
   Sq ft is the most load-bearing input here and we have NO independent check on it:
   the MLS is the only source that carries one (99% of deed rows have none), and at
   93 Gaywood the tax card said 1,188 where the MLS said 1,108 -- a 7% gap that was
   enough to move the answer. So walk sq ft outward until the verdict changes and say
   where that happens. */
function flipPoint(town, sqft, beds, baths, mode, ask, lot) {
  const at = s => {
    const c = comps(town, s, beds, baths, mode, lot);
    if (!c || c.failed) return null;
    return ask > c.hi ? "above" : ask < c.lo ? "below" : "inside";
  };
  const now = at(sqft);
  if (!now) return null;
  const STEP = 5, LIMIT = 0.6;
  for (let d = STEP; d <= sqft * LIMIT; d += STEP) {
    for (const s of [sqft + d, sqft - d]) {
      if (s < 300) continue;
      const v = at(s);
      if (v && v !== now)
        return {from: now, to: v, sqft: Math.round(s), pct: (s - sqft) / sqft, bigger: s > sqft};
    }
  }
  return {from: now, stable: true};
}

function lotContext(town, sqft, lot) {
  const near = D.comps.filter(c =>
    c[0] === town && c[7] && (!sqft || Math.abs(c[1] - sqft) / sqft <= 0.15));
  if (near.length < THIN) return null;
  const lots = near.map(c => c[7]).sort((a, b) => a - b);
  return {
    pct: Math.round(100 * lots.filter(x => x < lot).length / lots.length),
    medLot: lots[lots.length >> 1],
    n: near.length,
  };
}

/* ── the SEASONAL estimator: town x closing month, every house type ───────────
   Its own ladder, resolved PER MONTH: a town can have a fat June and a thin
   January. Also never crosses town lines. */
function factor(town, m, mode) {
  const T = D.towns[town];
  // "Last 2 years only" re-cuts BOTH panels. Anything else uses the full window: the
  // seasonal factor is a PERCENTAGE over ask -- scale-free -- so the price index that
  // separates `idx` from `raw` simply doesn't apply to it, and pretending otherwise
  // would just be theatre. Only the time window genuinely changes this number.
  const recent = mode === "recent";
  const src = recent ? (T.recent || {}) : T;
  const label = recent ? " (last 2 yrs)" : "";

  const mo = (src.months || {})[m];
  if (mo && mo.n >= THIN)
    return {...mo, tier:"month", recent, tag:`${town} × ${MONTHS[m-1]}${label}`};
  const se = (src.seasons || {})[D.seasonOf[m]];
  if (se && se.n >= THIN)
    return {...se, tier:"season", recent,
            tag:`${town} × ${D.seasonOf[m]}${label} — ${MONTHS[m-1]} alone was too thin`};
  const al = src.all;
  if (al && al.n >= THIN)
    return {...al, tier:"year", recent,
            tag:`${town}, whole year${label} — even the season was too thin`};

  // the recent window can genuinely run out of sales where the full one doesn't.
  // Fall back to the full window rather than refuse -- but SAY that's what happened.
  if (recent) {
    const f = factor(town, m, "idx");
    if (f) return {...f, borrowedWindow: true,
                   tag:`${f.tag} — the last 2 years alone were too thin here`};
  }
  return null;
}

