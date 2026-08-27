#!/usr/bin/env python3
"""Local editor for what you want in a house — the HS preference sheet.

Serves priorities.html, feeds it the LIVE housing-score model scraped straight out
of ../offer/engine.js, and writes every change back to priorities.json.

    python3 serve.py            # -> http://127.0.0.1:8778

Why it reads engine.js instead of holding its own copy of the model: the whole
point of the page is "show me everything you use to score a house." A hand-kept
list would drift the first time a factor's weight changed, and it would drift
SILENTLY -- the page would look complete while quietly hiding a factor. So the
weights, labels and the verbatim source of every scoring rule come out of the real
file, and anything new in engine.js shows up here on the next reload, flagged as
having no plain-English note yet.

priorities.json is the deliverable: an agent reads it as context when tuning the
weights in engine.js. Nothing reads it automatically -- it is a statement of taste,
and taste gets applied by hand.

Scratch tool: not part of the aggregate.py pipeline, not scheduled.
"""

import datetime
import hashlib
import http.server
import json
import os
import pathlib
import re
import sys
import threading
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
ENGINE = HERE.parent / "offer" / "engine.js"
OUT = HERE / "priorities.json"
PORT = int(os.environ.get("PRIORITIES_PORT", "8778"))

STANCES = ["gate", "big", "some", "little", "skip"]


# ══ pulling the model out of engine.js ═══════════════════════════════════════
# A real parse, not a line regex: every entry is captured by brace-balance so the
# page can show the RULE verbatim, not just its weight. Strings and // comments are
# skipped while balancing. (Checked against the current file: no braces hide inside
# a string or a regex literal, and no regex contains a "//" that would read as a
# comment -- `a\/?c` is the closest it gets.)

def _entries(block: str):
    """Yield (source_text, disabled) for each top-level {...} in an array body."""
    i, n = 0, len(block)
    while i < n:
        if block[i] == "{":
            start, depth, j = i, 0, i
            quote = None
            while j < n:
                c = block[j]
                if quote:
                    if c == "\\":
                        j += 2
                        continue
                    if c == quote:
                        quote = None
                elif c in "\"'":
                    quote = c
                elif c == "/" and j + 1 < n and block[j + 1] == "/":
                    j = block.find("\n", j)
                    if j < 0:
                        break
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        text = block[start : j + 1]
                        # commented-out entry? the line it opens on starts with //
                        ls = block.rfind("\n", 0, start) + 1
                        yield text, block[ls:start].strip().startswith("//")
                        i = j + 1
                        break
                j += 1
            else:
                break
            if j >= n:
                break
        else:
            i += 1


def _array(src: str, name: str) -> str:
    """The body of `const NAME = [ ... ];` — bracket-balanced, so a `]` in a
    regex or a string inside the array can't truncate it early."""
    m = re.search(rf"const\s+{name}\s*=\s*\[", src)
    if not m:
        sys.exit(f"{ENGINE.name}: can't find `const {name} = [` — did the model move?")
    i, depth, quote = m.end() - 1, 0, None
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "/" and src[i + 1 : i + 2] == "/":
            i = src.find("\n", i)
            if i < 0:
                break
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return src[m.end() : i]
        i += 1
    sys.exit(f"{ENGINE.name}: `const {name} = [` never closes.")


def _field(text: str, pat: str, cast=str, default=None):
    m = re.search(pat, text)
    return cast(m.group(1)) if m else default


def read_model():
    """Scrape engine.js for the whole housing score. Raises loudly if it can't —
    a silently-empty model would make this page lie about what it covers."""
    src = ENGINE.read_text()

    factors = []
    for text, _ in _entries(_array(src, "HS_FACTORS")):
        k = _field(text, r'k:"([^"]+)"')
        if not k:
            continue
        # `s:` is the scoring curve — everything from `s:` to the end of the entry.
        rule = text.split("\n   s:", 1)[-1] if "\n   s:" in text else text
        factors.append({
            "k": k,
            "w": _field(text, r"w:\s*(\d+)", int, 0),
            "label": _field(text, r'label:"([^"]*)"', str, k),
            "src": text.strip(),
            "rule": rule.strip(),
        })

    def points(name):
        out = []
        for text, off in _entries(_array(src, name)):
            k = _field(text, r'k:"([^"]+)"')
            if not k:
                continue
            out.append({
                "k": k,
                "pts": _field(text, r"pts:\s*([+-]?\d+)", int, 0),
                "label": _field(text, r'label:"([^"]*)"', str, k),
                "match": (_field(text, r"re:\s*(/.*/[a-z]*)")
                          or (_field(text, r"test:\s*(.+?),?\s*}\s*$") or "").strip() or None),
                "src": text.strip(),
                "disabled": off,
            })
        return out

    flavour = points("HS_FLAVOUR")
    watched = points("HS_WATCHED")
    if not factors or not flavour:
        sys.exit(f"{ENGINE.name}: parsed 0 factors or 0 flavour terms — refusing to "
                 "serve a model that would look complete and be empty.")

    # The fingerprint covers the whole scored region, so ANY edit to the model —
    # a weight, a curve, a new factor — invalidates a saved sheet and the page can
    # say "the score changed since you last ruled on this."
    a = src.index("const HS_FACTORS")
    b = src.index("function hsFor")
    fp = hashlib.sha256(src[a:b].encode()).hexdigest()[:12]

    return {
        "factors": factors,
        "flavour": flavour,
        "watched": watched,
        "cap": _field(src, r"HS_FLAVOUR_CAP\s*=\s*(\d+)", int, 12),
        "base_scale": _field(src, r"base\s*\*\s*([\d.]+)", float, 0.88),
        "total_weight": sum(f["w"] for f in factors),
        "fingerprint": fp,
        "source": f"../offer/engine.js ({ENGINE.stat().st_size // 1024}kb)",
        "read_at": stamp(),
    }


