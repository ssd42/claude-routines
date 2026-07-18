#!/usr/bin/env python3
"""
Leaderboard scorer for the World Cup 2026 Bracket Challenge.

Two phases, ONE cumulative season total:

GROUP STAGE  (now FINAL — the group total is frozen)
  +50  per team whose predicted finishing position matches the final table
  +30  bonus per group where ALL FOUR positions are correct
  => max per group = 4*50 + 30 = 230 ; max total = 12 * 230 = 2760

KNOCKOUTS  (scored once the bracket starts — adds ON TOP of the group total)
  Cumulative per round, per correctly-predicted team:
  +20  reaches the Round of 16   (i.e. wins its Round-of-32 match)
  +30  reaches the Quarter Finals
  +40  reaches the Semi Finals
  +75  reaches the Final
  +100 is the World Champion
  A team predicted (and actually going) all the way banks 20+30+40+75+100 = 265.
  NOTE: just qualifying for the knockouts (Round of 32) awards no points here —
  that was rewarded by the group-stage finishing positions.

The two phases simply add: total = group_total + knockout_total. The group
total stops moving once the groups are final; from then on the board swings on
knockout results only.

GROUP "CURRENT FINISHING ORDER" is derived from the table by the tiebreak chain
we can compute from a simple row: points -> goal diff -> goals for -> FIFA world
ranking (lower = better) -> name. See tiebreakers.md.

INPUTS

predictions.json
  {
    "players": [
      { "name": "Steven", "username": "stevenpybots",
        "groups": { "A": ["MEX","USA","CRC","JAM"], ... },
        "thirds": [...],                       # 8 best-third picks (group phase)
        "ko": {                                # knockout bracket picks (optional)
          "r16":   [...],   # teams you have winning their R32 match
          "qf":    [...],   # ... reaching the Quarter Finals
          "sf":    [...],   # ... reaching the Semi Finals
          "final": [...],   # your two finalists
          "champion": "ARG" # your World Champion
        }
      },
      ...
    ]
  }
  Each `ko` list is the set of teams predicted to reach AT LEAST that round, so
  the lists nest (your champion is in `final`, your finalists are in `sf`, ...).
  You only have to place each team at its DEEPEST round — score.py propagates it
  back to the earlier rounds.

standings.json   (final group tables)
  { "groups": { "A": [{"team":"MEX","pts":9,"gd":6,"gf":6}, ...], ... } }

knockouts.json   (optional; actual knockout results — see that file's _doc)
  { "r16": [...], "qf": [...], "sf": [...], "final": [...], "champion": "ARG" }
  Auto-loaded from the predictions folder if present. When it exists and has any
  result, the board switches to GROUP+KNOCKOUT mode. Until then the board is the
  pure group-stage board (unchanged behaviour).

USAGE
  python score.py predictions.json standings.json [YYYY-MM-DD] [--force] [--image-prompt]
"""

import datetime
import glob
import json
import os
import sys


# Knockout rounds: (key, points, label). `champion` is a single team, not a list.
KO_ROUNDS = [
    ("r16", 20, "Round of 16"),
    ("qf", 30, "Quarter Finals"),
    ("sf", 40, "Semi Finals"),
    ("final", 75, "Final"),
    ("champion", 100, "Champion"),
]


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


def score_player_groups(player, standings, rankings=None):
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


def expand_ko(d):
    """Normalize a knockout dict into cumulative team-SETS per round.

    Accepts lists for r16/qf/sf/final and a scalar (or 1-list) for champion. A
    team listed only in its deepest round is propagated back to the earlier
    rounds, so the input can be fully nested OR furthest-round-only and still
    scores the same. Returns {round_key: set(team_codes)}."""
    if not d:
        return {key: set() for key, _, _ in KO_ROUNDS}
    champ = d.get("champion")
    champ_set = (set(champ) if isinstance(champ, list) else {champ}) if champ else set()
    sets = {
        "r16": set(d.get("r16") or []),
        "qf": set(d.get("qf") or []),
        "sf": set(d.get("sf") or []),
        "final": set(d.get("final") or []),
        "champion": champ_set,
    }
    # propagate deeper rounds outward into the shallower ones (cumulative nesting)
    sets["final"] |= sets["champion"]
    sets["sf"] |= sets["final"]
    sets["qf"] |= sets["sf"]
    sets["r16"] |= sets["qf"]
    return sets


def ko_active(actual_ko):
    """True once any knockout result is known (so the board switches modes)."""
    if not actual_ko:
        return False
    return any(actual_ko.get(k) for k, _, _ in KO_ROUNDS)


def validate_ko(name, ko):
    """Informational sanity check on a player's knockout picks (stderr only).
    Flags wrong round sizes / missing champion so hand-transcription errors
    surface — purely advisory, never changes scoring."""
    if not ko:
        return
    for key, n in (("r16", 16), ("qf", 8), ("sf", 4), ("final", 2)):
        got = len(ko.get(key) or [])
        if got != n:
            print(f"  ! {name}: {key} has {got} teams (expected {n})", file=sys.stderr)
    if not ko.get("champion"):
        print(f"  ! {name}: champion missing", file=sys.stderr)


