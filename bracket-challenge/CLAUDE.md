# bracket-challenge — agent notes

Daily **provisional** leaderboard for a friend-league FIFA WC2026 Bracket
Challenge (group stage only). See [`README.md`](README.md) for the full
description, scoring rules, and run command.

## Independence
This routine is self-contained (see the root [`../CLAUDE.md`](../CLAUDE.md)).
Keep all changes inside this folder. Do **not** import from or read
`house-hunt/` — any resemblance in the fetch→reconcile→score→diff→post pipeline
is a shared *pattern*, not shared *code*. Don't extract a shared module unless
explicitly asked.

## Shape of the work
- `score.py` is **deterministic** — same inputs must give the same board. Keep it
  pure; no network, no clock-dependent behavior beyond the date you pass in.
- State/memory lives in `history/<date>.json`: a run reads yesterday's snapshot
  (for ▲▼ arrows) and writes today's. Don't break that contract.
- Standings come from independent `sources.json` reconciled by 2-of-3 consensus.
- Delivery target (Slack channel) is in `job.json`. Secrets stay out of the repo.

## Operational notes from prod runs (read before running)
Hard-won lessons from real scheduled runs — follow these to avoid known traps:

- **Slack channel ID is a constant — don't search for it.** `#world-cup-groups`
  = `C0B9MHSGKQA` (created June 10, won't change; also in `job.json`). Use the ID
  directly; never call `slack_search_channels` each run.
- **WebFetch is blocked (HTTP 403) on every major sports site** in the run
  environment — foxsports, espn, fifa, nbcsports, cbssports, livescore, etc.
  Don't attempt WebFetch for standings. Go straight to **WebSearch**, one
  targeted query per group (e.g. `2026 World Cup Group C standings Scotland Haiti
  score`). Budget **two** search rounds per group; if still unresolved, mark the
  group disputed and move on.
- **Git push-permission check: keep it simple.** Just run `git push --dry-run
  origin main` — git still negotiates auth, nothing is written. Do **not** use
  the `git commit --allow-empty` + `--dry-run` + `git reset --soft HEAD~1`
  trick: it detaches HEAD and cascades into stash/merge conflicts when you later
  commit real data.
- **Don't clobber a fuller snapshot.** If `history/<today>.json` already exists,
  an earlier run finished today (maybe with fewer groups). Read it, compare group
  counts, and only overwrite if the new data has **genuinely more groups**. A
  partial snapshot overwriting a fuller one breaks tomorrow's ▲/▼ baseline.
- **Get standings right before committing.** Arrows compare to the most recent
  snapshot *strictly before today*. Don't commit an intermediate/partial
  today-snapshot — whatever you commit becomes tomorrow's comparison baseline.
- **Use the correct date everywhere.** Compute it once with
  `TZ=America/New_York date +%Y-%m-%d` and pass it to `score.py`; a wrong date in
  an intermediate run is what produced a stale title (e.g. "June 12" on a June 13
  board) in the past.