# ══ the deliverable ══════════════════════════════════════════════════════════

def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_sheet(body, model):
    """Rewrite priorities.json in full, atomically. This file IS the point."""
    stances = {}
    for k, v in (body.get("stances") or {}).items():
        if not isinstance(v, dict):
            continue
        s = v.get("stance")
        row = {
            "stance": s if s in STANCES else None,
            "line": (v.get("line") or "").strip(),
            "note": (v.get("note") or "").strip(),
        }
        if row["stance"] or row["line"] or row["note"]:
            stances[k] = row

    wants = [
        {
            "name": (w.get("name") or "").strip(),
            "stance": w.get("stance") if w.get("stance") in STANCES else None,
            "note": (w.get("note") or "").strip(),
        }
        for w in (body.get("wants") or [])
        if (w.get("name") or "").strip()
    ]
    trades = [
        {"a": t.get("a"), "b": t.get("b"), "pick": t.get("pick"), "at": t.get("at")}
        for t in (body.get("trades") or [])
        if t.get("a") and t.get("b")
    ]

    known = ([f["k"] for f in model["factors"]]
             + ["w:" + f["k"] for f in model["flavour"]]
             + ["o:" + w["k"] for w in model["watched"]])
    ruled = sum(1 for k in known if stances.get(k, {}).get("stance"))

    doc = {
        "_doc": (
            "What the owner actually wants in a house, factor by factor. Authored in "
            "priorities/priorities.html (python3 serve.py); rewritten in full on every "
            "edit. Keys match the housing-score model in offer/engine.js: a bare key is "
            "an HS_FACTORS key, 'w:' prefixes an HS_FLAVOUR word, 'o:' prefixes an "
            "HS_WATCHED signal."
        ),
        "_how_to_read": (
            "One question per thing: how much does missing it cost. big/some/little are "
            "three rungs of that one magnitude and DO map to weight. The other two are not "
            "on that scale: gate = a deal-breaker however good the rest is, which is a "
            "FILTER — no weight reproduces 'I walk', so do not implement it as a big "
            "number. skip = take it out of the score, which is absence, not the smallest "
            "weight. A factor with no stance has NOT been ruled on — that is not "
            "the same as 'doesn't matter', and it must never be read as a zero. "
            "POLARITY: for a term with negative points (a pool, as-is, wall AC, a relist) the "
            "same five keys mean the avoidance side of the same scale — 'gate' is \"won't "
            "touch it\", 'big' is \"counts hard against it\". Never read 'big' on a penalty "
            "as wanting the thing."
        ),
        "_for_the_agent": (
            "Read this before changing weights or curves in offer/engine.js. 'line' is "
            "the owner's own threshold in his words and usually contradicts the curve on "
            "purpose — that gap is the ask. 'wants' are things the score does not measure "
            "yet and each one is a request to go find data for it. 'trades' are forced "
            "either/or answers; they are the evidence for RELATIVE weight, and are worth "
            "more than the stances when the two disagree — a null 'pick' means he skipped "
            "that pair, which is not a tie and carries no preference. Never edit by hand — "
            "it is the owner's voice, not yours."
        ),
        "updated": stamp(),
        "model_fingerprint": model["fingerprint"],
        "model_source": (
            f"offer/engine.js — {len(model['factors'])} measured factors "
            f"({model['total_weight']} weight), {len(model['flavour'])} words, "
            f"{len([w for w in model['watched'] if not w['disabled']])} watched"
        ),
        "ruled": f"{ruled} of {len(known)} scored things have a stance",
        "stances": stances,
        "wants": wants,
        "trades": trades,
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(OUT)
    return doc


# ══ server ═══════════════════════════════════════════════════════════════════

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/priorities.html"
        if self.path == "/model.json":
            # Re-read every load: edit engine.js, reload the page, see it.
            try:
                return self._send(read_model())
            except SystemExit as e:
                return self._send({"error": str(e)}, code=500)
        if self.path == "/priorities.json":
            return self._send(json.loads(OUT.read_text()) if OUT.exists() else None)
        return super().do_GET()

    def do_POST(self):
        if self.path != "/save":
            return self.send_error(404, "no such endpoint")
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            doc = write_sheet(body, read_model())
        except Exception as e:  # keep the editor alive; surface it in the UI
            return self._send({"ok": False, "error": str(e)}, code=500)
        return self._send({"ok": True, "file": OUT.name, "ruled": doc["ruled"]})

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "POST /save" in (fmt % args):
            print(f"  saved -> {OUT.name}  {stamp()}")


def main():
    if not ENGINE.exists():
        sys.exit(f"can't find {ENGINE} — run this from market-history/priorities/")
    m = read_model()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"what you want  {url}")
    print(f"  {len(m['factors'])} measured factors ({m['total_weight']} weight), "
          f"{len(m['flavour'])} words, {len(m['watched'])} watched "
          f"— live from {ENGINE.name}")
    print(f"  every edit writes {OUT}")
    print("  ctrl-c to stop\n")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\nstopped. {OUT} holds what you want.")


if __name__ == "__main__":
    main()
