// SHARED COMP ENGINE — loaded by BOTH analyser.html (the analyser) and market.html
// (the browser). It lives here so the two pages CANNOT disagree: if the market list
// says a house is $31k under comps and the analyser says something else when you
// click it, that's the worst bug this tool could have. One engine, one answer.
//
// Depends on: data.js (window.OFFER_DATA) loaded first.
// Exports (as globals, because file:// blocks ES modules): D, $, MONTHS, THIN, usd,
// usdK, pctStr, digits, med, quart, TIERS, indexFor, indexIsBorrowed, comps,
// compsExact, flipPoint, lotContext, factor.
//
// ── MAP OF THIS FILE ──────────────────────────────────────────────────────────
//   money/quantile helpers         usd, usdK, med, quart, wquant
//   §LEVEL   what a house is worth  comps() / compsExact() — comparable sales, town + size
//     └ §borrow                     compsBorrow() — a thin town tops up from its neighbours
//   §fragile how sure is that       flipPoint(), lotContext()
//   §HS      how much YOU'd like it  hsFor() — a PREFERENCE score, never a valuation
//   §SEASONAL best month to buy      factor() — town × month sold-vs-ask
//
// ── WHERE THE KNOBS ARE (the "what should count, and how much" surface) ─────────
//   THIN            below this many comps a bucket refuses to answer (baked in build_data.py)
//   TIERS           the size/beds/baths tolerance ladder comps() widens along
//   LOT_TOLS        how far lot size may drift before it's dropped as a filter
//   BORROW_*        §borrow: how many neighbours, how far, how hard to trust them
//   HS_FACTORS      the weighted preference model — every factor's weight and scoring curve
//   HS_FLAVOUR      text-mined ± points (garage, pool, as-is …), capped at HS_FLAVOUR_CAP
// Change a number in one of these and the whole tool moves with it — that is the point.
"use strict";

const D = window.OFFER_DATA;
const $ = id => document.getElementById(id);
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
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
/* How far the BUILD YEAR may drift before era stops being a filter. Same shape as the lot
   tolerances above and the same reasoning: match like with like rather than apply a
   blanket "old houses are worth less", which would price a gut-renovated 1910 colonial
   identically to a tired one. `null` is the last rung -- era dropped, and the result says
   so -- because a town with nothing of your vintage should still get an answer. */
const ERA_TOLS = [15, 30];
const LOT_ONLY_TOLS = [0.20, 0.35, 0.50];

/* ── §SIZE — value does not scale 1:1 with floor area ─────────────────────────────
   Until 2026-07-21 a comp was rescaled by (subject_sqft / comp_sqft), i.e. flat $/sqft:
   double the floor area, double the price. Houses don't work that way -- $/sqft FALLS as
   size rises, because land, kitchen and services are already paid for in the first
   1,500sqft. Flat scaling therefore overprices a subject that is bigger than its comps.

   That is not a rare corner. Comps are drawn from a ±15-25% band, but a town's size
   distribution is dense at the small end, so the pool's median sqft sits BELOW the
   subject in 58% of cases. Measured over the 1,121 gradeable 2026 sales, median error by
   how far the subject sat above its own pool:

       subject vs pool median sqft     -6.3%    +0.0%    +3.9%   +12.8%
       median error at b=1.00          -2.23%   -0.83%   +0.37%  +3.67%     spread 5.90pp
       median error at b=0.75          -0.96%   -0.92%   -0.05%  +1.21%     spread 2.17pp

   A pure level shift would move all four columns together; this flattens the GRADIENT,
   which is what makes it a size correction rather than a thumb on the scale. Overall
   median |error| barely moves (9.79% -> 9.71%) because the effect only bites in the
   tails -- that is expected, and is not a reason to think it did nothing.

   ── the exponent is the TOWN's own, like the price index above ──────────────────
   build_data.py fits log(price) ~ log(sqft) per (town, family) over that town's sales
   restated at today's prices, shrunk toward the all-sales slope so a thin town can't
   assert a wild one. It varies a lot, and the variation is real:

       Summit 1.03   Maplewood 0.93   Basking Ridge 0.88   Scotch Plains 0.73
       Edison 0.70   Colonia 0.53     Woodbridge 0.39      Nutley 0.36

   An extra square foot is worth nearly full freight in Summit and almost nothing in
   Nutley. A town with too few sales (or a shape we don't fit) falls back to
   D.sizeElastBase, the all-sales slope, exactly as a thin town borrows the regional
   price index -- and, like that, it is a fact the page can show rather than a constant
   someone picked.

   ⚠️ Do not expect this to predict better than one global number; measured, it doesn't.
   Per-town beat a flat 0.75 on 505 of 1,121 graded 2026 sales and lost on 501, a
   confidence interval straddling zero. Comps are already size-matched to ±15-25%, so
   the exponent has little room to act. It is here because it is DERIVED rather than
   swept for, and because "what does size buy in this town" is a question worth being
   able to answer. Accuracy is not the argument. */
