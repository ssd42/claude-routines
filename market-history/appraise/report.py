"""Stage 10 — render the appraisal as a local page and open it.

Reads run/context.json (deterministic) and run/verdict.json (what the model wrote), and
emits run/report.html. No dependencies, no build, opens from file:// — the same
constraints every other page in this project runs under.

  python3 report.py            # render + open
  python3 report.py --demo     # render from context.json alone, before a verdict exists

COLOUR — decided by running the validator, not by eye (validate_palette.py):
  The site's diverging pair #8c2f2a / #2c6459 scores OKLab dE 7.1 under deuteranopia:
  above the 6.0 floor, below the 8.0 target. The skill's rule is that 6-8 is legal ONLY
  with secondary encoding, so over/under is NEVER colour alone here — every one carries
  a +/- sign and a written label.
  Saturating the green was tested and makes it WORSE (7.1 -> 6.2 -> 5.4): deuteranopia
  collapses the red-green axis, so a greener green moves into the confusion, not away
  from it. The muted teal is the right choice and its low chroma is what buys the
  separation. Do not "fix" it.
"""
import argparse, json, subprocess, sys
from pathlib import Path

RUN = Path(__file__).resolve().parent / "run"
usd = lambda n: "$" + format(int(round(n)), ",")
usdk = lambda n: f"${n/1e6:.2f}M".replace("0M", "M") if n >= 1e6 else f"${round(n/1e3):,}K"


def scale(lo, hi, pad=0.10):
    span = max(hi - lo, 1)
    return lo - span * pad, hi + span * pad


def x(v, a, b):
    return max(0.0, min(100.0, (v - a) / max(b - a, 1) * 100))


def money_axis(a, b, ticks=5):
    out = []
    for i in range(ticks + 1):
        v = a + (b - a) * i / ticks
        out.append(f'<div class="tick" style="left:{i/ticks*100:.2f}%">'
                   f'<span>{usdk(v)}</span></div>')
    return "".join(out)


def headline(ctx, v, ask):
    """One axis, in dollars. Everything that is a price sits on it and is directly
    comparable — the comp band, our range, the three tiers, the ask. A second scale
    would be the one chart mistake this skill calls out by name."""
    anc = ctx.get("anchor") or {}
    if anc.get("failed") or not v.get("range"):
        return ('<p class="none">No value range — the engine could not price this house '
                f'from its own town\'s sales ({anc.get("reason","")}). '
                'Everything below still stands; a range does not.</p>')
    lo, hi = v["range"]
    vals = [lo, hi, anc["lo"], anc["hi"]] + ([ask] if ask else [])
    tiers = v.get("tiers") or {}
    vals += [t for t in tiers.values() if t]
    a, b = scale(min(vals), max(vals))

    def bar(l, h, cls, label):
        return (f'<div class="bar {cls}" style="left:{x(l,a,b):.2f}%;'
                f'width:{max(x(h,a,b)-x(l,a,b),0.8):.2f}%" '
                f'title="{label}: {usd(l)} – {usd(h)}"></div>')

    marks = ""
    for key, cls, txt in (("good", "t-good", "good deal"),
                          ("fair", "t-fair", "worth it"),
                          ("stretch", "t-stretch", "stretch")):
        t = tiers.get(key)
        if t:
            marks += (f'<div class="tier {cls}" style="left:{x(t,a,b):.2f}%" '
                      f'title="{txt}: {usd(t)}"><i></i><span>{txt}<b>{usdk(t)}</b></span></div>')
    askmark = ""
    if ask:
        askmark = (f'<div class="askline" style="left:{x(ask,a,b):.2f}%" '
                   f'title="asking {usd(ask)}"><i></i><span>asking <b>{usdk(ask)}</b></span></div>')
    return f"""
    <div class="plot">
      <div class="lane"><div class="lane-lab">comps say</div>
        <div class="track">{bar(anc['lo'], anc['hi'], 'b-comp', 'comp band p25–p75')}</div>
        <div class="lane-val">{usdk(anc['lo'])} – {usdk(anc['hi'])}<i>n={anc['n']}</i></div></div>
      <div class="lane"><div class="lane-lab">we say</div>
        <div class="track">{bar(lo, hi, 'b-ours', 'our range')}</div>
        <div class="lane-val">{usdk(lo)} – {usdk(hi)}</div></div>
      <div class="marks">{marks}{askmark}</div>
      <div class="axis">{money_axis(a, b)}</div>
    </div>"""


