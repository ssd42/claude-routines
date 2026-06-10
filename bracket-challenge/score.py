#!/usr/bin/env python3
"""
Provisional group-stage scorer for the World Cup 2026 Bracket Challenge.

Knockouts are NOT scored here (FIFA scores those). This only computes the
group-stage points "as if the group stage ended today", so a league can watch
the leaderboard swing every day instead of waiting for the real reveal.

SCORING (group stage only)
  +50  per team whose predicted finishing position matches the actual table
  +30  bonus per group where ALL FOUR positions are correct
  => max per group = 4*50 + 30 = 230 ; max total = 12 * 230 = 2760

"CURRENT FINISHING ORDER" is derived from the live table by the standard
tiebreak chain we can compute from a simple table row:
  1. points   (desc)
  2. goal difference  (desc)
  3. goals for  (desc)
  4. team name  (asc)  -- documented fallback so output is deterministic.
     NOTE: real FIFA tiebreaks then use head-to-head, fair-play, drawing of
     lots. Early in a group, teams are genuinely tied and this fallback may
     order them differently than FIFA eventually will. That's fine for a
     *provisional* board; it self-corrects as matches are played.

INPUTS (two JSON files)

predictions.json
  {
    "players": [
      { "name": "Steven",
        "groups": { "A": ["MEX","USA","CRC","JAM"], "B": [...], ... } },
      ...
    ]
  }
  Each group's list is the predicted finish order: [1st, 2nd, 3rd, 4th].
  Use consistent short team codes everywhere (your call what they are).

standings.json   (today's live tables; only include groups that have started)
  {
    "groups": {
      "A": [
        {"team":"MEX","pts":4,"gd":2,"gf":3},
        {"team":"USA","pts":4,"gd":1,"gf":2},
        {"team":"CRC","pts":1,"gd":-1,"gf":1},
        {"team":"JAM","pts":0,"gd":-2,"gf":0}
      ],
      ...
    }
  }
  Order of rows does NOT matter; we sort by the tiebreak chain ourselves.

USAGE
  python score.py predictions.json standings.json
"""

import datetime
import glob
import json
import os
import sys


def current_order(rows, rankings=None):
    """Return team codes in current finishing order (1st..4th).

    Approximate tiebreak from table data only: points -> overall goal diff ->
    overall goals -> FIFA world ranking (lower = better) -> name. We can't do
    the official head-to-head (criteria 1-3) or conduct (6) without match/card
    data; consensus on the FINAL order handles that once a group completes.
    See tiebreakers.md."""
    rankings = rankings or {}
    ordered = sorted(
        rows,
        key=lambda r: (-r["pts"], -r["gd"], -r["gf"], rankings.get(r["team"], 999), r["team"]),
    )
    return [r["team"] for r in ordered]


def score_group(predicted, actual_order):
    """predicted/actual_order are 4-length lists of team codes.
    Returns (points, positions_correct, perfect_bool)."""
    correct = sum(1 for i in range(len(actual_order)) if predicted[i] == actual_order[i])
    perfect = correct == len(actual_order)
    points = correct * 50 + (30 if perfect else 0)
    return points, correct, perfect


def score_player(player, standings, rankings=None):
    total = 0
    breakdown = {}
    for g, rows in standings["groups"].items():
        predicted = player["groups"].get(g)
        if not predicted:
            continue  # player didn't predict this group (shouldn't happen)
        actual = current_order(rows, rankings)
        pts, correct, perfect = score_group(predicted, actual)
        total += pts
        breakdown[g] = {"pts": pts, "correct": correct, "perfect": perfect}
    return total, breakdown


def build_leaderboard(predictions, standings, rankings=None):
    board = []
    for p in predictions["players"]:
        total, breakdown = score_player(p, standings, rankings)
        board.append({"name": p["name"], "username": p.get("username"),
                      "total": total, "breakdown": breakdown})
    board.sort(key=lambda x: (-x["total"], x["name"]))
    # assign ranks with ties sharing a rank
    rank = 0
    last = None
    for i, row in enumerate(board):
        if row["total"] != last:
            rank = i + 1
            last = row["total"]
        row["rank"] = rank
    return board


def load_previous(history_dir, today):
    """Return {player_key: prior_row} from the most recent snapshot before
    `today`, or {} if there's no prior history. Keyed by username (stable),
    falling back to name."""
    if not os.path.isdir(history_dir):
        return {}
    snaps = sorted(glob.glob(os.path.join(history_dir, "*.json")))
    prior = [s for s in snaps if os.path.basename(s)[:-5] < today]
    if not prior:
        return {}
    with open(prior[-1]) as f:
        rows = json.load(f)
    return {(r.get("username") or r["name"]): r for r in rows}


def save_snapshot(board, history_dir, today):
    """Persist today's board so tomorrow can diff against it."""
    os.makedirs(history_dir, exist_ok=True)
    rows = [
        {"name": r["name"], "username": r.get("username"),
         "total": r["total"], "rank": r["rank"]}
        for r in board
    ]
    with open(os.path.join(history_dir, f"{today}.json"), "w") as f:
        json.dump(rows, f, indent=2)


def movement(row, previous):
    """Arrow string comparing this row's rank to the prior snapshot."""
    prev = previous.get(row.get("username") or row["name"])
    if prev is None:
        return "NEW"
    delta = prev["rank"] - row["rank"]  # +ve = moved up the board
    if delta > 0:
        return f"▲{delta}"   # ▲
    if delta < 0:
        return f"▼{-delta}"  # ▼
    return "—"               # — (no change)


def render_ascii(board, standings, previous):
    groups_in = ", ".join(sorted(standings["groups"].keys()))
    width = 42
    lines = []
    lines.append("+" + "-" * width + "+")
    lines.append("|  BRACKET CHALLENGE  -  AS OF TODAY".ljust(width + 1) + "|")
    lines.append("+" + "-" * width + "+")
    for row in board:
        rank = f"{row['rank']}."
        name = (row.get("username") or row["name"])[:22]
        move = movement(row, previous)
        line = f"| {rank:>3} {name:<22}{row['total']:>6}  {move:>4} |"
        lines.append(line)
    lines.append("+" + "-" * width + "+")
    lines.append(f"  groups counted: {groups_in}")
    lines.append("  scoring: +50 / correct position, +30 / perfect group")
    lines.append("  ▲/▼ = places moved since yesterday")
    return "\n".join(lines)


def main():
    if len(sys.argv) not in (3, 4):
        print("usage: python score.py predictions.json standings.json [YYYY-MM-DD]",
              file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1]) as f:
        predictions = json.load(f)
    with open(sys.argv[2]) as f:
        standings = json.load(f)
    today = sys.argv[3] if len(sys.argv) == 4 else datetime.date.today().isoformat()
    base_dir = os.path.dirname(os.path.abspath(sys.argv[1]))
    history_dir = os.path.join(base_dir, "history")

    # FIFA ranking is the final tiebreaker; load it if present, else skip.
    rankings = {}
    rankings_path = os.path.join(base_dir, "fifa_rankings.json")
    if os.path.exists(rankings_path):
        with open(rankings_path) as f:
            rankings = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    board = build_leaderboard(predictions, standings, rankings)
    previous = load_previous(history_dir, today)
    print(render_ascii(board, standings, previous))
    save_snapshot(board, history_dir, today)


if __name__ == "__main__":
    main()
