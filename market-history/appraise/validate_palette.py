"""Port of the dataviz skill's palette validator (no node on this machine).

Same maths, same thresholds: OKLab DeltaE x100, Machado-Oliveira-Fernandes 2009
severity-1.0 CVD simulation, OKLCH lightness band and chroma floor, WCAG contrast.
Run it rather than reasoning about whether a palette is colourblind-safe.

  python3 validate_palette.py "#8c2f2a,#2c6459,#a8631c" --mode light --surface "#f7f4ee"
"""
import argparse, math, sys

BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR, CVD_TARGET, CVD_FLOOR, NORMAL_FLOOR, CONTRAST_MIN = 0.10, 8.0, 6.0, 15.0, 3.0
MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
               [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
               [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
               [0.004733, 0.691367, 0.303900]],
}
s2l = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def lin(h):
    h = h.strip().lstrip("#")
    return [s2l(int(h[i:i+2], 16) / 255) for i in (0, 2, 4)]
def oklab_from_lin(rgb):
    r, g, b = rgb
    l = (0.4122214708*r + 0.5363325363*g + 0.0514459929*b) ** (1/3)
    m = (0.2119034982*r + 0.6806995451*g + 0.1073969566*b) ** (1/3)
    s = (0.0883024619*r + 0.2817188376*g + 0.6299787005*b) ** (1/3)
    return [0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
            1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
            0.0259040371*l + 0.7827717662*m - 0.8086757660*s]
def oklch(h):
    L, a, b = oklab_from_lin(lin(h)); return L, math.hypot(a, b)
def rel_lum(h):
    r, g, b = lin(h); return 0.2126*r + 0.7152*g + 0.0722*b
def contrast(a, b):
    hi, lo = sorted([rel_lum(a), rel_lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)
def simulate(h, kind):
    r, g, b = lin(h); M = MACHADO[kind]
    return [min(1, max(0, M[i][0]*r + M[i][1]*g + M[i][2]*b)) for i in range(3)]
def delta_e(h1, h2, kind=None):
    a = oklab_from_lin(simulate(h1, kind) if kind else lin(h1))
    b = oklab_from_lin(simulate(h2, kind) if kind else lin(h2))
    return 100 * math.dist(a, b)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("palette"); ap.add_argument("--mode", default="light")
    ap.add_argument("--surface"); ap.add_argument("--pairs", default="adjacent")
    a = ap.parse_args()
    pal = [c.strip() for c in a.palette.split(",") if c.strip()]
    surface = a.surface or ("#fcfcfb" if a.mode == "light" else "#1a1a19")
    lo, hi = BAND[a.mode]
    pairs = ([(i, i+1) for i in range(len(pal)-1)] if a.pairs == "adjacent"
             else [(i, j) for i in range(len(pal)) for j in range(i+1, len(pal))])
    ok = True
    print(f"\n  palette {pal}   mode={a.mode}  surface={surface}\n")

    off = [(c, round(oklch(c)[0], 3)) for c in pal if not (lo <= oklch(c)[0] <= hi)]
    ok &= not off
    print(f"  1 lightness band {lo}-{hi} : {'PASS' if not off else 'FAIL ' + str(off)}")

    low = [(c, round(oklch(c)[1], 3)) for c in pal if oklch(c)[1] < CHROMA_FLOOR]
    ok &= not low
    print(f"  2 chroma floor {CHROMA_FLOOR}     : {'PASS' if not low else 'FAIL ' + str(low)}")

    con = [(c, round(contrast(c, surface), 2)) for c in pal if contrast(c, surface) < CONTRAST_MIN]
    print(f"  3 contrast vs surface   : {'PASS' if not con else 'WARN ' + str(con)}"
          + ("" if not con else "  -> needs visible labels or a table view"))

    for kind in ("protan", "deutan"):
        worst = min(((delta_e(pal[i], pal[j], kind), pal[i], pal[j]) for i, j in pairs),
                    default=(99, "", ""))
        v = worst[0]
        st = "PASS" if v >= CVD_TARGET else ("FLOOR" if v >= CVD_FLOOR else "FAIL")
        ok &= v >= CVD_FLOOR
        print(f"  4 CVD {kind:<7} dE>={CVD_TARGET} : {st} worst {v:.1f}  {worst[1]}<->{worst[2]}")

    worst = min(((delta_e(pal[i], pal[j]), pal[i], pal[j]) for i, j in pairs), default=(99, "", ""))
    ok &= worst[0] >= NORMAL_FLOOR
    print(f"  4b normal vision dE>={NORMAL_FLOOR}: "
          f"{'PASS' if worst[0] >= NORMAL_FLOOR else 'FAIL'} worst {worst[0]:.1f}  {worst[1]}<->{worst[2]}")

    print(f"\n  -> {'ALL CHECKS PASS' if ok else 'FAILED - fix the marked checks'}\n")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