const SIZE_ELAST_FALLBACK = 0.75;
const sizeElast = (town, fam) =>
  (D.sizeElast && D.sizeElast[town + "|" + fam]) || D.sizeElastBase || SIZE_ELAST_FALLBACK;

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
  // same §SIZE scaling as comps(); at ±10% sqft the correction is small, but the two
  // paths must not disagree about what a comp is worth to this house
  const valOf = c => sqft
    ? c[4] * mult(c) * Math.pow(sqft / c[1], sizeElast(c[0], c[9]))
    : c[4] * mult(c);
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

/* ══ §borrow — a thin town tops up its comps from its nearest neighbours ═══════════
   When a town's OWN comps can't reach THIN even at the widest tier, comps() refuses.
   That guards against a confident-but-wrong number, but it also silences the smallest
   towns completely. The fix mirrors the borrowed price index: pool in comps from the
   nearest towns, count each PARTIALLY (weight falls with distance), and lift its $/sqft
   onto THIS town's price shelf via the ratio of the two towns' levels — so we borrow the
   SHAPE of the market next door, never its price level (Green Brook 349 $/sqft borrowing
   from Warren must not inherit Warren's level). Always flagged, never silent.

   It runs ONLY where we can re-anchor honestly: house sq ft known AND this town has a
   measured `ppsf` level (both baked by build_data.py). No sq ft, or no level → we refuse
   exactly as before. Size-less borrowing (re-anchoring raw prices) is deliberately left
   for later; the ratio trick is only clean in $/sqft space.

   The four knobs below are the whole tuning surface — widen them to borrow more freely,
   tighten them to trust only close neighbours. */
const BORROW_NEIGHBOURS = 5;    // at most this many towns may lend to one query
const BORROW_MAX_MI = 8;        // and none further away than this
const BORROW_MIN_W = 0.15;      // a far lender still counts a little, never zero
const borrowWeight = mi => Math.max(BORROW_MIN_W, Math.min(1, 1 - mi / BORROW_MAX_MI));

/* Weighted quantiles: a borrowed comp counts as its weight, an own-town comp as 1.
   Standard weighted quantile — the value where cumulative weight crosses q, averaging the
   two straddling values when it lands exactly on a boundary (so with equal weights the
   MEDIAN matches quart()'s averaging convention). The p25/p75 picks can sit one comp
   apart from quart()'s integer-index ones on some counts — immaterial on a set we are
   already flagging as borrowed and telling the reader to treat loosely. */
function wquant(items) {                       // items: [{v, w}], every w > 0
  const s = [...items].sort((a, b) => a.v - b.v);
  const total = s.reduce((sum, x) => sum + x.w, 0);
  const at = q => {
    const target = q * total;
    let cum = 0;
    for (let i = 0; i < s.length; i++) {
      cum += s[i].w;
      if (cum > target) return s[i].v;
      if (cum === target) return i + 1 < s.length ? (s[i].v + s[i + 1].v) / 2 : s[i].v;
    }
    return s[s.length - 1].v;
  };
  return [at(0.5), at(0.25), at(0.75)];
}

/* The borrowing pass. Returns a comps()-shaped result (mid/lo/hi/tier/sales) marked
   `borrowedComps`, plus `ownN`/`effN`/`borrowFrom` so the page can show exactly whose
   sales it leaned on. Returns null (→ caller refuses) when it can't re-anchor. */
/* Which $/sqft to lift a borrowed comp by. A town's blended rate is really a statement
   about its TYPICAL house -- small homes carry a far higher rate -- so scaling a large
   subject by it invents a mansion. Nutley blends to $377/sqft but its 2,500sqft+ stock
   runs $299, and that 26% gap is most of why a nominally 5,537sqft house there came back
   at $1.75m against a $675k sale. build_data.py now measures the rate inside the same
   SIZE_BANDS the drift index has always used; take the subject's band on BOTH sides of the
   ratio so we compare like with like, and fall back to the blended figure when a town is
   too thin to carry that band. */
function ppsfFor(town, sqft) {
  const t = D.towns[town];
  if (!t) return null;
  const edges = D.sizeBands;
  if (sqft && edges && t.ppsfBand) {
    let lo = null;
    for (const e of edges) if (sqft >= e) lo = e;     // edges ascend; take the last cleared
    const banded = lo != null && t.ppsfBand[String(lo)];
    if (banded) return banded;
  }
  return t.ppsf || null;
}

