#!/usr/bin/env python3
"""
Agent / brokerage pattern analysis for house-hunt  (STANDALONE, additive).

This is an EXTRA task layered on top of the existing pipeline — it reads the
sold-comp archive that match.py already builds (seen.json -> "sold"), and looks
for patterns in WHO listed the houses that sold, and how they closed vs asking.

The use case: find a realty brokerage (or agent) whose listings tend to close
UNDER asking — i.e. where a buyer has historically gotten a deal — so you can
prioritize houses currently listed by that brokerage.

⚠️ DATA LIMITATION — SELLER SIDE ONLY
  Realtor.com (via HomeHarvest) publishes the LISTING (seller-side) agent and
  brokerage only. The BUYER's agent is not exposed by this source, so every
  pattern below is seller-side ("this brokerage LISTED houses that sold under
  ask"). Adding buyer-side would require an MLS / different data source.

It changes NOTHING in the existing routine: no shared state is written, it only
reads seen.json. Run it whenever you want the pattern report.

USAGE
  python3 agents.py                # report (brokerages, then agents)
  python3 agents.py --md           # Slack-markdown summary (post via Slack MCP)
  python3 agents.py --min N        # min sales to include a name (default 4)
  python3 agents.py --zip 07076    # restrict to one or more zips (repeatable)
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _median(nums):
    s = sorted(n for n in nums if n is not None)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def load_solds(zips=None):
    """Sold comps from seen.json that have a list+sold price (so vs-ask is real)."""
    path = os.path.join(BASE_DIR, "seen.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        archive = json.load(f).get("sold", {})
    out = []
    for r in archive.values():
        if not (r.get("list_price") and r.get("sold_price")):
            continue
        if zips and r.get("zip") not in zips:
            continue
        out.append(r)
    return out


def _norm_name(name):
    return " ".join((name or "").split()).strip()


def aggregate(solds, key_field):
    """Group sold comps by an agent/brokerage name -> pattern stats."""
    groups = {}
    for r in solds:
        name = _norm_name(r.get(key_field))
        if not name:
            continue
        groups.setdefault(name, []).append(r)

    rows = []
    for name, recs in groups.items():
        ratios = [r["sold_price"] / r["list_price"] for r in recs]
        under = sum(1 for x in ratios if x < 1)
        ppsf = [r["sold_price"] / r["sqft"] for r in recs if r.get("sqft")]
        zips = sorted({r.get("zip") for r in recs if r.get("zip")})
        rows.append({
            "name": name,
            "n": len(recs),
            "median_vs_ask": (_median(ratios) - 1) * 100,  # %; negative = under ask
            "pct_under": under / len(recs) * 100,
            "median_dom": _median([r.get("dom") for r in recs]),
            "median_ppsf": _median(ppsf),
            "zips": zips,
        })
    return rows


def _fmt(row, show_zips=True):
    dom = f"{row['median_dom']:.0f}d" if row["median_dom"] is not None else "?"
    ppsf = f"${row['median_ppsf']:,.0f}/sf" if row["median_ppsf"] is not None else ""
    z = f"  [{', '.join(row['zips'][:4])}{'…' if len(row['zips']) > 4 else ''}]" if show_zips else ""
    return (f"{row['median_vs_ask']:+.1f}% vs ask  n={row['n']:<3} "
            f"{row['pct_under']:.0f}% under  {dom}  {ppsf}  {row['name']}{z}")


def report(brokerages, agents, total, with_name, min_n, md=False):
    under_b = sorted([r for r in brokerages if r["n"] >= min_n], key=lambda r: r["median_vs_ask"])
    over_b = [r for r in reversed(under_b)]
    under_a = sorted([r for r in agents if r["n"] >= min_n], key=lambda r: r["median_vs_ask"])

    if md:
        L = ["🧑‍💼 *Agent / brokerage patterns* — _seller-side (buyer agent not published)_",
             f"_{with_name} of {total} sold comps have a listing agent/brokerage · min {min_n} sales_", ""]
        L.append("*🟢 Brokerages that close UNDER asking*")
        L += [f"• {_fmt(r, show_zips=False)}" for r in under_b[:8]] or ["_none yet_"]
        L += ["", "*🔴 Brokerages that close OVER asking*"]
        L += [f"• {_fmt(r, show_zips=False)}" for r in over_b[:5]] or ["_none yet_"]
        L += ["", "*🧑 Agents that close UNDER asking*"]
        L += [f"• {_fmt(r, show_zips=False)}" for r in under_a[:8]] or ["_none yet_"]
        return "\n".join(L)

    L = ["🧑‍💼  AGENT / BROKERAGE PATTERNS  (seller-side; buyer agent not published)",
         f"   {with_name} of {total} sold comps carry a listing agent/brokerage · min {min_n} sales",
         "   line: median vs ask · n sales · % that sold under ask · median DOM · median $/sf · name",
         "",
         "🟢 BROKERAGES that close UNDER asking (ranked, most-under first)"]
    L += [f"   {_fmt(r)}" for r in under_b[:15]] or ["   (none meet the threshold yet)"]
    L += ["", "🔴 BROKERAGES that close OVER asking (for contrast)"]
    L += [f"   {_fmt(r)}" for r in over_b[:8]] or ["   (none)"]
    L += ["", "🧑 AGENTS that close UNDER asking (ranked)"]
    L += [f"   {_fmt(r)}" for r in under_a[:15]] or ["   (none meet the threshold yet)"]
    return "\n".join(L)


def main():
    args = sys.argv[1:]
    md = "--md" in args
    min_n = 4
    if "--min" in args:
        min_n = int(args[args.index("--min") + 1])
    zips = [args[i + 1] for i, a in enumerate(args) if a == "--zip"] or None

    solds = load_solds(zips)
    total = len(solds)
    with_name = sum(1 for r in solds if _norm_name(r.get("list_brokerage")) or _norm_name(r.get("list_agent")))
    if not total:
        print("No sold comps with list+sold price in seen.json yet. "
              "Run `python3 fetch.py` (solds on by default) then `match.py <date>` first.",
              file=sys.stderr)
        sys.exit(1)

    brokerages = aggregate(solds, "list_brokerage")
    agents = aggregate(solds, "list_agent")
    print(report(brokerages, agents, total, with_name, min_n, md=md))


if __name__ == "__main__":
    main()
