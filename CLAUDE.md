# claude-routines

A home for standalone, Claude-driven **scheduled routines**. Each top-level
folder is one routine. This repo is deliberately isolated from any production
code: scheduled jobs get write access **here only**, so the blast radius is
limited to toy data — they never touch prod or trigger deploys.

## Layout
| path | what |
|------|------|
| [`bracket-challenge/`](bracket-challenge/) | daily provisional leaderboard for a WC2026 bracket-challenge friend league |
| [`house-hunt/`](house-hunt/) | daily new-listing scout + list→sold watchlist tracker for target neighborhoods |

Each routine folder has its own `README.md` (what it does + how to run it),
`CLAUDE.md` (agent notes for that routine), `job.json` (schedule + delivery
config), and `.py` scorer.

## Core principle: routines are independent

Treat each folder as its own self-contained project:

- **Self-contained.** A routine owns its data, state (its own `history/`,
  `seen.json`, etc.), config, and code. Everything it needs to run lives in its
  folder.
- **No cross-imports.** One routine must not import from or read another's
  files. There is no shared package they depend on.
- **Its own memory.** Routines persist their own state between runs inside their
  folder; never reach into a sibling's state.
- **Shared functionality is the exception, by copy not coupling.** They happen
  to share *patterns* — fetch → reconcile (2-of-3 consensus) → score → diff
  against yesterday → post to Slack — but each implements its own version. If a
  helper is genuinely worth sharing later, lifting it into a shared module is a
  deliberate decision; the default is to keep routines decoupled even at the
  cost of a little duplication.

Practically: when you work on one routine, scope your changes to that folder.
Don't refactor two routines into a shared abstraction unless explicitly asked.

## Working in this repo
- Each routine runs standalone with plain `python3` (stdlib only) — see the
  routine's README for the exact command.
- **The repo is the "DB."** There is no external database. A routine's committed
  JSON state files (`history/`, `seen.json`, `watchlist.json`, …) ARE its
  datastore: each run reads the prior state, writes the new state, then
  git-commits + pushes it so it survives to the next scheduled run (see each
  routine's `job.json` → `data_home`). `raw/` and other transient per-run
  fetches are gitignored and never committed.

## ⚠️ Security — THIS REPO IS PUBLIC

`github.com/ssd42/claude-routines` is a **public** repo. Anything committed here
is world-readable forever (git history keeps it even after a later deletion).

**Never, ever commit a secret.** That means webhook URLs, API tokens, keys,
cookies, auth headers — none of it goes into any tracked file (code, JSON,
markdown, fixtures, commit messages).

- Secrets live **outside** the repo: as env vars/secrets set on the **Claude
  routine** (the remote scheduled-agent server), read at run time. The
  house-hunt Slack webhook is `HOUSE_HUNT_SLACK_WEBHOOK` — it lives only on the
  routine and is never pasted here or onto a laptop. `job.json` stores only the
  channel id/name, never the URL.
- Config files reference secrets **by env-var name**, never by value.
- `.gitignore` blocks `.env*`, `*secret*`, `*webhook*`, `*.key`, `*.pem` as a
  backstop — but the rule is "never write it down in-repo," not "rely on the
  ignore."
- Before any commit, scan the staged diff for anything that looks like a secret
  (`https://hooks.slack.com/...`, long tokens). If unsure, do **not** commit —
  ask.
- If a secret ever does land in a commit: treat it as compromised — rotate it
  immediately, then scrub history. Don't just delete the line in a new commit.

## Autopilot — git workflow for scheduled runs

These routines run unattended and commit their own updated memory. Standard loop:

```bash
# 1. run the routine (writes history/, seen.json, etc.) — see routine README
python3 score.py ...            # or: python3 match.py ...

# 2. stage ONLY the routine's own data/state (never blanket `git add -A`)
git add bracket-challenge/history/            # or house-hunt/{history,seen.json,watchlist.json}

# 3. sanity-check what's staged BEFORE committing (secret scan)
git diff --cached

# 4. commit with a clear, dated message
git commit -m "bracket-challenge: leaderboard snapshot 2026-06-10"

# 5. push
git push origin main
```

Rules for the autopilot:
- **Scope the add.** Stage the specific files the routine produced. Never
  `git add -A`/`git add .` — that risks sweeping in a stray secret or scratch
  file.
- **Don't commit transient output.** `raw/`, `.playwright-mcp/`, `__pycache__/`
  are gitignored; keep it that way.
- One routine's run commits only that routine's files.
- If `git push` rejects (remote moved), `git pull --rebase origin main` then push
  again. Don't force-push `main`.
