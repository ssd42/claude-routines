"""Fetch listing photos in two passes, so looking at ALL of them stays affordable.

    python3 photos.py                 # survey: every photo, small
    python3 photos.py --detail 7 9 22 # re-fetch just those, full size

WHY TWO PASSES
--------------
Vision cost scales with PIXEL COUNT, so resolution is the whole bill. Measured on a
real listing: the rdcpix URL the feed hands back renders at 960x640 (614k pixels), and
the `-w1024_h768_x2` transform an earlier version of this script hardcoded renders at
1500x1000 (1.5M pixels) -- 2.4x the pixels on EVERY photo, whether or not the photo had
any detail worth resolving. A 19-photo gallery paid that 19 times.

The fix is not "use small images" -- the outlets and the ceiling slopes that changed a
$37k appraisal were only legible because the image was big enough. It is to stop paying
detail rates for the establishing shots:

  pass 1  every photo at 640px  -- enough to see what a room IS and whether it matters
  pass 2  the 3-6 that matter, at full size -- enough to read an outlet or a data plate

That is cheaper than uniform full-size AND it makes SKILL.md's "view every photo before
pricing" rule affordable, which uniform full-size quietly discouraged.

WHAT TO PULL AT FULL SIZE
-------------------------
Kitchen and baths (finish age), the utility/mechanical room (boiler, panel, water heater,
water staining), any room with visible outlets, and anything the survey pass left you
unsure about. Establishing shots, yards, and empty staged rooms almost never need it.
"""
import argparse, json, re, subprocess, sys, urllib.request
from pathlib import Path

RUN = Path(__file__).resolve().parent / "run"
UA = {"User-Agent": "Mozilla/5.0"}
# rdcpix encodes the render size in the path. Rewriting it asks their origin for a real
# render at that size -- this is NOT client-side upscaling, which is why the big version
# genuinely resolves more detail.
SIZE = re.compile(r"-w\d+_h\d+(_x\d)?")


def at(url, w, h, retina):
    """rdcpix renders at the requested width with _x1, and DOUBLE it with _x2 (capped
    ~1500). Measured on a real listing:

        -w320_h240_x1  ->  320x213  (0.07M px)      -w480_h360_x2  ->   960x640 (0.61M)
        -w640_h427_x1  ->  640x427  (0.27M px)      -w640_h427_x2  ->  1280x853 (1.09M)
                                                    -w1024_h768_x2 -> 1500x1000 (1.50M)

    An earlier version of this file hardcoded _x2 on BOTH passes, so the "640px survey"
    actually pulled 1280x853 -- four times the pixels intended, and it reported the
    requested size rather than the delivered one, so the discrepancy was invisible.
    Survey uses _x1; detail uses _x2. Never trust the requested size: measure."""
    return SIZE.sub(f"-w{w}_h{h}_x{2 if retina else 1}", url.split("?")[0])


def delivered_px(path):
    """Measure what actually arrived. The requested size is a request, not a promise."""
    try:
        out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                             capture_output=True, text=True).stdout
        w = int(re.search(r"pixelWidth: (\d+)", out).group(1))
        h = int(re.search(r"pixelHeight: (\d+)", out).group(1))
        return w * h
    except Exception:
        return 0


def grab(url, dest):
    dest.write_bytes(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=25).read())
    return dest.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", nargs="*", type=int, default=None,
                    help="photo numbers to re-fetch at full size")
    ap.add_argument("--survey-width", type=int, default=640)
    a = ap.parse_args()

    subj = json.loads((RUN / "subject_blind.json").read_text())
    urls = subj.get("photos") or []
    if not urls:
        sys.exit("no photos on this listing")
    out = RUN / "photos"
    out.mkdir(parents=True, exist_ok=True)

    if a.detail:
        w, h, retina, tag, want = 1024, 768, True, "detail", a.detail
    else:
        w, h, retina, tag, want = (a.survey_width, round(a.survey_width * 2 / 3), False,
                                   "survey", range(1, len(urls) + 1))

    got = px = 0
    for i in want:
        if not (1 <= i <= len(urls)):
            print(f"  {i}: out of range (1-{len(urls)})"); continue
        try:
            p = out / f"{i:02d}.jpg"
            grab(at(urls[i - 1], w, h, retina), p)
            got += 1; px += delivered_px(p)   # measured, never assumed
        except Exception as e:
            print(f"  {i}: {type(e).__name__}")

    print(f"{tag}: {got} photo(s), {px/1e6:.1f}M pixels delivered")
    if tag == "survey":
        full = len(urls) * 1_500_000        # every photo at detail size
        print(f"  vs all-at-detail: {full/1e6:.1f}M  ({(1 - px/full)*100:.0f}% less)")
        print(f"  next           : python3 photos.py --detail <numbers>  for the rooms that matter")


if __name__ == "__main__":
    main()