def comps_table(ctx):
    rows = ctx.get("comparables") or []
    if not rows:
        return ('<p class="none">No comparable sales offered — this listing publishes no '
                'sqft, beds or baths, so any pick would be arbitrary.</p>')
    lo = min(min(r["ask"], r["sold"]) for r in rows)
    hi = max(max(r["ask"], r["sold"]) for r in rows)
    a, b = scale(lo, hi)
    out = []
    for r in rows:
        over = r["sold"] >= r["ask"]
        xa, xs = x(r["ask"], a, b), x(r["sold"], a, b)
        l, w = min(xa, xs), abs(xs - xa)
        # sign + word carry the meaning; colour only reinforces it (dE 7.1, see header)
        sign = "+" if over else "−"
        word = "over ask" if over else "under ask"
        out.append(f"""
        <div class="cmp">
          <div class="cmp-h"><b>{r['address']}</b>
            <span>{r['sold_date']} · {r['sqft']:,} sqft · {r['beds']:g}bd {r['baths']:g}ba
            {'· ' + r['match_basis'] if r.get('match_basis') else ''}</span></div>
          <div class="track">
            <div class="dumb {'d-over' if over else 'd-under'}"
                 style="left:{l:.2f}%;width:{max(w,0.6):.2f}%"></div>
            <div class="dot d-ask"  style="left:{xa:.2f}%" title="asked {usd(r['ask'])}"></div>
            <div class="dot {'d-over' if over else 'd-under'}" style="left:{xs:.2f}%"
                 title="sold {usd(r['sold'])}"></div>
          </div>
          <div class="cmp-v">asked {usdk(r['ask'])} → sold {usdk(r['sold'])}
            <b class="{'o' if over else 'u'}">{sign}{abs(r['gap_pct']):.1f}% {word}</b></div>
        </div>""")
    return (f'<div class="axis mini">{money_axis(a, b, 4)}</div>' + "".join(out))


def works_block(v):
    w = v.get("works") or {}
    if not w: return ""
    out = []
    for key, title in (("move_in", "To move in"), ("year_one", "Year one")):
        blk = w.get(key) or {}
        lines = blk.get("lines") or []
        if not lines and not blk.get("total"): continue
        t = blk.get("total")
        out.append(f"""<div class="works">
          <h4>{title}{f'<b>{usdk(t[0])} – {usdk(t[1])}</b>' if t else ''}</h4>
          <ul>{''.join(f"<li>{l['what']}<i>{l.get('evidence','')}</i>"
                       f"<b>{usdk(l['lo'])}–{usdk(l['hi'])}</b></li>" for l in lines)}</ul>
        </div>""")
    gate = w.get("oil_tank_gate")
    if gate:
        out.append(f'<p class="gate"><b>Oil tank — a gate, not a line item.</b> {gate}</p>')
    return "".join(out)


