# Fetch runbook

How listings get into `raw/` each run. This is the **agent-side** half; once
`raw/*.json` exists, `match.py` does everything after it.

> ⚠️ **This must run LOCALLY (on a residential IP), not in the cloud routine.**
> Redfin/Zillow/Realtor 403 every datacenter IP, and the scheduled cloud
> sandbox blocks all outbound HTTP except the git proxy + attached MCP
> connectors. So there is no free cloud path to listings — fetch on your Mac.

## `fetch.py` — what it does
`python3 fetch.py` writes one `raw/<source>.json` (in the shape `match.py`'s
header docstring documents), for the zips in `criteria.json` (07076 Scotch
Plains, 07067 Colonia). Two free sources, first that returns listings wins:

1. **RentCast** (primary) — official JSON API, free **50 calls/mo**. stdlib only.
   Needs `RENTCAST_API_KEY` (free signup at rentcast.io). No photos. Used when
   the env var is set.
2. **HomeHarvest** (fallback) — free OSS scraper of Realtor.com. No key, and it
   **adds photos + real listing URLs**. `pip install homeharvest`. Used when
   there's no RentCast key, or RentCast errors/quota-hits.

```bash
python3 fetch.py                 # auto-pick source
python3 fetch.py --source homeharvest   # force a source
python3 fetch.py --sold          # also pull recently-sold comps (HomeHarvest)
```

Field mapping notes:
- HomeHarvest `style` (e.g. `SINGLE_FAMILY`) is normalized to the `criteria.json`
  property-type strings (`Single Family`, `Townhouse`, …) — otherwise `match.py`
  would exclude every row as the "wrong type".
- pandas `NA`/`NaN` cells become `null`.
- `raw/*.json` is cleared at the start of each fetch and is gitignored.

## One-time setup
- (Recommended) free RentCast account → `export RENTCAST_API_KEY=…`.
- For the fallback: `pip install homeharvest`.

## Full on-demand run
See `run.sh` (fetch → score → print board + timing). Then deliver + persist:
1. Post the `match.py` board + `timing.py` runway to Slack **#housing-updates
   (channel id `C0B9JHL9NE9`) via the Slack MCP** — the cloud webhook is blocked,
   and MCP posts to the exact channel id with no secret in the repo.
2. Commit only the real-data state: `git add history/<DATE>.json seen.json
   watchlist.json && git commit -m "house-hunt: board snapshot <DATE>" && git push`.

## Watchlist intake (interactivity)
Reply in a listing's Slack thread and apply one command per reply, then re-save:
- `track <address>` → `watchlist.json` (captures list price now)
- `mute <address>`  → `mutes.json`
- `note <address> "…"` → attach a note

## When we outgrow free
Swap the RentCast call for a paid tier (or ATTOM) writing the same `raw/*.json`
shape — nothing downstream changes. A remote MCP wrapping the API would also let
the *cloud* routine fetch directly; until then, fetch stays local.
