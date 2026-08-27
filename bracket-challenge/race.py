#!/usr/bin/env python3
"""Build a self-contained leaderboard-race web page from the daily snapshots.

Reads every history/<YYYY-MM-DD>.json (the routine's daily memory, keyed by the
stable `username`) plus matches.json (the per-day game log built by matches.py),
and emits race.html with both datasets embedded — no server, no build, no
external data. Open the file straight from disk.

    python3 race.py            # writes race.html next to this script
    python3 race.py --open     # write, then open it in your browser
    python3 race.py out.html   # custom output path

stdlib only, deterministic: same inputs -> same page.
"""
import glob
import json
import os
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
START_DATE = "2026-06-11"  # opening day — everyone at 0 before any games
END_DATE = "2026-07-20"    # day after the final (ESP 1-0 ARG, Jul 19) — the
                           # tournament is over, so every later snapshot is a
                           # duplicate of this one and adds flat frames.

# FIFA 3-letter code -> flag emoji (SCO/ENG use the subdivision flags). Kept here
# (not in matches.json) so the game-log reference stays clean and hand-editable.
FLAG = {
    "MEX": "🇲🇽", "KOR": "🇰🇷", "CZE": "🇨🇿", "RSA": "🇿🇦", "CAN": "🇨🇦",
    "SUI": "🇨🇭", "QAT": "🇶🇦", "BIH": "🇧🇦", "BRA": "🇧🇷", "MAR": "🇲🇦",
    "SCO": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "HAI": "🇭🇹", "TUR": "🇹🇷", "USA": "🇺🇸", "AUS": "🇦🇺",
    "PAR": "🇵🇾", "GER": "🇩🇪", "ECU": "🇪🇨", "CIV": "🇨🇮", "CUW": "🇨🇼",
    "NED": "🇳🇱", "JPN": "🇯🇵", "TUN": "🇹🇳", "SWE": "🇸🇪", "BEL": "🇧🇪",
    "IRN": "🇮🇷", "EGY": "🇪🇬", "NZL": "🇳🇿", "ESP": "🇪🇸", "URU": "🇺🇾",
    "KSA": "🇸🇦", "CPV": "🇨🇻", "FRA": "🇫🇷", "NOR": "🇳🇴", "SEN": "🇸🇳",
    "IRQ": "🇮🇶", "ARG": "🇦🇷", "AUT": "🇦🇹", "ALG": "🇩🇿", "JOR": "🇯🇴",
    "POR": "🇵🇹", "COL": "🇨🇴", "COD": "🇨🇩", "UZB": "🇺🇿", "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "CRO": "🇭🇷", "GHA": "🇬🇭", "PAN": "🇵🇦",
}


def load_history():
    """[{date, entries:[{username,name,total,rank}]}] sorted by date."""
    days = []
    for path in sorted(glob.glob(os.path.join(HERE, "history", "*.json"))):
        date = os.path.splitext(os.path.basename(path))[0]
        if date > END_DATE:
            continue
        with open(path) as f:
            rows = json.load(f)
        days.append({
            "date": date,
            "entries": [
                {"username": r["username"], "name": r["name"],
                 "total": r["total"], "rank": r["rank"]}
                for r in rows
            ],
        })
    return days