CSS = """
:root{--paper:#f7f4ee;--paper-2:#f1ece3;--rule:#ddd5c7;--rule-2:#c8bda9;
  --ink:#1f1c18;--ink-2:#544d43;--ink-3:#8a8072;
  --over:#8c2f2a;--under:#2c6459;--flag:#a8631c;
  --serif:"Iowan Old Style","Hoefler Text",Baskerville,Georgia,serif;
  --sans:"Avenir Next",Seravek,Optima,"Gill Sans",Helvetica,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;
  line-height:1.55;padding:clamp(1.5rem,4vw,3rem) clamp(1rem,4vw,3rem) 6rem}
.sheet{max-width:64rem;margin:0 auto}
a.home{font-family:var(--serif);font-size:.85rem;color:var(--ink-3);text-decoration:none}
h1{font-family:var(--serif);font-weight:400;font-size:clamp(1.7rem,3.4vw,2.4rem);
  letter-spacing:-.015em;line-height:1.1;margin:.2rem 0 .1rem}
h1 em{font-style:italic;color:var(--ink-2)}
.sub{color:var(--ink-3);font-size:.85rem;border-bottom:2px solid var(--ink);
  padding-bottom:.75rem;margin-bottom:1.4rem}
h2{font-family:var(--serif);font-weight:400;font-size:1.25rem;margin:2.2rem 0 .2rem}
h2+.hint{color:var(--ink-3);font-size:.78rem;margin-bottom:.9rem}
h4{font-size:.7rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.4rem}
h4 b{font-family:var(--serif);font-size:1rem;color:var(--ink);letter-spacing:0;text-transform:none}
.none{color:var(--ink-3);font-style:italic;border-left:2px solid var(--rule-2);
  padding:.5rem .8rem;margin:.5rem 0}
/* hero */
.hero{border:1px solid var(--rule-2);padding:1.1rem 1.2rem;margin-bottom:.6rem}
.hero .big{font-family:var(--serif);font-size:clamp(1.9rem,5vw,2.9rem);line-height:1;
  font-variant-numeric:tabular-nums}
.hero .cap{font-size:.7rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600;margin-bottom:.5rem}
.hero .note{color:var(--ink-2);margin-top:.5rem;font-size:.9rem}
/* one shared money axis */
.plot{border:1px solid var(--rule-2);padding:1rem 1.1rem .3rem;margin-bottom:.6rem}
.lane{display:grid;grid-template-columns:5.5rem 1fr 9rem;gap:.8rem;align-items:center;
  padding:.45rem 0}
.lane-lab{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600;text-align:right}
.lane-val{font-size:.78rem;color:var(--ink-2);font-variant-numeric:tabular-nums}
.lane-val i{font-style:normal;color:var(--ink-3);margin-left:.4rem;font-size:.72rem}
.track{position:relative;height:18px}
.track:before{content:"";position:absolute;left:0;right:0;top:8px;height:1px;background:var(--rule)}
.bar{position:absolute;top:5px;height:8px;border-radius:4px}   /* 4px rounded data ends */
.b-comp{background:var(--rule-2)}
.b-ours{background:var(--ink);box-shadow:0 0 0 2px var(--paper)} /* 2px surface ring */
.marks{position:relative;height:44px;margin:.2rem 0 0 6.3rem;margin-right:9.8rem}
.tier,.askline{position:absolute;top:0;transform:translateX(-50%);text-align:center;width:7rem}
.tier i,.askline i{display:block;width:2px;height:12px;margin:0 auto 3px}
.tier span,.askline span{font-size:.62rem;color:var(--ink-3);line-height:1.25;display:block}
.tier b,.askline b{display:block;font-family:var(--serif);font-size:.82rem;color:var(--ink)}
.t-good i{background:var(--under)} .t-fair i{background:var(--ink)} .t-stretch i{background:var(--flag)}
.askline i{background:var(--over);height:16px}
.askline span{color:var(--over)}
.axis{position:relative;height:22px;margin:.4rem 0 0 6.3rem;margin-right:9.8rem;
  border-top:1px solid var(--rule)}
.axis.mini{margin:0 0 .3rem;height:20px}
.tick{position:absolute;top:3px;transform:translateX(-50%)}
.tick span{font-size:.62rem;color:var(--ink-3);font-variant-numeric:tabular-nums}
/* comparables */
.cmp{border-bottom:1px solid var(--rule);padding:.7rem 0}
.cmp-h{display:flex;justify-content:space-between;align-items:baseline;gap:1rem;flex-wrap:wrap}
.cmp-h b{font-family:var(--serif);font-weight:400;font-size:1.02rem}
.cmp-h span{font-size:.72rem;color:var(--ink-3)}
.cmp .track{margin:.35rem 0}
.dumb{position:absolute;top:7px;height:3px;border-radius:2px;opacity:.5}
.dot{position:absolute;top:4px;width:9px;height:9px;border-radius:50%;   /* >=8px markers */
  transform:translateX(-50%);box-shadow:0 0 0 2px var(--paper)}
.d-ask{background:var(--ink-3)}
.d-over{background:var(--over)} .d-under{background:var(--under)}
.cmp-v{font-size:.78rem;color:var(--ink-2);font-variant-numeric:tabular-nums}
.cmp-v b{margin-left:.4rem}
.o{color:var(--over)} .u{color:var(--under)}
.legend{display:flex;gap:1.1rem;flex-wrap:wrap;font-size:.7rem;color:var(--ink-3);
  margin:.5rem 0 .2rem}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:.3rem;
  vertical-align:-1px}
/* narrative */
.card{border:1px solid var(--rule-2);padding:.9rem 1.1rem;margin:.5rem 0}
.card.bad{border-color:var(--over)} .card.good{border-color:var(--under)}
.works ul{list-style:none;margin:.2rem 0 1rem}
.works li{display:grid;grid-template-columns:1fr auto;gap:.3rem 1rem;padding:.32rem 0;
  border-bottom:1px dotted var(--rule);font-size:.86rem}
.works li i{grid-column:1;font-style:italic;color:var(--ink-3);font-size:.72rem}
.works li b{grid-row:1/3;align-self:center;font-family:var(--serif);font-weight:400;
  font-variant-numeric:tabular-nums}
.gate{border-left:3px solid var(--flag);padding:.5rem .8rem;background:var(--paper-2);
  font-size:.86rem;margin:.4rem 0 1rem}
.flags{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0}
.flags span{font-size:.66rem;border:1px solid var(--rule-2);padding:.12rem .45rem;
  color:var(--ink-3)}
table{width:100%;border-collapse:collapse;font-size:.8rem;margin:.4rem 0}
th,td{text-align:left;padding:.3rem .5rem;border-bottom:1px solid var(--rule)}
th{font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
td.n{text-align:right;font-variant-numeric:tabular-nums}
details{margin:.6rem 0}summary{cursor:pointer;font-size:.78rem;color:var(--ink-3)}
.foot{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--rule);
  font-size:.74rem;color:var(--ink-3);line-height:1.6}
@media(max-width:640px){
  .lane{grid-template-columns:1fr;gap:.2rem}.lane-lab{text-align:left}
  .marks,.axis{margin-left:0;margin-right:0}
}
"""


