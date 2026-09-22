# SPIKE — renaming `market-history`

**Status:** nothing done, nothing decided. Investigated 2026-09-22 after the
docs/private/config reorg landed (`e8c9d8e`). The name choice below is a
recommendation, not a decision — it needs the owner's say-so.

> Working note. The question was "what would you rename it to, and is that safe?"
> This is the answer, written down so it doesn't have to be re-derived later.

## Why the name is wrong

`README.md` still opens with:

> Not a dashboard, not a decision tool (yet): the sole job right now is to
> **hydrate a clean dataset**.

That stopped being true some time ago. The folder now holds an appraiser skill,
an offer advisor, a housing score, a desirability map, a tier list, a
repair-cost guide, buyer requirements and per-house appraisal notes with photos.
Sold history is *one input* to all of that, and the folder is named after it.

It's also the hub now — house-hunt is deprioritised and new data lands here — so
the misleading name is on the thing people reach for first.

## What to call it

**`house-math`.** Plain language, covers the whole job (what's it worth, what
should we offer, what will the repairs cost, which town scores better), and it's
clearly *not* `house-hunt` — which matters, because that folder still exists and
a name like `home-search` would blur the two.

Runner-up: **`home-buying`**. Duller, but impossible to misread.

Whatever it lands on, the stale README line above goes with it.

## Is it safe?

**Yes — and the reorg is what made it so.** Every module computes its paths from
`__file__` and every import is intra-folder (`import towns`). **Not one line of
Python needs to change.** Also unaffected:

- **Git history.** A `git mv` is a rename; `log --follow` keeps working.
- **The published site URL.** `pages.yml` flattens files into `_site/`, so the
  folder name never appears in the public URL.
- **The data files.** No absolute paths inside the CSVs or JSON.
- **The launchd job.** Not installed — `~/Library/LaunchAgents` has no copy, so
  the plist is dormant. Nothing live breaks.
- **Scheduling.** There is no `job.json` here. This folder is a hub, not a
  scheduled routine, so no cron points at it.

## What actually breaks, worst first

### 1. The root `.gitignore` — this one fails open

Seven rules hardcode the `market-history/` prefix (lines 34–44), including:

```
market-history/appraise/appraisals/
market-history/appraise/run/
```

`appraisals/` holds house photos and personal appraisal notes. Rename the folder
without updating these and **the ignore silently stops matching**: nothing
errors, nothing warns, those files just quietly become stageable — on a repo
that is **public**.

Every other failure here is loud or harmless. This one isn't. **It must go in
the same commit as the rename**, and `git status --ignored` must be checked
straight after.

### 2. `.github/workflows/pages.yml` — silent too

Twenty references, including the `paths:` trigger filter. Get that filter wrong
and the workflow simply never fires: no error, no red X, the Pages site just
keeps serving yesterday's numbers. Confirm the workflow actually triggered after
the first push.

### 3. `.claude/skills/appraise/SKILL.md`

Hardcodes `cd market-history/appraise` and the appraisals output path. Fails at
the next appraisal — loudly enough to notice, annoying enough to avoid.

### 4. Prose, ~50 places

Docs, docstrings, the `market-history/0.1` User-Agent in `aggregate.py`, the
`/tmp/market-history-listings.log` path in the plist. Harmless if missed, but
leaves the repo half-renamed.

**83 references total, ~30 of them path-bearing** (counted 2026-09-22, before
this note and its TODO card added a few more of their own). All mechanical.

## The recipe

1. **One commit:** `git mv market-history <new-name>`, *plus* root `.gitignore`,
   `pages.yml` and `appraise/SKILL.md` in that same commit.
2. **Second commit:** the prose sweep, including the stale README line.
3. **Verify:** `git status --ignored` (confirm `appraisals/` is still ignored —
   this is the one that matters), `compileall`, `hydrate.py --check`, the
   markdown link check, then push and watch the Pages workflow fire.

## Verdict

Worth doing, low risk, **not urgent** — but it only gets more expensive, since
every week adds references. The same-commit `.gitignore` discipline is the whole
ballgame; everything else is find-and-replace.

**Open question for the owner:** is `house-math` the name, or something else?
Nothing should move until that's answered — a rename done twice costs double.