def load_matches():
    """Read the game-log reference and decorate each game with flag emoji + a
    `corrected` default (the stored file keeps only codes, for easy editing)."""
    path = os.path.join(HERE, "matches.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        by_date = json.load(f).get("by_date", {})
    for games in by_date.values():
        for g in games:
            g["home_flag"] = FLAG.get(g["home"], "")
            g["away_flag"] = FLAG.get(g["away"], "")
            g["corrected"] = bool(g.get("corrected"))
    return by_date


def display_names(days):
    """username -> most-recent display name (names drift; latest wins)."""
    names = {}
    for day in days:
        for e in day["entries"]:
            names[e["username"]] = e["name"]
    return names


def build(days, matches):
    names = display_names(days)
    order, seen = [], set()
    for day in days:
        for e in day["entries"]:
            if e["username"] not in seen:
                seen.add(e["username"])
                order.append(e["username"])
    players = [{"username": u, "name": names[u]}
               for u in sorted(order, key=lambda u: names[u].lower())]
    # The race starts the morning of June 11 — group stage not yet kicked off, so
    # everyone sits at 0. The opening-day fixtures are shown as that day's games.
    start = {"date": START_DATE,
             "entries": [{"username": p["username"], "name": p["name"],
                          "total": 0, "rank": 1} for p in players]}
    days = [start] + days
    payload = {"days": days, "players": players, "matches": matches}
    return HTML.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False))


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bracket Race — NYNJWC · World Cup 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800;900&family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:oklch(0.165 0.014 156);
    --bg-2:oklch(0.205 0.017 158);
    --panel:oklch(0.225 0.018 160);
    --line:oklch(0.32 0.02 158);
    --line-soft:oklch(0.27 0.018 158 / .6);
    --ink:oklch(0.97 0.008 120);
    --muted:oklch(0.74 0.022 152);
    --faint:oklch(0.58 0.02 152);
    --gold:oklch(0.84 0.135 86);
    --gold-deep:oklch(0.70 0.14 72);
    --green:oklch(0.78 0.15 150);
    --red:oklch(0.68 0.16 22);
    --ease:cubic-bezier(.16,1,.3,1);
    --row-h:42px; --gap:9px; --plot-left:172px; --plot-right:62px;
  }
  *{box-sizing:border-box}
  html,body{margin:0; min-height:100%}
  body{
    background:
      radial-gradient(1100px 700px at 88% -8%, oklch(0.27 0.03 158 / .6) 0, transparent 55%),
      radial-gradient(900px 600px at -5% 110%, oklch(0.24 0.04 86 / .25) 0, transparent 50%),
      var(--bg);
    color:var(--ink);
    font-family:'Archivo','Helvetica Neue',system-ui,sans-serif;
    font-size:15px; line-height:1.45; -webkit-font-smoothing:antialiased;
    padding:clamp(18px,4vw,40px) clamp(14px,4vw,32px) 60px;
  }
  .wrap{width:min(1140px,100%); margin:0 auto}

  /* ---- header ---- */
  header{
    display:flex; align-items:flex-end; justify-content:space-between;
    gap:20px; flex-wrap:wrap; padding-bottom:18px;
    border-bottom:1px solid var(--line-soft);
  }
  .kicker{
    font-size:11px; letter-spacing:.28em; text-transform:uppercase;
    color:var(--gold); font-weight:700; margin:0 0 6px;
    display:flex; align-items:center; gap:9px;
  }
  .kicker::before{content:""; width:22px; height:2px; background:var(--gold); display:inline-block}
  h1{
    font-family:'Bricolage Grotesque','Archivo',sans-serif;
    font-weight:800; font-size:clamp(34px,6vw,58px); line-height:.92;
    margin:0; letter-spacing:-.02em;
  }
  h1 em{font-style:normal; color:var(--gold)}
  .tagline{color:var(--muted); font-size:14px; margin:10px 0 0; max-width:42ch}

  .scoreboard{
    text-align:right; font-variant-numeric:tabular-nums; flex:0 0 auto;
    padding:12px 16px; border:1px solid var(--line); border-radius:13px;
    background:linear-gradient(180deg, var(--bg-2), oklch(0.19 0.016 158));
    box-shadow:inset 0 1px 0 oklch(1 0 0 / .04);
  }
  .scoreboard .dow{font-size:11px; letter-spacing:.22em; text-transform:uppercase; color:var(--faint)}
  .scoreboard .big{
    font-family:'Bricolage Grotesque',sans-serif; font-weight:700;
    font-size:40px; line-height:1; letter-spacing:-.01em; margin:2px 0 4px;
  }
  .scoreboard .prog{font-size:12px; color:var(--muted); letter-spacing:.04em}
  .scoreboard .prog b{color:var(--ink); font-weight:700}

  /* ---- layout ---- */
  .stage{
    display:grid; grid-template-columns:1fr 296px; gap:22px; margin-top:24px;
    align-items:start;
  }
  @media(max-width:820px){ .stage{grid-template-columns:1fr} }

  /* ---- chart ---- */
  .chart{position:relative; padding-top:6px}
  .axis{
    position:absolute; left:var(--plot-left); right:var(--plot-right);
    top:0; bottom:38px; pointer-events:none;
  }
  .axis i{
    position:absolute; top:0; bottom:0; width:1px;
    background:var(--line-soft);
  }
  .axis i span{
    position:absolute; top:-2px; left:6px; font-size:10px; color:var(--faint);
    font-variant-numeric:tabular-nums; letter-spacing:.04em;
  }
  .rows{position:relative}
  .row{
    position:absolute; left:0; right:0; height:var(--row-h);
    display:flex; align-items:center; gap:10px;
    transition:transform 1.15s var(--ease), opacity .6s ease;
    will-change:transform;
  }
  .pos{
    flex:0 0 22px; width:22px; text-align:right;
    font-variant-numeric:tabular-nums; font-weight:700; font-size:14px;
    color:var(--faint); transition:color .4s;
  }
  .medal{font-size:15px; line-height:1}
  .kit{
    flex:0 0 30px; width:30px; height:30px; border-radius:8px;
    display:grid; place-items:center; font-weight:800; font-size:12px;
    letter-spacing:-.02em; color:oklch(0.16 0.02 156);
    box-shadow:inset 0 0 0 1px oklch(1 0 0 / .14), 0 2px 5px oklch(0 0 0 / .3);
  }
  .name{
    flex:0 0 92px; width:92px; font-weight:600; font-size:14px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  .track{position:relative; flex:1 1 auto; height:100%; margin-right:var(--plot-right)}
  .bar{
    position:absolute; top:7px; bottom:7px; left:0; width:0;
    border-radius:0 6px 6px 0;
    transition:width 1.15s var(--ease), filter .4s, box-shadow .4s;
    box-shadow:inset 0 1px 0 oklch(1 0 0 / .18);
  }
  .bar::after{ /* glossy top sheen */
    content:""; position:absolute; inset:0 0 50% 0; border-radius:0 6px 0 0;
    background:linear-gradient(180deg, oklch(1 0 0 / .12), transparent);
  }
  .val{
    position:absolute; left:calc(100% + 9px); top:50%; transform:translateY(-50%);
    font-variant-numeric:tabular-nums; font-weight:800; font-size:14px;
    white-space:nowrap; letter-spacing:-.01em;
  }
  .delta{
    position:absolute; left:calc(100% + 9px); top:50%;
    transform:translate(0,-50%); opacity:0;
    font-size:11px; font-weight:700; white-space:nowrap;
    transition:opacity .4s; font-variant-numeric:tabular-nums;
  }
  .row.lead .pos{color:var(--gold)}
  .row.lead .name{color:var(--gold)}
  @keyframes overtake{
    0%{box-shadow:inset 0 1px 0 oklch(1 0 0 / .18), 0 0 0 0 oklch(0.84 0.135 86 / .55)}
    100%{box-shadow:inset 0 1px 0 oklch(1 0 0 / .18), 0 0 0 7px oklch(0.84 0.135 86 / 0)}
  }
  .row.jump .bar{animation:overtake .9s ease-out}

  /* ---- games rail ---- */
  .rail{
    border:1px solid var(--line); border-radius:14px; overflow:hidden;
    background:linear-gradient(180deg, var(--bg-2), oklch(0.185 0.015 158));
    position:sticky; top:18px;
  }
  .rail-head{
    display:flex; align-items:center; justify-content:space-between;
    padding:13px 15px; border-bottom:1px solid var(--line-soft);
  }
  .rail-head h2{
    margin:0; font-size:11px; letter-spacing:.2em; text-transform:uppercase;
    color:var(--muted); font-weight:700;
  }
  .rail-head .pulse{
    width:8px; height:8px; border-radius:50%; background:var(--green);
    box-shadow:0 0 0 0 oklch(0.78 0.15 150 / .6); animation:beat 2s infinite;
  }
  @keyframes beat{50%{box-shadow:0 0 0 6px oklch(0.78 0.15 150 / 0)}}
  .games{padding:7px; display:flex; flex-direction:column; gap:6px; min-height:140px}
  .game{
    display:grid; grid-template-columns:30px 1fr auto; align-items:center; gap:9px;
    padding:9px 10px; border-radius:9px; background:oklch(0.26 0.018 158 / .5);
    border:1px solid transparent;
    animation:slidein .5s var(--ease) both;
  }
  @keyframes slidein{from{opacity:0; transform:translateX(8px)}}
  .game .grp{
    font-size:10px; font-weight:800; color:var(--faint);
    border:1px solid var(--line); border-radius:5px; padding:2px 0; text-align:center;
  }
  .game .grp.ko{
    font-size:9px; color:var(--gold); border-color:var(--gold-deep);
    background:oklch(0.70 0.14 72 / .12);
  }
  .game .fix{font-size:13px; font-weight:500; display:flex; gap:6px; align-items:baseline}
  .game .fix .t{font-weight:700; letter-spacing:.01em}
  .game .fix .loser{color:var(--faint); font-weight:500}
  .game .sc{
    font-variant-numeric:tabular-nums; font-weight:800; font-size:14px;
    letter-spacing:.02em; white-space:nowrap;
  }
  .game.corr{border-color:oklch(0.70 0.14 72 / .5)}
  .game .tag{
    grid-column:2/4; font-size:10px; color:var(--gold-deep); font-weight:700;
    letter-spacing:.04em; margin-top:-3px;
  }
  .empty{
    padding:26px 16px; text-align:center; color:var(--faint); font-size:13px;
    line-height:1.5;
  }
  .empty b{color:var(--muted); display:block; font-size:14px; margin-bottom:3px}

  /* ---- transport ---- */
  .transport{
    display:flex; align-items:center; gap:16px; margin-top:26px;
    padding:14px 18px; border:1px solid var(--line); border-radius:14px;
    background:var(--bg-2);
  }
  button.play{
    appearance:none; border:0; cursor:pointer; flex:0 0 auto;
    width:46px; height:46px; border-radius:50%;
    background:var(--gold); color:oklch(0.22 0.04 80);
    display:grid; place-items:center; font-size:17px;
    box-shadow:0 4px 14px oklch(0.7 0.14 72 / .35);
    transition:transform .12s var(--ease), filter .2s;
  }
  button.play:hover{filter:brightness(1.06)}
  button.play:active{transform:scale(.93)}
  .scrub-wrap{flex:1 1 auto; display:flex; flex-direction:column; gap:5px}
  input[type=range]{
    -webkit-appearance:none; appearance:none; width:100%; height:5px;
    border-radius:3px; cursor:pointer;
    background:linear-gradient(90deg,var(--gold) 0 var(--fill,0%),var(--line) var(--fill,0%));
  }
  input[type=range]::-webkit-slider-thumb{
    -webkit-appearance:none; width:16px; height:16px; border-radius:50%;
    background:var(--ink); border:3px solid var(--gold-deep); cursor:grab;
    box-shadow:0 2px 6px oklch(0 0 0 / .4);
  }
  input[type=range]::-moz-range-thumb{
    width:16px; height:16px; border-radius:50%; border:3px solid var(--gold-deep);
    background:var(--ink); cursor:grab;
  }
  .ticks{display:flex; justify-content:space-between; font-size:10px; color:var(--faint); letter-spacing:.05em}
  .speed{display:flex; gap:5px; flex:0 0 auto}
  .speed button{
    appearance:none; cursor:pointer; font-family:inherit;
    border:1px solid var(--line); background:transparent; color:var(--faint);
    border-radius:8px; padding:6px 9px; font-size:12px; font-weight:700;
    transition:.2s;
  }
  .speed button.on{color:oklch(0.18 0.02 156); background:var(--gold); border-color:var(--gold)}
  .foot{margin-top:16px; color:var(--faint); font-size:11.5px; letter-spacing:.04em; text-align:center}
  @media(prefers-reduced-motion:reduce){ *{animation-duration:.01ms!important; transition-duration:.01ms!important} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <p class="kicker">NYNJWC · FIFA World Cup 2026 · Group Stage</p>
      <h1>Bracket <em>Race</em></h1>
      <p class="tagline">Where the league would finish if the group stage ended today — the table swings every day instead of revealing once at the end.</p>
    </div>
    <div class="scoreboard">
      <div class="dow" id="dow">—</div>
      <div class="big" id="date">—</div>
      <div class="prog">Day <b id="dayno">1</b> of <span id="daytot">15</span></div>
    </div>
  </header>

  <div class="stage">
    <div class="chart">
      <div class="axis" id="axis"></div>
      <div class="rows" id="rows"></div>
    </div>

    <aside class="rail">
      <div class="rail-head">
        <h2>Today's matches</h2>
        <span class="pulse"></span>
      </div>
      <div class="games" id="games"></div>
    </aside>
  </div>

  <div class="transport">
    <button class="play" id="play" aria-label="Play / pause">&#9654;</button>
    <div class="scrub-wrap">
      <input type="range" id="scrub" min="0" value="0" step="1">
      <div class="ticks"><span id="tick0"></span><span id="tick1"></span></div>
    </div>
    <div class="speed" id="speed"></div>
  </div>
  <div class="foot" id="foot"></div>
</div>

<script>
const DATA = /*__DATA__*/;
const { days, players, matches } = DATA;
const N = players.length;

// Refined, cohesive palette: evenly spaced hues at controlled chroma/lightness
// (oklch) so 14 colours read as a designed set, not a saturated rainbow.
const colour = {};
players.forEach((p,i)=>{
  const h = (i*360/N + 24) % 360;
  colour[p.username] = `oklch(0.70 0.125 ${h.toFixed(0)})`;
});
const GOLD = 'oklch(0.84 0.135 86)', GOLD2 = 'oklch(0.70 0.14 72)';
const initials = s => s.trim().split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
const MEDAL = ['🥇','🥈','🥉'];

const ROW_H=42, GAP=9;
const rowsEl=document.getElementById('rows');
rowsEl.style.height=(N*(ROW_H+GAP))+'px';

const rowEls={};
players.forEach(p=>{
  const r=document.createElement('div'); r.className='row';
  r.innerHTML=
    `<div class="pos"></div>`+
    `<div class="kit"></div>`+
    `<div class="name">${p.name}</div>`+
    `<div class="track"><div class="bar"><span class="val"></span><span class="delta"></span></div></div>`;
  const kit=r.querySelector('.kit');
  kit.textContent=initials(p.name);
  kit.style.background=`linear-gradient(155deg, ${colour[p.username]}, color-mix(in oklch, ${colour[p.username]} 72%, black))`;
  r.querySelector('.bar').style.background=`linear-gradient(180deg, ${colour[p.username]}, color-mix(in oklch, ${colour[p.username]} 80%, black))`;
  rowsEl.appendChild(r); rowEls[p.username]=r;
});

// yard-line gridlines at running-max quartiles
const axisEl=document.getElementById('axis');
function drawAxis(max){
  axisEl.innerHTML='';
  for(let q=1;q<=4;q++){
    const i=document.createElement('i'); i.style.left=(q*25)+'%';
    if(q<4){ const s=document.createElement('span'); s.textContent=Math.round(max*q/4); i.appendChild(s); }
    axisEl.appendChild(i);
  }
}

function runningMax(idx){
  let m=50; for(let i=0;i<=idx;i++) for(const e of days[i].entries) if(e.total>m) m=e.total;
  return m;
}

const DOW=['SUNDAY','MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY'];
let prevPos={};

function render(idx, animateJumps){
  const day=days[idx];
  const max=runningMax(idx);
  drawAxis(max);
  const byUser=Object.fromEntries(day.entries.map(e=>[e.username,e]));
  const prevDay = idx>0 ? Object.fromEntries(days[idx-1].entries.map(e=>[e.username,e])) : null;
  const sorted=[...day.entries].sort((a,b)=>b.total-a.total || a.rank-b.rank);
  const pos={}; sorted.forEach((e,i)=>pos[e.username]=i);

  players.forEach(p=>{
    const row=rowEls[p.username];
    const e=byUser[p.username]||{total:0,rank:N};
    const place=pos[p.username]??(N-1);
    const ranked = e.total>0;  // before kickoff everyone's tied at 0 — no podium
    row.style.transform=`translateY(${place*(ROW_H+GAP)}px)`;
    row.classList.toggle('lead', place===0 && ranked);

    const bar=row.querySelector('.bar');
    bar.style.width=(100*e.total/max)+'%';
    if(place===0 && ranked){
      bar.style.background=`linear-gradient(180deg, ${GOLD}, ${GOLD2})`;
      bar.style.filter='saturate(1.05)';
    }else{
      bar.style.background=`linear-gradient(180deg, ${colour[p.username]}, color-mix(in oklch, ${colour[p.username]} 80%, black))`;
      bar.style.filter='none';
    }
    row.querySelector('.val').textContent=e.total.toLocaleString();

    const posEl=row.querySelector('.pos');
    posEl.innerHTML = (place<3 && ranked) ? `<span class="medal">${MEDAL[place]}</span>` : (place+1);

    // rank delta vs previous day
    const dEl=row.querySelector('.delta');
    if(prevDay && prevDay[p.username]){
      const moved = prevDay[p.username].rank - e.rank; // +ve = climbed
      if(moved>0){ dEl.textContent=`▲ ${moved}`; dEl.style.color='var(--green)'; dEl.style.opacity='0'; }
      else if(moved<0){ dEl.textContent=`▼ ${-moved}`; dEl.style.color='var(--red)'; dEl.style.opacity='0'; }
      else { dEl.style.opacity='0'; dEl.textContent=''; }
    } else { dEl.textContent=''; dEl.style.opacity='0'; }

    // overtake flash when a player climbs into a better slot
    if(animateJumps && prevPos[p.username]!==undefined && place < prevPos[p.username]){
      row.classList.remove('jump'); void row.offsetWidth; row.classList.add('jump');
    }
  });
  prevPos=pos;

  // scoreboard
  const [y,m,d]=day.date.split('-').map(Number);
  const dt=new Date(Date.UTC(y,m-1,d));
  document.getElementById('dow').textContent=DOW[dt.getUTCDay()];
  document.getElementById('date').textContent=
    dt.toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}).toUpperCase();
  document.getElementById('dayno').textContent=idx+1;
  renderGames(day.date);

  scrub.value=idx;
  scrub.style.setProperty('--fill',(idx/(days.length-1)*100)+'%');
  document.getElementById('foot').textContent=
    `Provisional standings as the league stood entering each day · fixtures at right are that day’s matches · scoring +50 per correct finishing position, +30 per perfect group`;
}

