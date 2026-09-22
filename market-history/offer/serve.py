#!/usr/bin/env python3
"""Serve offer/ locally, and let the pages WRITE favourites back to the repo.

    python3 offer/serve.py            # http://localhost:8000
    python3 offer/serve.py --port 8731

WHY THIS EXISTS. There is no database and no backend; the published site is static
files on GitHub Pages, which can never write anything. But a favourite is worth keeping
properly -- it should survive a cleared cache, follow you to the phone, be visible in
git history, and be readable by anything else we build. localStorage does none of that.

So: favourites are written HERE, on the laptop, straight into offer/favourites.json,
which gets committed like every other piece of state in this repo. The published site
reads that same file and is simply read-only -- star buttons do not appear there. Star
at the desk, browse anywhere.

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
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FAVS = os.path.join(HERE, "favourites.json")
MAX_BODY = 64 * 1024


def load():
    if not os.path.exists(FAVS):
        return {"favourites": []}
    try:
        with open(FAVS) as f:
            d = json.load(f)
        d.setdefault("favourites", [])
        return d
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ! {FAVS} is unreadable ({e}); refusing to overwrite it", file=sys.stderr)
        raise


def save(d):
    """Write via a temp file and replace, so a crash mid-write cannot leave a truncated
    favourites file -- this is the only copy and it is meant to be committed."""
    tmp = FAVS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, FAVS)


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
        if self.path.startswith("/api/favourites"):
            # the page uses this to decide whether to show star buttons at all
            try:
                return self._json({"writable": True, **load()})
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/favourites"):
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json({"error": "too large"}, 413)
            req = json.loads(self.rfile.read(n) or b"{}")
            d = load()
            favs = d["favourites"]
            key = (req.get("key") or "").strip().lower()
            if not key:
                return self._json({"error": "key required"}, 400)

            if req.get("action") == "remove":
                d["favourites"] = [f for f in favs if f.get("key", "").lower() != key]
            else:
                existing = next((f for f in favs if f.get("key", "").lower() == key), None)
                row = {"key": key,
                       "address": req.get("address"), "town": req.get("town"),
                       "zip": req.get("zip"), "added": req.get("added"),
                       "ask_when_added": req.get("ask_when_added"),
                       "note": req.get("note") or ""}
                if existing:
                    # keep the original added date; a re-star should not reset the history
                    row["added"] = existing.get("added") or row["added"]
                    if not row["note"]:
                        row["note"] = existing.get("note") or ""
                    favs[favs.index(existing)] = row
                else:
                    favs.append(row)
            save(d)
            return self._json({"writable": True, **d})
        except Exception as e:
            return self._json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if not os.path.exists(FAVS):
        save({"favourites": []})
        print(f"created {os.path.relpath(FAVS)}")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {os.path.relpath(HERE)} at http://localhost:{args.port}")
    print("favourites are WRITABLE here; the published site is read-only")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