function compsBorrow(town, sqft, beds, baths, mode, fam) {
  const home = D.towns[town];
  // dollars this comp implies for a `sqft` house, scaled by §SIZE rather than flat $/sqft
  // a lender's sale scales on the LENDER's curve -- borrowing the shape of that market is
  // the whole point of this path; only its price LEVEL gets re-anchored to ours
  const sizeVal = (price, c) => price * Math.pow(sqft / c[1], sizeElast(c[0], c[9]));
  const targetPpsf = ppsfFor(town, sqft);
  if (!sqft || !targetPpsf || !home.near) return null;   // can't re-anchor → refuse as before

  // lenders: the nearest towns within range that carry a level of their own to scale by
  const lenders = home.near
    .filter(([t, mi]) => mi <= BORROW_MAX_MI && D.towns[t] && ppsfFor(t, sqft))
    .slice(0, BORROW_NEIGHBOURS);
  if (!lenders.length) return null;
  const wOf = {}, miOf = {};
  for (const [t, mi] of lenders) { wOf[t] = borrowWeight(mi); miOf[t] = mi; }

  const yearOK = c => mode !== "recent" || D.recentYears.includes(String(c[6]));
  const famOK  = c => !fam || c[9] === fam;
  const toToday = (c, t) => mode === "idx" ? (indexFor(t)[c[6]] || 1) : 1;

  // one pooled record per usable comp. Own town: full weight, its own value. A lender:
  // its $/sqft brought to today (its OWN curve) then lifted to this town's level, weighted.
  const pool = [];
  for (const c of D.comps) {
    if (!yearOK(c) || !famOK(c)) continue;
    if (c[0] === town) {
      // §SIZE applies here too — `ppsf` stays a true $/sqft for display, but the dollars
      // this comp implies for THIS house scale by the same sub-linear exponent as comps()
      const ppsf = (c[4] / c[1]) * toToday(c, town);
      pool.push({c, from: town, w: 1, ppsf, val: sizeVal(c[4] * toToday(c, town), c)});
    } else if (c[0] in wOf) {
      const anchor = targetPpsf / ppsfFor(c[0], sqft);
      const ppsf = (c[4] / c[1]) * toToday(c, c[0]) * anchor;
      pool.push({c, from: c[0], w: wOf[c[0]], ppsf,
                 val: sizeVal(c[4] * toToday(c, c[0]) * anchor, c)});
    }
  }

  // same size/beds/baths ladder as the home engine; accept on EFFECTIVE n (Σ weights).
  // Lot is deliberately not a filter here — we are already in fallback territory and a
  // borrowed lot means little across a town line.
  for (const t of TIERS) {
    const hit = pool.filter(p =>
      Math.abs(p.c[1] - sqft) / sqft <= t.sq &&
      (beds  === null || Math.abs(p.c[2] - beds)  <= t.bd) &&
      (baths === null || Math.abs(p.c[3] - baths) <= t.ba));
    const effN = hit.reduce((sum, p) => sum + p.w, 0);
    if (effN < THIN) continue;

    const [mid, lo, hi] = wquant(hit.map(p => ({v: p.val, w: p.w})));
    const byTown = {};
    for (const p of hit) if (p.from !== town) {
      byTown[p.from] = byTown[p.from] || {t: p.from, n: 0, mi: miOf[p.from], w: wOf[p.from]};
      byTown[p.from].n++;
    }
    return {
      tier: t, n: hit.length, mid, lo, hi,
      ppsf: wquant(hit.map(p => ({v: p.ppsf, w: p.w})))[0],
      bySize: true, degraded: true,
      borrowedComps: true,
      ownN: hit.filter(p => p.from === town).length,
      effN: Math.round(effN),
      borrowFrom: Object.values(byTown).sort((a, b) => b.n - a.n),
      borrowed: mode === "idx" && indexIsBorrowed(town),   // the SEPARATE index flag
      sales: hit
        .sort((a, b) => b.c[6] - a.c[6] || b.c[8] - a.c[8] || b.c[4] - a.c[4])
        .map(p => ({sqft:p.c[1], beds:p.c[2], baths:p.c[3], year:p.c[6], lot:p.c[7],
                    month:p.c[8], vsAsk:p.c[5], sold:p.c[4], today:p.c[4] * toToday(p.c, p.from),
                    val:p.val, town:p.from, w:p.w, borrowed: p.from !== town})),
    };
  }
  return null;
}

/* `fam` (optional): "house" | "attached" | "multi". When given, comps are matched to
   it first -- a Chatham single-family sold at $629/sqft where a Chatham condo sold at
   $482, so pricing a condo against a pooled median that is mostly houses makes it look
   $150k underpriced when it isn't. If the type-matched set is too thin we widen to the
   pooled set and FLAG it (`famDropped`), same as every other tier here: widen, say so,
   or refuse. Costs ~26% of queries at the tight tier, which is the price of not being
   confidently wrong about 1,600 attached homes. */
