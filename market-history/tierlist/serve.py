#!/usr/bin/env python3
"""Local tier-list editor for the market-history target towns.

Serves tierlist.html, feeds it the towns from ../zips.json, and writes every
change straight back to tiers.json — that file is the deliverable.

    python3 serve.py            # -> http://127.0.0.1:8777

Scratch tool: not part of the aggregate.py pipeline, not scheduled, untracked.
zips.json is read-only here; this never writes back to it.
"""

import datetime
import http.server
import json
import os
import pathlib
import sys
import threading
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
ZIPS = HERE.parent / "zips.json"
OUT = HERE / "tiers.json"
PORT = int(os.environ.get("TIERLIST_PORT", "8777"))

# The S→F ramp is a ranking. "unknown" is NOT its bottom rung — it means "no read
# on this town yet", which is why it sits off the ramp here and in the UI.
RAMP = ["S", "A", "B", "C", "D", "F"]
TIERS = RAMP + ["unknown"]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    # ── routes ──────────────────────────────────────────────
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/tierlist.html"
        if self.path == "/towns.json":
            return self._send(json.loads(ZIPS.read_text()))
        if self.path == "/tiers.json":
            saved = json.loads(OUT.read_text()) if OUT.exists() else None
            return self._send(saved)
        return super().do_GET()

    def do_POST(self):
        if self.path != "/save":
            return self.send_error(404, "no such endpoint")
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            path = write_tiers(body.get("tiers", {}))
        except Exception as e:  # keep the editor alive; surface it in the UI
            return self._send({"ok": False, "error": str(e)}, code=500)
        return self._send({"ok": True, "file": path.name})

    # ── helpers ─────────────────────────────────────────────
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


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_tiers(tiers):
    """Write tiers.json atomically — this file is the point of the exercise."""
    ordered = {t: list(tiers.get(t, [])) for t in TIERS}
    ordered["unranked"] = list(tiers.get("unranked", []))
    ranked = sum(len(ordered[t]) for t in RAMP)
    doc = {
        "_doc": (
            "Hand-ranked tiers for the market-history target towns. Authored in "
            "tierlist/tierlist.html (python3 serve.py); rewritten in full on every "
            "edit. Town names match ../zips.json. Order within a tier is meaningful "
            "— best first. Opinion, not data: nothing in aggregate.py reads this."
        ),
        "_unknown_rule": (
            "'unknown' is NOT the bottom of the S-F ramp — it means no read on the "
            "town yet, good or bad. Don't sort it below F or fold it into 'unranked' "
            "(which just means not looked at yet). Ranked counts exclude both."
        ),
        "updated": stamp(),
        "source": (
            f"../zips.json — {ranked} ranked, {len(ordered['unknown'])} unknown, "
            f"{len(ordered['unranked'])} unsorted"
        ),
        "tiers": ordered,
    }
    # ensure_ascii=False: this file gets read by a human, not just a parser.
    # Atomic: tiers.json IS the deliverable — a crash mid-write must not truncate it.
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(OUT)
    return OUT


def main():
    if not ZIPS.exists():
        sys.exit(f"can't find {ZIPS} — run this from market-history/tierlist/")
    url = f"http://127.0.0.1:{PORT}/"
    n = len(json.loads(ZIPS.read_text())["towns"])
    print(f"tier list  {url}")
    print(f"  {n} towns from {ZIPS.name}")
    print(f"  every edit writes {OUT}")
    print("  ctrl-c to stop\n")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\nstopped. {OUT} holds your tiers.")


if __name__ == "__main__":
    main()
