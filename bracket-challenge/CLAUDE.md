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