function comps(town, sqft, beds, baths, mode, lot, fam, built) {
  if (!sqft && !lot && beds === null && baths === null) return null;
  const ix = indexFor(town);
  const mult = c => (mode === "idx" ? (ix[c[6]] || 1) : 1);
  // dollars for THIS house: rescale by SIZE when we know it, else take the comp's own
  // sold price. The exponent is §SIZE -- value climbs with floor area, but slower than
  // 1:1, so a subject bigger than its comps is no longer scaled up flat.
  // The curve is the one belonging to the comp's OWN town and family -- that sale is what
  // we are rescaling, so "what does size buy where this house sold" is the right question.
  // In the main path that town is always the subject's; when types get pooled it keeps a
  // condo on the condo curve.
  const valOf = c => sqft
    ? c[4] * mult(c) * Math.pow(sqft / c[1], sizeElast(c[0], c[9]))
    : c[4] * mult(c);

  let wantFam = fam || null;
  const ok = (c, t, lt, et) =>
    c[0] === town &&
    (mode !== "recent" || D.recentYears.includes(String(c[6]))) &&
    (!wantFam || c[9] === wantFam) &&
    (beds  === null || Math.abs(c[2] - beds)  <= t.bd) &&
    (baths === null || Math.abs(c[3] - baths) <= t.ba) &&
    (!sqft || Math.abs(c[1] - sqft) / sqft <= t.sq) &&
    (lt === null || (c[7] && Math.abs(c[7] - lot) / lot <= lt)) &&
    (et === null || !built || (c[10] && Math.abs(c[10] - built) <= et));

  const build = (hit, t, lotTol, eraTol) => {
    const [mid, p25, p75] = quart(hit.map(valOf));
    return {tier:t, n:hit.length, mid, lo:p25, hi:p75,
            ppsf: sqft ? med(hit.map(c => (c[4] / c[1]) * mult(c))) : null,
            eraTol, eraDropped: !!built && eraTol == null,
            degraded: t.id !== "t1", lotTol, lotDropped: !!lot && lotTol === null,
            bySize: !!sqft, fam: wantFam, famDropped: !!fam && !wantFam,
            borrowed: mode === "idx" && indexIsBorrowed(town)};
  };

  // try the whole ladder type-matched; only if NOTHING clears it do we pool the types.
  // A type-matched set this small is thin enough that its quartiles are shaky -- but it is
  // still describing the RIGHT KIND of home, which matters more. Below ~5 the quartiles
  // stop meaning anything at all, so that is the floor.
  const THIN_FAM = 6;

  const ladder = (min, et) => {
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
          const hit = D.comps.filter(c => ok(c, t, lt, et));
          if (hit.length >= min) { const r = build(hit, t, lt, et); r.noSize = true; return r; }
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
          (baths === null || Math.abs(c[3] - baths) <= t.ba) &&
          (et === null || !built || (c[10] && Math.abs(c[10] - built) <= et)));
        if (hit.length >= min) { const r = build(hit, t, null, et); r.noSize = true; return r; }
      }
      return null;
    }
    if (lot) {
      for (const lt of LOT_TOLS)
        for (const t of TIERS) {
          const hit = D.comps.filter(c => ok(c, t, lt, et));
          if (hit.length >= min) return build(hit, t, lt, et);
        }
    }
    for (const t of TIERS) {
      const hit = D.comps.filter(c => ok(c, t, null, et));
      if (t.id === "t1") strictN = hit.length;
      if (hit.length >= min) return build(hit, t, null, et);
    }
    return null;
  };

  let strictN = 0;
  /* Era widens BEFORE anything else relaxes, and is dropped before the type is. The order
     is a claim about which dimension matters most: a same-size same-town house from the
     wrong decade is still a closer comp than a different KIND of home, so era gives way
     first. When it is dropped the result says so (`eraDropped`) rather than pretending the
     comps were vintage-matched. `built` is optional -- pass nothing and this rung is
     skipped entirely and the engine behaves exactly as it did before. */
  let r = null;
  if (built) for (const et of ERA_TOLS) { r = ladder(THIN, et); if (r) break; }
  if (!r) r = ladder(THIN, null);
  /* A thin set of the RIGHT kind of home beats a fat set of the wrong kind.
     Before this rung existed, a Wayne condo whose own type had only 8 comps at its size
     fell straight through to the pooled set -- 47 houses and 4 condos -- and came back
     $1.14m against a $625k sale, +83%. Wayne's attached homes alone said $748k, +20%.
     Measured across 2026, dropping the family carried a +10.5% median bias on attached
     homes versus +0.0% where it never fired: the pooled answer is confidently wrong, not
     merely uncertain. So try type-matched again at a lower floor first, and SAY it was
     thin rather than quietly padding the sample with the wrong houses. */
  if (r) return r;

  /* ORDER MATTERS HERE, and it is not the intuitive order. Measured across the 2026 sales:
       - compsBorrow is ALREADY type-matched (it takes `fam`), so a borrowed set is the
         right kind of home off MORE data. Putting the thin rung above it downgraded 29
         estimates (15.8% -> 17.9% mean error) and halved their p25-p75 coverage.
       - Pooling the types is the only rung that answers with the WRONG kind of home, and
         it carried a +10.5% median overestimate on attached homes. It goes last.
     So: borrow from next door before answering thin, and answer thin before pooling.
     compsBorrow returns null when it can't re-anchor, so the chain continues below. */
  const b = compsBorrow(town, sqft, beds, baths, mode, fam || null);
  if (b) return b;

  /* A thin set of the RIGHT kind of home still beats a fat set of the wrong kind. A Wayne
     condo with only 8 attached comps at its size fell through to 47 houses and 4 condos
     and came back $1.14m against a $625k sale, +83%; its own type said +33%. Flagged
     `thinFam` because quartiles off 6-9 sales are genuinely shakier -- coverage on this
     rung runs ~38% against the 50% a p25-p75 band should hit, so the band is over-confident
     and the page must say so rather than print it like any other answer. */
  r = ladder(THIN_FAM, null);
  if (r) { r.thinFam = true; return r; }

  if (wantFam) { wantFam = null; r = ladder(THIN, null); }   // pool the types, and flag it
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