def score_player_ko(player, actual_sets):
    """Cumulative knockout points for one player against the actual results.
    actual_sets is expand_ko(knockouts.json). Returns (points, breakdown)."""
    pred = expand_ko(player.get("ko"))
    total = 0
    breakdown = {}
    for key, val, _label in KO_ROUNDS:
        hits = pred[key] & actual_sets[key]
        if hits:
            breakdown[key] = {"pts": val * len(hits), "teams": sorted(hits)}
            total += val * len(hits)
    return total, breakdown


def build_leaderboard(predictions, standings, rankings=None, actual_ko=None):
    actual_sets = expand_ko(actual_ko) if ko_active(actual_ko) else None
    board = []
    for p in predictions["players"]:
        gpts, gbreak = score_player_groups(p, standings, rankings)
        if actual_sets is not None:
            validate_ko(p["name"], p.get("ko"))
            kpts, kbreak = score_player_ko(p, actual_sets)
        else:
            kpts, kbreak = 0, {}
        board.append({"name": p["name"], "username": p.get("username"),
                      "group": gpts, "ko": kpts, "total": gpts + kpts,
                      "breakdown": gbreak, "ko_breakdown": kbreak})
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
    """Persist today's board so tomorrow can diff against it. Stores the
    group/ko split too; older snapshots that predate the knockouts simply lack
    those keys (diffing only needs total + rank, so it stays compatible)."""
    os.makedirs(history_dir, exist_ok=True)
    rows = [
        {"name": r["name"], "username": r.get("username"),
         "group": r.get("group", r["total"]), "ko": r.get("ko", 0),
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


def render_ascii(board, standings, previous, today, ko_on=False):
    if ko_on:
        return render_ascii_ko(board, previous, today)
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


def render_ascii_ko(board, previous, today):
    """Group-final + knockouts board: shows the frozen GRP total, KO points
    earned so far, the running TOTAL, and movement vs yesterday."""
    width = 48  # matches the column rows below exactly (1+3+1+20+5+5+6+2+4+1)
    lines = []
    lines.append("+" + "-" * width + "+")
    lines.append(f"|  SCORES AS OF {pretty_date(today)}".ljust(width + 1) + "|")
    lines.append("|  group stage final + knockouts".ljust(width + 1) + "|")
    lines.append("+" + "-" * width + "+")
    lines.append(f"| {'#':>3} {'PLAYER':<20}{'GRP':>5}{'KO':>5}{'TOT':>6}  {'+/-':>4} |")
    lines.append("+" + "-" * width + "+")
    for row in board:
        rank = f"{row['rank']}."
        name = row["name"][:20]
        move = movement(row, previous)
        ko = f"+{row['ko']}" if row.get("ko") else "—"
        line = (f"| {rank:>3} {name:<20}{row.get('group', 0):>5}"
                f"{ko:>5}{row['total']:>6}  {move:>4} |")
        lines.append(line)
    lines.append("+" + "-" * width + "+")
    lines.append("  GRP = group total (final) · KO = knockout pts so far")
    lines.append("  knockouts: R16 +20, QF +30, SF +40, Final +75, Champ +100")
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

    # FIFA ranking is the final group-stage tiebreaker; load it if present.
    rankings = {}
    rankings_path = os.path.join(base_dir, "fifa_rankings.json")
    if os.path.exists(rankings_path):
        with open(rankings_path) as f:
            rankings = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    # Actual knockout results: auto-loaded if knockouts.json sits next to the
    # predictions. Once it holds any result the board switches to GRP+KO mode.
    actual_ko = None
    ko_path = os.path.join(base_dir, "knockouts.json")
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            actual_ko = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    ko_on = ko_active(actual_ko)

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
            board = json.load(f)  # rows: name, username, group, ko, total, rank
        print(f"NOTE: history/{today}.json already exists — reusing today's "
              "frozen board; positions are computed once per day and were NOT "
              "recomputed. (Pass --force to recompute and replace the baseline.)\n",
              file=sys.stderr)
        # an old (group-only) snapshot won't carry the ko split; render in
        # whichever mode the snapshot supports
        ko_on = ko_on and any("ko" in r for r in board)
    else:
        board = build_leaderboard(predictions, standings, rankings, actual_ko)

    print(render_ascii(board, standings, previous, today, ko_on=ko_on))
    if not frozen:
        save_snapshot(board, history_dir, today)

    if want_prompt:
        template_path = os.path.join(base_dir, "image-prompt.template.txt")
        print("\n\n===== CHATGPT IMAGE PROMPT (paste into ChatGPT) =====\n")
        print(fill_image_prompt(board, previous, today, template_path))


if __name__ == "__main__":
    main()
