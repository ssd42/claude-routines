# house-hunt — agent notes

Daily new-listing scout + list→sold watchlist tracker for target neighborhoods.
See [`README.md`](README.md) for the full board sections, how-it-works steps, and
run/demo commands. **Status: SPIKE** — some agent-side steps (per-source fetch,
Slack thread-reply intake, `data_home` persistence) are not wired up yet; check
the README's Status section before assuming a step exists.

## Independence
This routine is self-contained (see the root [`../CLAUDE.md`](../CLAUDE.md)).
Keep all changes inside this folder. Do **not** import from or read
`bracket-challenge/` — the shared fetch→reconcile→score→diff→post shape is a
*pattern*, not shared *code*. Don't extract a shared module unless explicitly
asked.

## Shape of the work
- `match.py` is **deterministic**: reconcile (address+zip match, 2-of-3 numeric
  consensus, ⚠ on disagreement) → score against `criteria.json` → diff against
  `seen.json` → track watchlist. Same inputs → same board.
- Memory that must persist between runs: `history/`, `seen.json`,
  `watchlist.json` (committed). `raw/` is transient per-run fetch (gitignored).
- Config in `criteria.json` (what counts as a match) and `job.json` (schedule +
  Slack delivery + watchlist intake). The webhook (`HOUSE_HUNT_SLACK_WEBHOOK`)
  lives only on the remote Claude routine — never save it here.
- Slack delivery: post to channel `C0B9JHL9NE9` (the incoming webhook has gone to
  the wrong channel before — verify the target).