function renderGames(date){
  const el=document.getElementById('games');
  const list=matches[date]||[];
  if(!list.length){
    el.innerHTML=`<div class="empty"><b>Rest day</b>No matches played on this date.</div>`;
    return;
  }
  el.innerHTML=list.map(g=>{
    const homeWin=g.hs>g.as, awayWin=g.as>g.hs;
    const t1=`<span class="${homeWin?'t':awayWin?'loser':'t'}">${g.home_flag} ${g.home}</span>`;
    const t2=`<span class="${awayWin?'t':homeWin?'loser':'t'}">${g.away} ${g.away_flag}</span>`;
    return `<div class="game${g.corrected?' corr':''}">
      <span class="grp${g.round?' ko':''}">${g.round||g.group}</span>
      <span class="fix">${t1}<span style="color:var(--faint)">v</span>${t2}</span>
      <span class="sc">${g.hs}–${g.as}</span>
      ${g.note?`<span class="tag">${g.note}</span>`:''}
      ${g.corrected?'<span class="tag">↺ score corrected</span>':''}
    </div>`;
  }).join('');
}

// ---- transport ----
const scrub=document.getElementById('scrub');
const playBtn=document.getElementById('play');
scrub.max=days.length-1;
document.getElementById('daytot').textContent=days.length;
const fmt = s => { const[y,m,d]=s.split('-'); return new Date(Date.UTC(+y,+m-1,+d)).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}); };
document.getElementById('tick0').textContent=fmt(days[0].date);
document.getElementById('tick1').textContent=fmt(days[days.length-1].date);