def render(ctx, v, sealed, demo=False):
    s = ctx.get("subject", {})
    anc = ctx.get("anchor") or {}
    ask = (sealed or {}).get("last_list_price")
    facts = " · ".join(str(x) for x in [
        f"{s.get('beds')}bd" if s.get("beds") else None,
        f"{s.get('baths')}ba" if s.get("baths") else None,
        f"{int(float(s['sqft'])):,} sqft" if s.get("sqft") else "sqft not published",
        f"built {s.get('year_built')}" if s.get("year_built") else None,
        s.get("property_type")] if x)

    flags = [k for k in ("degraded", "lotDropped", "eraDropped", "famDropped",
                         "thinFam", "borrowed", "noSize") if anc.get(k)]
    flagbar = ("".join(f"<span>{k}</span>" for k in flags)
               if flags else "<span>clean comp set</span>")

    rng = v.get("range")
    hero = ('<div class="big">' + (f"{usdk(rng[0])} – {usdk(rng[1])}" if rng else "no range")
            + "</div>")
    verdict_note = v.get("headline") or (
        "Demo render — no verdict written yet. The numbers below are the deterministic "
        "half: the comp anchor, real recent sales, location and holding cost." if demo else "")

    vsask = ""
    if ask and rng:
        mid = (rng[0] + rng[1]) / 2
        gap = (ask - mid) / mid * 100
        over = gap > 0
        vsask = f"""<div class="card {'bad' if over else 'good'}">
          <b>Asking {usd(ask)}</b> — that is
          <b class="{'o' if over else 'u'}">{'+' if over else '−'}{abs(gap):.1f}%
          {'above' if over else 'below'}</b> the middle of our range.
          {v.get('vs_ask','')}</div>"""
    elif ask and demo:
        vsask = f'<p class="none">Asking {usd(ask)} — sealed until a verdict exists.</p>'

    tiers = v.get("tiers") or {}
    tier_tbl = ""
    if tiers:
        tier_tbl = ("<table><tr><th>Offer</th><th>What it means</th><th class='n'>Price</th></tr>"
                    + "".join(f"<tr><td>{lab}</td><td>{d}</td><td class='n'>{usd(tiers[k])}</td></tr>"
                              for k, lab, d in (
                                  ("good", "A really good deal", "buy below this and you're winning"),
                                  ("fair", "What it's worth", "the centre of our range"),
                                  ("stretch", "Only if you love it", "the top of what's defensible"))
                              if tiers.get(k)) + "</table>")

    loc = ctx.get("location") or {}
    stores = loc.get("stores_miles") or {}
    hold = ctx.get("holding_cost")

    rows = ctx.get("comparables") or []
    tablev = ("<table><tr><th>Address</th><th>Sold</th><th class='n'>Asked</th>"
              "<th class='n'>Sold for</th><th class='n'>Gap</th></tr>"
              + "".join(f"<tr><td>{r['address']}</td><td>{r['sold_date']}</td>"
                        f"<td class='n'>{usd(r['ask'])}</td><td class='n'>{usd(r['sold'])}</td>"
                        f"<td class='n'>{r['gap_pct']:+.1f}%</td></tr>" for r in rows)
              + "</table>") if rows else ""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{s.get('address','Appraisal')} — appraisal</title><style>{CSS}</style></head><body>
