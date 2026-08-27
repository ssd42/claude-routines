# priorities — what you want in a house, and where you'd bend

A single local page that shows you **everything the housing score (HS) looks at**,
and lets you say how much each one actually costs you to miss.

```bash
cd market-history/priorities
python3 serve.py            # -> http://127.0.0.1:8778, opens itself
```

Every change saves straight to **`priorities.json`** next to this file. That file is
the deliverable — it's what an agent reads before touching a weight or a curve in
`offer/engine.js`.

## What it's for

Three things, in order:

1. **See what's actually in the score.** All 14 measured things, the 10 words we
   mine out of the listing copy, and the 2 things our own daily scrape watches —
   each with what it means, how loud it currently is, and a picture of the rule.
2. **Say where you'd bend.** One question per thing: how much does missing it cost?
   *Won't budge · Really want · Somewhat want · Barely · Doesn't matter* — plus your
   own threshold in your own words.
3. **Say what's missing.** Anything you keep noticing at open houses that nothing
   above measures goes on the bench at the bottom, and becomes a request to go find
   data for it.

Plus a forced **one-or-the-other** at the end. The stances say what you'd give up;
those say what you'd give it up *for*, which is the part that actually sets weights.

## Two of the five rungs aren't weights

*Really want · Somewhat want · Barely* are three strengths of one question, and they
do map to weight. The other two don't: **won't budge** is a filter — no amount of
weight reproduces "I walk" — and **doesn't matter** is absence, not the smallest
weight. Nothing here asks you to rank 26 things against each other; each is judged on
its own. A row left blank means **not decided**, never a zero.

## Where the numbers come from

Nothing here is hand-copied. `serve.py` parses `../offer/engine.js` on every page
load and pulls out the real weights, the real word list and the verbatim source of
every rule, so:

- change a weight in `engine.js` → reload → the page shows the new one;
- add a factor → it appears here flagged **new**, waiting for a plain-English note;
- the whole scored region is fingerprinted, so if it changed since you last filled
  this in, the page says so instead of quietly comparing answers to a different
  question.

The one exception is the **curve pictures**: you can't sample a function out of a
source file without running it, so the page keeps its own copy of the maths for
drawing. That copy can drift, so the real rule sits one click away under every
chart, and:

```bash
python3 check_mirror.py     # runs both versions of all 14 rules and compares
```

fails loudly and names the factor if a picture ever stops matching the model.

## Files

| file | what |
|------|------|
| `serve.py` | the little server: reads the live model, writes your answers |
| `priorities.html` | the page — one file, no build, no dependencies |
| `priorities.json` | **the deliverable** — your answers, rewritten on every edit |
| `check_mirror.py` | proves the drawn curves still match `offer/engine.js` |

Scratch tool: not part of the `aggregate.py` pipeline, not scheduled. Nothing here
writes back to the model — taste gets applied by hand, deliberately.