let cur=0, playing=false, timer=null, speedIdx=0;
// Default to a slow, sit-with-it pace; faster gears for skimming.
const SPEEDS=[{l:'0.5×',ms:3600},{l:'1×',ms:2300},{l:'2×',ms:1300}];
const speedEl=document.getElementById('speed');
SPEEDS.forEach((s,i)=>{
  const b=document.createElement('button'); b.textContent=s.l; if(i===speedIdx)b.className='on';
  b.onclick=()=>{speedIdx=i;[...speedEl.children].forEach((c,j)=>c.className=j===i?'on':'');if(playing){stop();start();}};
  speedEl.appendChild(b);
});

function step(){ if(cur>=days.length-1){stop();return;} cur++; render(cur,true); }
function start(){
  playing=true; playBtn.innerHTML='&#10073;&#10073;';
  if(cur>=days.length-1){cur=0; render(0,false);}
  timer=setInterval(step,SPEEDS[speedIdx].ms);
}
function stop(){ playing=false; playBtn.innerHTML='&#9654;'; clearInterval(timer); timer=null; }
playBtn.onclick=()=>playing?stop():start();
scrub.oninput=()=>{ stop(); cur=+scrub.value; render(cur,false); };

render(0,false);
setTimeout(start,750);
</script>
</body>
</html>
"""


def main():
    args = sys.argv[1:]
    open_it = "--open" in args
    args = [a for a in args if a != "--open"]
    out = args[0] if args else os.path.join(HERE, "race.html")
    days = load_history()
    if not days:
        sys.exit("no history/*.json snapshots found")
    html = build(days, load_matches())
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}  ({len(days)} days, {len(days[-1]['entries'])} players)")
    if open_it:
        webbrowser.open(f"file://{os.path.abspath(out)}")


if __name__ == "__main__":
    main()
