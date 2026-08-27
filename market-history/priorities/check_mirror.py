#!/usr/bin/env python3
"""Prove priorities.html's curve pictures still match the real model.

The page draws each factor's scoring curve from its OWN copy of the maths, because
you cannot sample a function out of a source file without running it. That copy can
drift from ../offer/engine.js, and a drifted curve is worse than no curve — it is a
confident picture of a model that no longer exists.

serve.py fingerprints the scored region, so the page can say "something changed."
This says WHICH curve is now wrong:

    python3 check_mirror.py         # -> exit 0 if every curve agrees

It works by evaluating BOTH versions of every rule over its whole domain and
comparing point by point, using JavaScriptCore (`osascript -l JavaScript`, on every
mac) so the engine.js arrow functions run as themselves rather than being
re-implemented a third time. Local-only, like the editor it guards.
"""

import json
import pathlib
import re
import subprocess
import sys

import serve

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "priorities.html"

# Categorical factors have no domain to sweep, so each bar the page draws is
# checked against the engine's answer for the input that bar claims to describe.
PROBES = {
    "tier":  [["S", "S"], ["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"], ["F", "F"]],
    "type":  [["house", "house"], ["multi", "multi"], ["condo / attached", "condo"]],
    "beds":  [["2", 2], ["3", 3], ["4", 4], ["5+", 5]],
    "baths": [["1", 1], ["1.5", 1.5], ["2", 2], ["2.5+", 2.5]],
    "flood": [["outside a flood zone", 0], ["high-risk zone (A/AE/V/VE)", 1]],
}


def strip_comments(t: str) -> str:
    """Drop // comments without touching strings or regex literals."""
    out, i, quote = [], 0, None
    while i < len(t):
        c = t[i]
        if quote:
            out.append(c)
            if c == "\\":
                out.append(t[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and t[i + 1 : i + 2] == "/":
            j = t.find("\n", i)
            i = len(t) if j < 0 else j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def engine_curves():
    """{key: the `s:` arrow function, verbatim} out of engine.js."""
    out = {}
    for f in serve.read_model()["factors"]:
        body = strip_comments(f["src"]).rstrip()
        # the LAST top-level `s:` — `get:` can sit on the same line ahead of it
        m = None
        for mm in re.finditer(r"[,{]\s*s:\s*", body):
            m = mm
        if not m or not body.endswith("}"):
            sys.exit(f"can't find the scoring rule for `{f['k']}` in engine.js")
        out[f["k"]] = body[m.end() : -1].strip().rstrip(",")
    return out


def page_section(a: str, b: str) -> str:
    js = PAGE.read_text().split('<script>\n"use strict";', 1)[1].rsplit("</script>", 1)[0]
    i = js.index(a)
    return js[i : js.index(b, i)]


HARNESS = r"""
var bad = 0, lines = [];
const cl = x => Math.max(0, Math.min(1, x));
for (const k of Object.keys(PLAIN)) {
  const p = PLAIN[k];
  if (!ENGINE[k]) { lines.push("GONE   " + k + " — the page draws a factor engine.js no longer has"); bad++; continue; }
  let ef;
  try { ef = eval("(" + ENGINE[k] + ")"); }
  catch (e) { lines.push("BROKEN " + k + " — " + e.message); bad++; continue; }
  if (p.curve) {
    const [lo, hi] = p.curve.d;
    let worst = 0, at = null;
    for (let i = 0; i <= 400; i++) {
      const v = lo + (hi - lo) * i / 400;
      const d = Math.abs(cl(p.curve.f(v)) - cl(ef(v)));
      if (d > worst) { worst = d; at = v; }
    }
    if (worst > 1e-9) { lines.push("DRIFT  " + k + " — off by " + worst.toFixed(4) + " at " + at); bad++; }
    else lines.push("ok     " + k);
  } else if (p.bars) {
    const wrong = [];
    for (const [lbl, inp] of (PROBE[k] || []))
      { const mine = (p.bars.find(b => b[0] === lbl) || [null, null])[1];
        if (mine === null || Math.abs(mine - cl(ef(inp))) > 1e-9)
          wrong.push(lbl + ": page says " + mine + ", engine says " + cl(ef(inp))); }
    if (!PROBE[k]) wrong.push("no probes defined — add it to PROBES in check_mirror.py");
    else if (p.bars.length !== PROBE[k].length) wrong.push("page draws " + p.bars.length + " bars, " + PROBE[k].length + " probed");
    if (wrong.length) { lines.push("DRIFT  " + k + " — " + wrong.join("; ")); bad++; }
    else lines.push("ok     " + k);
  } else { lines.push("BLANK  " + k + " — no curve and no bars to check"); }
}
for (const k of Object.keys(ENGINE))
  if (!PLAIN[k]) { lines.push("MISSING " + k + " — engine.js scores it, the page has no note for it"); bad++; }
lines.join("\n") + "\n@@" + bad
"""


def main():
    eng = engine_curves()
    script = (
        page_section("const clamp =", "const PLAIN = {")
        + page_section("const PLAIN = {", "/* The words.")
        + f"\nconst ENGINE = {json.dumps(eng)};\nconst PROBE = {json.dumps(PROBES)};\n"
        + HARNESS
    )
    tmp = HERE / ".check_mirror.js"
    tmp.write_text(script)
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", str(tmp)],
                           capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("needs osascript (macOS) — this is a local-only check")
    finally:
        tmp.unlink(missing_ok=True)
    if r.returncode:
        sys.exit(f"JavaScriptCore failed:\n{r.stderr}")
    body, _, n = r.stdout.strip().rpartition("@@")
    print(body.strip())
    n = int(n)
    print(f"\n{len(eng)} factors checked — "
          + ("every picture matches engine.js." if not n else f"{n} PROBLEM(S) above."))
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
