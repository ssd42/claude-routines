# bracket-challenge

Daily leaderboard for our friend-league FIFA World Cup 2026 Bracket Challenge,
running the whole tournament from kickoff to the final. Two phases, **one
cumulative total**:

- **Group stage** *(now final, frozen)* — showed where everyone *would* rank "as
  of today" if the groups ended right then, so the board swung daily instead of
  revealing once at the end.
- **Knockouts** *(live)* — as the bracket plays out, each player banks points for
  every team they correctly predicted to reach each round. These add on top of
  the frozen group total, so the board keeps swinging through to the champion.

## How it works
1. **Fetch** the live truth from independent sources (see `sources.json`),
   reconciled by a 2-of-3 consensus on the raw numbers — the group tables during
   the group stage, and which teams advanced each round during the knockouts.
2. **Score** each player's bracket with `score.py` (deterministic): frozen group
   points + cumulative knockout points.
3. **Diff** against yesterday's snapshot for ▲▼ movement arrows.
4. **Post** the board to Slack (channel in `job.json`).

This repo is also the **memory**: each run reads yesterday's snapshot from
`history/` and writes today's back. It is intentionally separate from any
production repo — the scheduled routine only ever has write access here.

## Scoring
**Group stage** (frozen now that the groups are final):
- **+50** per team whose predicted finishing position matches the table
- **+30** bonus per group where all 4 positions are correct
- Tiebreak order we compute: points → GD → GF → FIFA ranking → name
  (see `tiebreakers.md`; head-to-head/conduct handled by consensus once a
  group finalizes)

**Knockouts** (cumulative, per correctly-predicted team, added on top):
- **+20** reaches the Round of 16 (i.e. wins its Round-of-32 match)
- **+30** reaches the Quarter Finals
- **+40** reaches the Semi Finals
- **+75** reaches the Final
- **+100** is the World Champion
- A team predicted (and actually going) all the way banks 20+30+40+75+100 = **265**.
  Just qualifying for the knockouts (Round of 32) is worth nothing here — that
  was already rewarded by the group-stage finishing positions.

## Files
| file | what |
|------|------|
| `score.py` | deterministic scorer (group + knockouts) + ASCII board + snapshot/arrows |
| `predictions.steven.json` | league brackets — group order, `thirds`, and each player's `ko` knockout picks (FIFA codes) |
| `roster.json` | league members + who's submitted |
| `teams.json` | team code ↔ name map |
| `sources.json` | standings/results sources + consensus rule |
| `fifa_rankings.json` | FIFA ranking (group-stage tiebreaker) |
| `standings.json` | final group tables (frozen) |
| `knockouts.json` | **live** actual knockout results — which teams reached each round |
| `tiebreakers.md` | official tiebreaker rules reference |
| `job.json` | schedule + Slack delivery config |
| `history/` | dated leaderboard snapshots (the daily memory) |
| `race.py` | builds `race.html` — an animated leaderboard bar-chart race |
| `matches.json` | day-by-day game log (the race's match reference) |

## Run it
```bash
python3 score.py predictions.steven.json standings.json [YYYY-MM-DD]
```
Writes `history/<date>.json` and prints the board. `knockouts.json` is
auto-loaded from this folder if present — once it holds any result the board
switches to the GROUP+KNOCKOUT layout automatically (no flag needed). Re-running
the same day reuses the frozen snapshot; pass `--force` to recompute and replace
the day's baseline (e.g. after fixing a knockout result).

## Visualize the race
```bash
python3 race.py --open      # rebuild race.html from history/ + matches.json, open it
```
`race.html` is a self-contained page (data embedded, no server/deps) that animates
the standings day by day from the June 11 kickoff (everyone at 0), with each day's
World Cup fixtures shown alongside. `matches.json` is the **hand-editable** match
reference — keyed by the date each game was played, sourced from the official
2026 World Cup group-stage schedule. To fix or add a game, edit `matches.json`
and re-run `race.py`.
