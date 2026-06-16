#!/usr/bin/env bash
# On-demand house-hunt run (LOCAL — needs a residential IP; the cloud sandbox
# can't fetch listings). Fetches real listings, scores them, and prints the
# board + timing runway. Delivery to Slack (channel C0B9JHL9NE9 via Slack MCP)
# and committing the day's snapshot are done after this — see README "On-demand".
#
#   ./run.sh                 # RentCast if RENTCAST_API_KEY set, else HomeHarvest;
#                            # pulls recently-sold comps by default (builds the dataset)
#   ./run.sh --no-sold       # skip the recently-sold comp pull (faster)
set -euo pipefail
cd "$(dirname "$0")"
DATE="$(TZ=America/New_York date +%F)"

echo "▶ fetching listings…"
python3 fetch.py "$@"

echo
echo "▶ scoring → canonical board (match.py --board) …"
python3 match.py "$DATE" --board

echo
echo "▶ timing runway (timing.py) …"
python3 timing.py "$DATE"

echo
echo "✓ done. Post the board ABOVE (match.py --board output) to Slack"
echo "  #housing-updates (C0B9JHL9NE9) via the Slack MCP — VERBATIM, no reformatting."
echo "  Then commit:  git add history/$DATE.json seen.json watchlist.json"
