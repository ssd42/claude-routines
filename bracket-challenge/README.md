# bracket-challenge

Daily **provisional** leaderboard for our friend-league FIFA World Cup 2026
Bracket Challenge. Shows where everyone *would* rank "as of today" if the group
stage ended right now — so the standings swing daily instead of revealing once
at the end. Group stage only (FIFA scores the knockouts).

## How it works
1. **Fetch** live group tables from independent sources (see `sources.json`),
   reconciled by a 2-of-3 consensus on the raw numbers.
2. **Score** each player's bracket with `score.py` (deterministic).
3. **Diff** against yesterday's snapshot for ▲▼ movement arrows.
4. **Post** the board to Slack (channel in `job.json`).

This repo is also the **memory**: each run reads yesterday's snapshot from
`history/` and writes today's back. It is intentionally separate from any
production repo — the scheduled routine only ever has write access here.

## Scoring (group stage)
- **+50** per team whose predicted finishing position matches the table
- **+30** bonus per group where all 4 positions are correct
- Tiebreak order we compute: points → GD → GF → FIFA ranking → name
  (see `tiebreakers.md`; head-to-head/conduct handled by consensus once a
  group finalizes)

## Files
| file | what |
|------|------|
| `score.py` | deterministic scorer + ASCII board + snapshot/arrows |
| `predictions.steven.json` | league brackets (normalized to FIFA codes) |
| `roster.json` | league members + who's submitted |
| `teams.json` | team code ↔ name map |
| `sources.json` | standings sources + consensus rule |
| `fifa_rankings.json` | FIFA ranking (final tiebreaker) |
| `tiebreakers.md` | official tiebreaker rules reference |
| `job.json` | schedule + Slack delivery config |
| `history/` | dated leaderboard snapshots (the daily memory) |

## Run it
```bash
python3 score.py predictions.steven.json standings.json [YYYY-MM-DD]
```
Writes `history/<date>.json` and prints the board.