/* ══ HS — the Housing Score ═══════════════════════════════════════════════════
   0-100: how much YOU would like this house. NOT what it is worth — comps answer
   that, and comps can be checked against reality. THIS CANNOT. There is no ground
   truth for taste: if it says 82 and you hate the house, the score is wrong by
   definition and the fix is to change the weights. So it shows its working.

   Two rules hold the whole thing up:

   1. BASE IS A WEIGHTED MEAN, NOT A SUM. An unknown factor drops out of the
      numerator AND the denominator, so it neither helps nor hurts — it just makes
      the rest count for proportionally more. That is "don't penalise a missing
      field" done arithmetically rather than by good intentions.

   2. FLAVOUR IS CAPPED AT ±12. The amenity signals come from the listing COPY, and
      copy length correlates with features found at r = +0.41 while correlating with
      price at r = +0.03 — i.e. a chatty agent looks like a better house, and that is
      pure noise. Measured: short blurbs yield a median 0.5 features, long ones 3.0.
      Uncapped, HS would rank estate agents. Capped, verbosity moves a grade at most.

   ⚠️ AMENITIES RANK HOUSES HERE, WHICH layers/README.md OTHERWISE FORBIDS.
   That rule protects VALUATION — comps and the seasonal factor must never be moved
   by how near a shop is, or we would be pricing a house by its groceries. HS is a
   PREFERENCE score, not a valuation, and the owner asked for it explicitly
   (2026-07-17). The line: amenities never touch what a house is WORTH; they may
   touch whether you WANT it. */

