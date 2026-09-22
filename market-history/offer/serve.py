#!/usr/bin/env python3
"""Serve offer/ locally, and let the pages WRITE favourites back to the repo.

    python3 offer/serve.py            # http://localhost:8000
    python3 offer/serve.py --port 8731

WHY THIS EXISTS. There is no database and no backend; the published site is static
files on GitHub Pages, which can never write anything. But a favourite is worth keeping
properly -- it should survive a cleared cache, follow you to the phone, be visible in
git history, and be readable by anything else we build. localStorage does none of that.

So: favourites and notes are written HERE, on the laptop, straight into
offer/favourites.json and offer/notes.json, which get committed like every other piece
of state in this repo. The published site reads those files and is simply read-only --
no star buttons, no editable notes. Write at the desk, read anywhere.

The trade: you cannot star a house from your phone at a viewing. That was the one thing
the Cloudflare-Worker plan in docs/spikes/persistence.md bought, and it costs a vendor,
a deployment and a secret. This costs a file. If phone-writing turns out to matter, that
spike is still there.

Bound to localhost only -- this writes to your working tree, so it is not for sharing.
"""
import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 256 * 1024

# TWO stores, deliberately separate files.
#   favourites.json  the shortlist -- houses you are tracking right now
#   notes.json       what you thought when you stood in one
#
# They are split because they have different lifetimes. A favourite is a live interest
# and comes off the list when the house is gone; a note is something you learned, and it
# stays valuable long after the house sold to someone else -- often MORE valuable, since
# a sold house with your reaction attached is evidence about what you actually want.
# Nesting notes inside favourites would delete that the moment you un-starred something.
# Both are keyed by the same house key, so they join.
STORES = {
    "favourites": (os.path.join(HERE, "favourites.json"), "favourites", list),
    "notes":      (os.path.join(HERE, "notes.json"),      "notes",      dict),
}


# This server is threaded, and a save is read-modify-write. Two edits landing in the
# same instant -- which the notes page does, since every card debounces independently --
# had both threads read the file, each apply only its own change, and each write back:
# last writer won and the other note vanished. They also raced on one shared temp path.
# One lock around the whole read-modify-write closes both.
LOCK = threading.Lock()


def load(store):
    path, root, kind = STORES[store]
    if not os.path.exists(path):
        return {root: kind()}
    try:
        with open(path) as f:
            d = json.load(f)
        d.setdefault(root, kind())
        return d
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ! {path} is unreadable ({e}); refusing to overwrite it", file=sys.stderr)
        raise


def save(store, d):
    """Write via a temp file and replace, so a crash mid-write cannot leave a truncated
    file -- this is the only copy and it is meant to be committed."""
    path = STORES[store][0]
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def which(path):
    return "notes" if path.startswith("/api/notes") else "favourites"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/"):
            # the pages use this to decide whether to show any editing controls at all
            try:
                return self._json({"writable": True, **load(which(self.path))})
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        store = which(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json({"error": "too large"}, 413)
            req = json.loads(self.rfile.read(n) or b"{}")
            key = (req.get("key") or "").strip().lower()
            if not key:
                return self._json({"error": "key required"}, 400)
            action = req.get("action")

            with LOCK:
                d = load(store)

                if store == "notes":
                    notes = d["notes"]
                    if action == "remove":
                        notes.pop(key, None)
                    else:
                        row = notes.get(key) or {}
                        # identity is written once and then left alone, so a note keeps saying
                        # which house it was even after the listing is long gone
                        for f in ("address", "town", "zip"):
                            if req.get(f) and not row.get(f):
                                row[f] = req[f]
                        for f in ("visit", "liked", "disliked", "note"):
                            if f in req:
                                row[f] = req[f]
                        row["updated"] = req.get("updated") or row.get("updated")
                        notes[key] = row
                else:
                    favs = d["favourites"]
                    existing = next((f for f in favs if f.get("key", "").lower() == key), None)
                    if action == "remove":
                        d["favourites"] = [f for f in favs if f.get("key", "").lower() != key]
                    else:
                        row = {"key": key,
                               "address": req.get("address"), "town": req.get("town"),
                               "zip": req.get("zip"), "added": req.get("added"),
                               "ask_when_added": req.get("ask_when_added")}
                        if existing:
                            # a re-star must not reset the date you first saved it
                            row["added"] = existing.get("added") or row["added"]
                            favs[favs.index(existing)] = row
                        else:
                            favs.append(row)
                save(store, d)
            return self._json({"writable": True, **d})
        except Exception as e:
            return self._json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    for name, (path, root, kind) in STORES.items():
        if not os.path.exists(path):
            save(name, {root: kind()})
            print(f"created {os.path.relpath(path)}")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {os.path.relpath(HERE)} at http://localhost:{args.port}")
    print("favourites are WRITABLE here; the published site is read-only")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
