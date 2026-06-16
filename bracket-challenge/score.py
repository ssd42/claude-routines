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


def pretty_date(iso):
    """Render an ISO date (YYYY-MM-DD) for display, e.g. 'JUNE 12, 2026'.
    Only used in the board header / image prompt; filenames + snapshot keys
    stay ISO."""
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B').upper()} {d.day}, {d.year}"


def group_started(rows):
    """True once at least one game has been played in the group.

    Every played match awards points (3 for a win, 1 each for a draw — even a
    0-0), so any non-zero points total means a game has happened. Before kickoff
    all rows are zero and current_order would just fall back to alphabetical, so
    we must NOT score a group until it has actually started."""
    return any(r["pts"] > 0 for r in rows)


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
        if not group_started(rows):
            continue  # no games played yet -> nothing to score (avoids phantom
                      # points from the alphabetical tiebreak on all-zero rows)
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


def render_ascii(board, standings, previous, today):
    counted = [g for g, rows in standings["groups"].items() if group_started(rows)]
    groups_in = ", ".join(sorted(counted)) or "(none yet — no games played)"
    width = 42
    lines = []
    lines.append("+" + "-" * width + "+")
    lines.append(f"|  SCORES AS OF {pretty_date(today)}".ljust(width + 1) + "|")
    lines.append("|  if the group stage ended today".ljust(width + 1) + "|")
    lines.append("+" + "-" * width + "+")
    for row in board:
        rank = f"{row['rank']}."
        name = row["name"][:22]  # show the player's actual name, not their handle
        move = movement(row, previous)
        line = f"| {rank:>3} {name:<22}{row['total']:>6}  {move:>4} |"
        lines.append(line)
    lines.append("+" + "-" * width + "+")
    lines.append(f"  groups counted: {groups_in}")
    lines.append("  scoring: +50 / correct position, +30 / perfect group")
    lines.append("  ▲/▼ = places moved since yesterday")
    return "\n".join(lines)


def fill_image_prompt(board, previous, today, template_path):
    """Return the Panini ChatGPT prompt with this board's exact rows filled in."""
    rows = []
    for r in board:
        name = r["name"]  # show the player's actual name, not their handle
        move = movement(r, previous)
        dots = "." * max(2, 22 - len(name))
        rows.append(f"{r['rank']}.  {name} {dots} {r['total']}   {move}")
    leaderboard = "\n".join(rows)
    with open(template_path) as f:
        template = f.read()
    return template.replace("{{DATE}}", pretty_date(today)).replace("{{LEADERBOARD}}", leaderboard)


def main():
    flags = {"--image-prompt", "--force"}
    args = [a for a in sys.argv[1:] if a not in flags]
    want_prompt = "--image-prompt" in sys.argv
    force = "--force" in sys.argv
    if len(args) not in (2, 3):
        print("usage: python score.py predictions.json standings.json [YYYY-MM-DD] [--image-prompt] [--force]",
              file=sys.stderr)
        sys.exit(2)
    with open(args[0]) as f:
        predictions = json.load(f)
    with open(args[1]) as f:
        standings = json.load(f)
    today = args[2] if len(args) == 3 else datetime.date.today().isoformat()
    base_dir = os.path.dirname(os.path.abspath(args[0]))
    history_dir = os.path.join(base_dir, "history")

    # FIFA ranking is the final tiebreaker; load it if present, else skip.
    rankings = {}
    rankings_path = os.path.join(base_dir, "fifa_rankings.json")
    if os.path.exists(rankings_path):
        with open(rankings_path) as f:
            rankings = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    # Positions are computed ONCE per day, by the first (scheduled) run. A
    # same-day re-run must NOT recompute ranks/totals: whatever the day's first
    # run posted is the board the league saw, and it's also tomorrow's ▲/▼
    # baseline. Re-running and overwriting the snapshot silently moves that
    # baseline, so the next day's arrows measure change against a board nobody
    # saw (this is exactly what broke the 2026-06-15 arrows — see CLAUDE.md).
    # So: if today's snapshot already exists, reuse it verbatim. Use --force
    # only for a genuine correction where you intend to replace the baseline.
    today_path = os.path.join(history_dir, f"{today}.json")
    previous = load_previous(history_dir, today)
    frozen = os.path.exists(today_path) and not force
    if frozen:
        with open(today_path) as f:
            board = json.load(f)  # rows: name, username, total, rank
        print(f"NOTE: history/{today}.json already exists — reusing today's "
              "frozen board; positions are computed once per day and were NOT "
              "recomputed. (Pass --force to recompute and replace the baseline.)\n",
              file=sys.stderr)
    else:
        board = build_leaderboard(predictions, standings, rankings)

    print(render_ascii(board, standings, previous, today))
    if not frozen:
        save_snapshot(board, history_dir, today)

    if want_prompt:
        template_path = os.path.join(base_dir, "image-prompt.template.txt")
        print("\n\n===== CHATGPT IMAGE PROMPT (paste into ChatGPT) =====\n")
        print(fill_image_prompt(board, previous, today, template_path))


if __name__ == "__main__":
    main()