const HS_FACTORS = [
  // ── the hard constraint. Full marks under $675k, worthless by $800k. Tightened from
  //    750k/950k on the owner's call (2026-08-19): the old band scored most of the market
  //    as merely "a bit expensive", and at w=30 that let price quietly stop discriminating.
  //    The drop is also twice as steep now -- 125k of runway instead of 200k.
  {k:"price", w:30, label:"price",
   get:l => l.p, s:p => p <= 650000 ? 1 : Math.max(0, 1 - (p - 650000) / 50000)},

  // ── "bigger is better; too big is a commitment". The plateau contains 524 Farley
  //    (6,599 sqft), the favourite of 30+ open houses.
  {k:"lot", w:16, label:"lot size",
   get:l => l.lot,
   s:x => x < 3000 ? 0.25
        : x < 6000 ? 0.25 + 0.75 * (x - 3000) / 3000     // 3k→6k climbs to full
        : x <= 14000 ? 1                                  // 6k–14k the sweet spot
        : x <= 22000 ? 1 - 0.3 * (x - 14000) / 8000       // getting to be a job
        : Math.max(0.3, 0.7 - 0.3 * (x - 22000) / 21560)},// an acre+ is a project

  // ── the commute is the one amenity that is not a nice-to-have.
  {k:"commute", w:12, label:"commute to NY",
   get:(l, T) => T && T.transit && T.transit.min,
   s:m => m <= 35 ? 1
        : m <= 50 ? 1 - 0.25 * (m - 35) / 15              // 35→50: still good
        : m <= 70 ? 0.75 - 0.45 * (m - 50) / 20           // 50→70: real cost
        : Math.max(0, 0.3 - 0.3 * (m - 70) / 50)},

  // ── YOUR tier list. The only OPINION in the model — every other factor is measured.
  //    It earns w=14 because it is largely independent of what HS already scores
  //    (checked: commute r=-0.29, schools r=+0.41, shops r=-0.34), so it adds taste
  //    rather than re-weighting a number we already have. It correlates r=+0.50 with a
  //    town's median price, which is the honest tension: the towns you rank highest
  //    are the ones you can least afford (S-tier: 5% of houses <=$650k; D-tier: 71%).
  //    "unknown"/"unranked" stay null and drop out — they are not an F.
  {k:"tier", w:14, label:"your town tier",
   get:(l, T) => T && T.tier,
   s:t => ({S:1, A:0.85, B:0.65, C:0.4, D:0.2, F:0}[t] ?? null)},

  // ── schools. NJ DOE 2024-25 district deciles, averaged across the three levels we
  //    have. A DISTRICT proxy on a zip: two houses on one street can feed different
  //    elementary schools, so this is a TOWN signal — verify the boundary for a real
  //    house. (Deliberately NOT layers/education/, which is adult degree rates and
  //    correlates with income at r=+0.87 — that would score a town's wealth twice.)
  {k:"school", w:12, label:"schools",
   get:(l, T) => {
     const s = T && T.school;
     if (!s) return null;
     const v = [s.el, s.mid, s.hs].filter(x => x != null);
     return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
   },
   s:d => Math.max(0, Math.min(1, (d - 2) / 7))},   // decile 2→0, 9+→1

  // ── time on market. MEASURED, not assumed: of active listings, the share cutting
  //    price PEAKS at 31-60 days (4.8%) and COLLAPSES past 121 (1.4%). So a long sit
  //    is not linearly better — a house nobody has touched in four months is stubborn
  //    or broken, not a bargain. Fresh gets nothing (no leverage, no information);
  //    1-3 months is the motivated-seller window; past that it decays.
  //    ⚠️ Confound worth remembering: the 121+ group may look non-cutting because the
  //    ones that DID cut already sold and left. Survivorship, not proof.
  {k:"dom", w:8, label:"time on market",
   get:l => l.dom,
   s:d => d <= 7 ? 0.5                                  // brand new: neutral, no info
        : d <= 30 ? 0.5 + 0.3 * (d - 7) / 23            // warming up
        : d <= 90 ? 0.8 + 0.2 * (d - 30) / 60           // the leverage window
        : d <= 150 ? 1 - 0.4 * (d - 90) / 60            // going stale
        : Math.max(0.25, 0.6 - 0.35 * (d - 150) / 150)},// forgotten, or something's wrong

  // ── you want a house, not a condo. Attached homes aren't ruled out (the Type filter
  //    does that) but they don't get to score like a house.
  {k:"type", w:8, label:"house, not a condo",
   get:l => D.family[l.ty] || null,
   s:f => f === "house" ? 1 : f === "multi" ? 0.55 : 0.2},

  {k:"beds", w:11, label:"beds",
   get:l => l.bd,
   s:b => b < 3 ? 0.25 : b === 3 ? 0.8 : 1},              // 3 is the floor; 5+ adds nothing

  {k:"baths", w:9, label:"baths",
   // Scored on FULL baths where we have them (`baf`, added 2026-08-24). The requirement
   // is TWO SIMULTANEOUS SHOWERS -- owner, 2026-08-24: "2 full bathrooms is the min now",
   // "we shower almost always at the same time". A powder room has no shower, and `ba`
   // SUMS halves: 1 full + 2 half reads as 2.0 and would sail straight through. That is
   // not hypothetical -- 324 Green St, Woodbridge is exactly that, and it has ONE shower.
   //   < 2 full         -> 0.25   the gate, however many powder rooms there are
   //     2 full         -> 0.85
   //     2 full + half  -> 1.0    (what used to be scored as "2.5")
   //   >= 3 full        -> 1.0
   // A BELOW-GRADE full bath COUNTS -- his call, 2026-08-24 ("if in the basement its fine
   // right?"). It is a resale markdown, not a disqualification, and the feed does not say
   // which floor a bath is on anyway.
   // Falls back to the old summed curve when `baf` is absent (every row scraped before
   // 2026-08-24), so this is additive and never silently re-scores history.
   get:l => (l.baf != null ? l.baf + (l.ba > l.baf ? 0.5 : 0) : l.ba),
   s:b => b < 2 ? 0.25 : b < 2.5 ? 0.85 : 1},

  {k:"sqft", w:7, label:"house size",
   get:l => l.sq,
   s:x => x < 1000 ? 0.4 : x < 1800 ? 0.4 + 0.6 * (x - 1000) / 800 : 1},

  // ── deliberately HALF the weight the spike first gave it: "newer" is a proxy for
  //    "not a project", and 524 Farley is a 1950 build. Condition is scored from the
  //    copy instead (see HS_FLAVOUR), where it belongs.
  {k:"year", w:6, label:"year built",
   get:l => l.yr,
   // Pre-1940 scores LOW and flat (0.2) rather than sitting mid-ramp — a 1935 build is
   // 1930s wiring/plumbing/insulation regardless of how pretty it is. From 1940 it
   // climbs to full at 2010+. 524 Farley (1950) lands at ~0.44, just above the cliff.
   s:y => y < 1940 ? 0.2 : y >= 2010 ? 1 : 0.3 + 0.7 * (y - 1940) / 70},

  // ── town appreciation. SMALL weight on purpose: it correlates r=+0.61 with price
  //    (already w=30), so its independent signal is modest, and past appreciation does
  //    not promise future. Rewards a town whose value is climbing (your equity climbs
  //    with it). Measured for 20 towns; the rest borrow the regional curve (T.appr.measured
  //    says which) but still score -- a borrowed rate is a real regional fact.
  {k:"appr", w:4, label:"town appreciation",
   get:(l, T) => T && T.appr ? T.appr.pct : null,
   s:p => Math.max(0, Math.min(1, (p - 5) / 35))},   // +5% -> 0, +40% -> 1

  // ── flood. A per-HOUSE factor (FEMA zone at the listing's point), not town-level, so
  //    it keeps HS discriminating WITHIN a town. High-risk (SFHA: A/AE/V/VE) is a real
  //    penalty -- mandatory flood insurance, often thousands a year, plus the risk. X is
  //    fine. Unknown (no coords, or fetch gap) drops out of the weighted mean.
  {k:"flood", w:8, label:"flood risk",
   get:l => l.flood == null ? null : l.flood,      // 1 = high-risk zone, 0 = minimal
   s:hi => hi ? 0 : 1},

  // ── shops. LOW weight on purpose: the ask was "closer is better, but don't give it
  //    many points". Averaged across the three so one distant chain can't sink a town.
  // TAXES. Added 2026-08-24 on the owner's call. NJ property tax is a permanent
  // component of the payment -- ~$1,000/mo on a $12.4k bill, roughly a fifth of the
  // monthly cost -- and it was missing from this model entirely while being one of the
  // few things he has ever stated as a hard number: "under 11k taxes is the ideal up to
  // 13k is possible more than that is really hard to swallow", then "13k yeah thats a
  // better cap on taxes".
  //
  // THE CURVE IS FLAT TO 13k, ON HIS EXPLICIT INSTRUCTION ("points shouldn't be lost
  // until after 13k"). An earlier draft sloped down from 11k and he rejected it -- and
  // he was right: he accepted 496 Outlook's $12,440 without hesitating, which a
  // from-11k slope would have quietly marked down. $11k is where he'd PREFER to land,
  // not where the scoring starts to bite. Zero by 16k, same flat-then-cliff shape as
  // `price`.
  //
  // ⚠️ This must be the BILLED amount, never rate x price. Rate x price is just price
  // wearing a hat -- it would double-count the heaviest factor in the model (w=30) and
  // add zero ranking information within a town. Worse, it is WRONG in his main town:
  // Woodbridge has not revalued since 1986 and West Milford Twp. v. Van Decker bars a
  // sale-triggered reassessment, so a Colonia bill tracks a stale assessed base. That
  // is why 384 Maplewood pays ~$3k less than 496 Outlook while having an extra room.
  //
  // Null until listings.csv is rehydrated with the `tax` column (2026-08-24) -- and a
  // null drops out of BOTH sides of the weighted mean, so this factor is simply inert
  // rather than wrong on older rows. That is the whole point of the mean-over-known
  // design; see CONFIDENCE.
  {k:"tax", w:10, label:"property taxes", fmt:v => "$" + Math.round(v/100)/10 + "k/yr",
   get:l => l.tax,
   s:t => t <= 13000 ? 1 : Math.max(0, 1 - (t - 13000) / 3000)},

  {k:"shops", w:5, label:"shops nearby",
   get:(l, T) => {
     if (!T) return null;
     const d = [T.tj && T.tj.mi, T.wawa && T.wawa.mi, T.seabra && T.seabra.mi]
       .filter(x => x != null);
     return d.length ? d.reduce((a, b) => a + b, 0) / d.length : null;
   },
   s:mi => mi <= 2 ? 1 : mi <= 6 ? 1 - 0.4 * (mi - 2) / 4 : Math.max(0.1, 0.6 - 0.5 * (mi - 6) / 10)},
];

