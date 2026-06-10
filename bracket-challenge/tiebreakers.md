# WC2026 group-stage tiebreakers (official)

Source: ESPN / FIFA regulations, May 2026. We score finishing **position**, so
the order teams finish in matters. Reference only — see note at bottom on what
our daily job actually computes.

## Ranking teams within a group (equal on points)
Applied in order:
1. Points in matches **between the tied teams**
2. Goal difference in matches **between the tied teams**
3. Goals scored in matches **between the tied teams**
   → if some teams remain tied, re-apply 1–3 to just those teams
4. Goal difference in **all** group matches
5. Goals scored in **all** group matches
6. Team conduct (fair-play) score across all group matches
7. FIFA world ranking  ← we have this in `fifa_rankings.json`

## Ranking the best third-place teams (8 of 12 advance)
1. Points
2. Goal difference
3. Goals scored
4. Team conduct score
5. FIFA world ranking

## Team conduct (fair-play) score
- Yellow card: **−1**
- Indirect red (2nd yellow): **−3**
- Direct red: **−4**
- Yellow + direct red: **−5**
(cards to players AND officials count)

## What our job actually computes
Criteria 1–3 (head-to-head) need match-by-match results, and criterion 6
(conduct) needs card data — neither is in a standings table. So:

- **Mid-group (provisional board):** approximate order = points → overall GD →
  overall goals → **FIFA ranking** → name. Honest best-effort from table data.
- **Group complete (real points):** take the **agreed final order** via 2-of-3
  source consensus — FIFA has already applied the full chain, so we don't
  reimplement head-to-head or conduct. Consensus = exact.