<div class="sheet">
  <a class="home" href="../../offer/index.html">← The house hunt</a>
  <h1>{s.get('address','—')} <em>— {s.get('town','')}</em></h1>
  <div class="sub">{facts}</div>

  <div class="hero">
    <div class="cap">What we think it's worth, as-is</div>
    {hero}
    <div class="note">{verdict_note}</div>
  </div>
  {headline(ctx, v, ask)}
  <div class="legend">
    <span><i style="background:var(--rule-2)"></i>comp band (p25–p75)</span>
    <span><i style="background:var(--ink)"></i>our range</span>
    <span><i style="background:var(--over)"></i>asking price</span>
  </div>
  <div class="flags">{flagbar}</div>
  {vsask}

  {'<h2>What to offer</h2><p class="hint">Derived from the range only — the repair budget below is cash you spend, never subtracted from these.</p>' + tier_tbl if tier_tbl else ''}

  <h2>Real sales nearby</h2>
  <p class="hint">Recent, comparable in shape, each showing what it <em>asked</em> and what it
    actually <em>got</em>. Direction is written out as well as coloured.</p>
  {comps_table(ctx)}
  <div class="legend">
    <span><i class="d-ask" style="background:var(--ink-3)"></i>asked</span>
    <span><i style="background:var(--under)"></i>sold − under ask</span>
    <span><i style="background:var(--over)"></i>sold + over ask</span>
  </div>
  {f'<details><summary>Same figures as a table</summary>{tablev}</details>' if tablev else ''}

  {'<h2>The ruling</h2><div class="card">' + v['ruling'] + '</div>' if v.get('ruling') else ''}
  {'<h2>What it needs</h2>' + works_block(v) if v.get('works') else ''}
  {'<h2>What would make this wrong</h2><div class="card"><ul>' + ''.join(f'<li>{o}</li>' for o in v['adversary']) + '</ul></div>' if v.get('adversary') else ''}

  <h2>Around it</h2>
  <table>
    <tr><th>Flood zone (this house)</th><td>{loc.get('flood_zone') or 'not in a mapped zone'}</td></tr>
    {''.join(f"<tr><th>Nearest {k.replace('_',' ')}</th><td>{x['miles']} mi — {x['which']}</td></tr>" for k,x in stores.items())}
    {f"<tr><th>Estimated tax</th><td>~{usd(hold['annual_estimate'])}/yr (~{usd(hold['monthly_estimate'])}/mo) — <em>{hold['warning']}</em></td></tr>" if hold else ''}
  </table>

  <p class="foot">
    <b>How to read this.</b> The range is what the house is worth <em>as it stands</em> —
    condition is already priced in. The repair budget is cash you would spend on top; it is
    never subtracted from the range or the offer tiers, or you would be charged twice for
    the same kitchen.<br><br>
    <b>Where the numbers come from.</b> The comp band is the engine used across this site,
    graded in public on the backtest page — median error 9.86%, and the true price lands
    inside its band about 48% of the time against a 50% target. Everything a model added on
    top is judgement, and every such claim names the photo or phrase it came from.<br><br>
    <b>Colour is never the only signal.</b> The over/under pair scores ΔE 7.1 under
    deuteranopia — above the floor, below target — so every direction is written in words
    and carries a sign as well as a colour.
  </p>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    ctx = json.loads((RUN / "context.json").read_text())
    vp, sp = RUN / "verdict.json", RUN / "subject_sealed.json"
    v = json.loads(vp.read_text()) if vp.exists() and not a.demo else {}
    sealed = json.loads(sp.read_text()) if sp.exists() else {}
    out = RUN / "report.html"
    out.write_text(render(ctx, v, sealed, demo=a.demo or not vp.exists()))
    print(f"wrote {out}")
    if not a.no_open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