/* Text-mined. ONLY ever applied when the words are actually there — never assumed.
   Coverage measured live (Scotch Plains, 101 descriptions). */
const HS_FLAVOUR = [
  {k:"reno",     pts:+5, label:"renovated",        re:/renovat|updated|remodel|new kitchen/i},
  {k:"garage",   pts:+4, label:"garage",           re:/\bgarage\b/i},
  {k:"ac",       pts:+7, label:"central air",      re:/central (air|a\/?c)|central-air/i},
  {k:"drive",    pts:+2, label:"driveway",         re:/\bdrive ?way\b/i},
  {k:"wallac",   pts:-3, label:"window/wall AC",   re:/window (unit|a\/?c)|wall (unit|a\/?c)|ductless|mini[- ]split/i},
  {k:"asis",     pts:-6, label:"as-is / needs work", re:/\bas[- ]is\b|handyman|\btlc\b|needs work|investor/i},
  // the best amenity signal we have: nobody hides a pool, so absence really is absence
  {k:"pool",     pts:-8, label:"in-ground pool",   re:/in[- ]?ground pool|inground|gunite|heated pool/i},
  // A basement AT ALL is its own fact, separate from finishing one: 29% of listings
  // mention a basement, only 17% call it finished, so ~1 in 8 houses has one the score
  // was blind to. These STACK on purpose -- having the space is worth something, and
  // finishing it is worth more again, so a finished basement lands at +5 and a bare one
  // at +2. Plural matters: a two-family advertises "finished basementS", which \bbasement\b
  // misses -- and a term that fails to fire on the very houses the +3 fires on would break
  // the stacking silently. Negation is a non-issue, measured: "no basement" appears once in
  // 5,391 descriptions, so this needs no guard against it.
  {k:"bsmtany",  pts:+2, label:"a basement",       re:/\bbasements?\b/i},
  {k:"bsmt",     pts:+3, label:"finished basement", re:/finished basement/i},
  // ── Solar, three-way and STACKING (2026-08-20, owner's call: "not a definitely not,
  //    but it would be nice to not value it as highly"). A flat penalty would be wrong,
  //    because the objection is to LEASES, not to panels: a lease or PPA is an inherited
  //    contract that complicates financing and resale, while an owned array is a genuine
  //    plus on the bills. And the copy usually says which -- so the score can too.
  //
  //    Measured on all 5,741 descriptions: 46 real panel mentions (0.80%) -- 5 clearly
  //    leased, 10 clearly owned, 30 silent on ownership, 1 ambiguous. Landing points:
  //      leased    -4 + -4  =  -8   the thing actually objected to; matches the pool
  //      unstated  -4       =  -4   the default, and a real unknown worth diligence
  //      owned     -4 + +4  =   0   neutral, not a bonus -- panels still complicate a
  //                                 reroof, and an SREC deal can still ride along
  //    The one ambiguous line ("sellers have paid off the LEASE on the solar panels")
  //    fires both and lands at -4, which is the honest answer for a sentence that says
  //    owned and leased in the same breath. Stacking gets that for free -- same
  //    mechanism as bsmtany/bsmt above.
  //
  //    THE REGEX REQUIRES A PANEL WORD, NEVER A BARE "solar". 12 listings advertise a
  //    "solarium"; a naive /solar/i would have docked every one of them. Zero are caught.
  //
  // ⚠ ABSENCE IS NOT ABSENCE HERE -- the opposite of the pool rule directly above.
  //    Nobody hides a pool, but plenty of sellers never mention panels. listings.csv HAS
  //    a `solar` column and it is empty on all 5,741 rows, so the copy is the only signal
  //    we have. 538 Cicilia Pl (Scotch Plains, 2026-08-20) has a visible rooftop array and
  //    solar=True in sales.csv, and its description does not contain the word -- so this
  //    rule does not fire on the very house that prompted it. Fixing that means filling
  //    the scraper's solar column, not widening these patterns.
  //    Known miss, accepted: 1 listing whose panels serve a pool only still scores -4.
  {k:"solar",      pts:-4, label:"solar panels",
   re:/solar[- ]?(panel|array|system|electric|energy|shingle|instal)|photovoltaic|\bpv\s+(system|panel|array)|sunrun|sunnova|powerwall|\bsrecs?\b/i},
  {k:"solarlease", pts:-4, label:"…on a lease / PPA",
   re:/(leas\w+|rented)\s+(?:[\w-]+\s+){0,3}solar|solar\s+(?:[\w-]+\s+){0,3}(leas\w+|ppa\b)|power\s+purchase\s+agreement/i},
  {k:"solarowned", pts:+4, label:"…owned outright",
   re:/(owned?|paid[- ]?off|fully\s+paid|purchased)\s+(?:[\w-]+\s+){0,5}solar|solar\s+(?:[\w-]+\s+){0,4}(are\s+|is\s+)?(fully\s+)?(owned|paid[- ]?off|paid\s+in\s+full)/i},
  {k:"deck",     pts:+2, label:"deck / patio",     re:/\bdeck\b|\bpatio\b/i},
  {k:"fence",    pts:+2, label:"fenced yard",      re:/\bfenced\b|fully fenced/i},
];

