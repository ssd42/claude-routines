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
  // ── the hard constraint. Full marks under $750k, worthless by $950k.
  {k:"price", w:30, label:"price",
   get:l => l.p, s:p => p <= 750000 ? 1 : Math.max(0, 1 - (p - 750000) / 200000)},

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

  {k:"beds", w:11, label:"beds",
   get:l => l.bd,
   s:b => b < 3 ? 0.25 : b === 3 ? 0.8 : 1},              // 3 is the floor; 5+ adds nothing

  {k:"baths", w:9, label:"baths",
   get:l => l.ba,
   s:b => b < 1.5 ? 0.25 : b < 2 ? 0.7 : b < 2.5 ? 0.85 : 1},

  {k:"sqft", w:7, label:"house size",
   get:l => l.sq,
   s:x => x < 1000 ? 0.4 : x < 1800 ? 0.4 + 0.6 * (x - 1000) / 800 : 1},

  // ── deliberately HALF the weight the spike first gave it: "newer" is a proxy for
  //    "not a project", and 524 Farley is a 1950 build. Condition is scored from the
  //    copy instead (see HS_FLAVOUR), where it belongs.
  {k:"year", w:6, label:"year built",
   get:l => l.yr,
   s:y => y >= 2010 ? 1 : y <= 1900 ? 0.2 : 0.2 + 0.8 * (y - 1900) / 110},

  // ── shops. LOW weight on purpose: the ask was "closer is better, but don't give it
  //    many points". Averaged across the three so one distant chain can't sink a town.
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
  {k:"ac",       pts:+3, label:"central air",      re:/central (air|a\/?c)|central-air/i},
  {k:"drive",    pts:+2, label:"driveway",         re:/\bdrive ?way\b/i},
  {k:"wallac",   pts:-3, label:"window/wall AC",   re:/window (unit|a\/?c)|wall (unit|a\/?c)|ductless|mini[- ]split/i},
  {k:"asis",     pts:-6, label:"as-is / needs work", re:/\bas[- ]is\b|handyman|\btlc\b|needs work|investor/i},
  // the best amenity signal we have: nobody hides a pool, so absence really is absence
  {k:"pool",     pts:-8, label:"in-ground pool",   re:/in[- ]?ground pool|inground|gunite|heated pool/i},
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

