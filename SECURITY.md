# Security

**This repository is public.** Anything committed here is world-readable, and
git history preserves it even if a later commit removes it.

## Never commit secrets
No webhook URLs, API tokens, keys, cookies, or auth headers in any tracked file
— including code, JSON config, markdown, fixtures, or commit messages.

Secrets live **outside** the repo, set on the **Claude routine** (the remote
scheduled-agent server) and read at run time from environment variables. They
never travel through this repo or a local checkout:

| secret | env var | notes |
|--------|---------|-------|
| house-hunt Slack incoming webhook | `HOUSE_HUNT_SLACK_WEBHOOK` | lives only on the routine; `job.json` stores only the channel id |

Config files reference secrets **by env-var name**, never by value.

`.gitignore` blocks `.env*`, `*secret*`, `*webhook*`, `*.key`, `*.pem`, and
similar as a backstop — but the policy is "never write a secret into a repo file
in the first place," not "rely on the ignore list."

## Before every commit
Review the staged diff (`git diff --cached`) for anything secret-shaped
(`https://hooks.slack.com/...`, long random tokens). If in doubt, don't commit.

## If a secret is exposed
Treat it as compromised:
1. **Rotate it immediately** (regenerate the webhook/token at the source).
2. Scrub it from git history (e.g. `git filter-repo`) — deleting the line in a
   new commit is **not** enough; the old commit still contains it.
