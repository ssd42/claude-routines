# claude-routines

Home for standalone Claude-driven scheduled routines. Each subfolder is one
self-contained routine with its own data and state. Intentionally separate from
any production repo — scheduled jobs get write access **here only**, so their
blast radius is limited to toy data and never touches prod or triggers deploys.

## Routines
| folder | what |
|--------|------|
| [`bracket-challenge/`](bracket-challenge/) | daily provisional leaderboard for the WC2026 bracket-challenge friend league |