/* Signals from OUR OWN watching, not from the copy. listings.py is the only source
   that can see these: a price cut we witnessed, and a relist (which resets the feed's
   days_on_market and is the whole reason that file exists). They are facts we
   observed, so unlike the text signals they are never a guess. */
const HS_WATCHED = [
  {k:"cut",     pts:+4, label:"cut its price",  test:l => !!l.cut},
  // DISABLED 2026-07-18 (owner's call — "not for now, can change it up later"). Restore
  // by uncommenting; the mechanism and the -3 are intact.
  // {k:"relist",  pts:-3, label:"relisted",       test:l => (l.spell || 1) > 1},
];
const HS_FLAVOUR_CAP = 12;

function hsFor(l) {
  const T = D.towns[l.t];
  let num = 0, den = 0, all = 0;
  const parts = [];
  for (const f of HS_FACTORS) {
    all += f.w;
    const v = f.get(l, T);
    if (v == null || v === "" || Number.isNaN(v)) { parts.push({...f, known:false}); continue; }
    const sc = Math.max(0, Math.min(1, f.s(v)));
    num += f.w * sc; den += f.w;
    parts.push({k:f.k, label:f.label, w:f.w, known:true, value:v, s:sc});
  }
  if (!den) return null;
  const base = 100 * num / den;

  let flav = 0;
  const found = [];
  const txt = l.tx || "";
  if (txt) for (const f of HS_FLAVOUR) {
    if (f.re.test(txt)) { flav += f.pts; found.push({label:f.label, pts:f.pts}); }
  }
  for (const f of HS_WATCHED) {
    if (f.test(l)) { flav += f.pts; found.push({label:f.label, pts:f.pts}); }
  }
  // window/wall AC is only a negative if there is no central air to override it
  flav = Math.max(-HS_FLAVOUR_CAP, Math.min(HS_FLAVOUR_CAP, flav));

  // Base is scaled to 88 so FLAVOUR has real headroom. Without this, a strong house
  // hit base ~95, +12 flavour clamped to 100, and SEVEN houses tied at a perfect
  // score — a ceiling exactly where the ranking has to do its work. Now 100 means
  // "excellent fundamentals AND everything we want is actually mentioned", which is
  // rare and says something. 88 is the most a listing can score on structured data
  // alone, which is also the honest cap: we cannot know it has a garage if nobody
  // wrote it down.
  return {
    hs: Math.round(Math.max(0, Math.min(100, base * 0.88 + flav))),
    base: Math.round(base),
    flavour: flav,
    // How much of the model actually ran. Two houses at HS 78 are NOT the same claim
    // if one is 55% known. Rank by hs, break ties on this — never the reverse.
    confidence: Math.round(100 * den / all),
    parts, found, hasText: !!txt,
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

