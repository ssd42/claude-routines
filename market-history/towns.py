#!/usr/bin/env python3
"""towns.py — turn "the towns I care about today" into the zips a fetcher can use.

    import towns
    scope = towns.resolve(zips=None, towns=["Cranford", "Montclair"])
    scope.zips          # {'07016', '07042', '07043'}
    print(scope.describe())

WHY THIS IS NOT A ONE-LINER. Every fetcher in this routine is ZIP-GRAINED — the sales
endpoint and the listing site are both queried by zip — but a person asks for a TOWN, and
the two do not line up in either direction:

  * a town can span several zips. Edison is 08820/08817/08837, Montclair 07042/07043,
    Parsippany-Troy Hills 07054/07034. Ask for the town and miss a zip and you have
    quietly refreshed part of it, which then reads as a complete refresh.
  * a zip can cover several towns. 07006 is Caldwell / North Caldwell / West Caldwell,
    07960 Morristown / Morris Township, 07945 Mendham / Mendham Township, 07508 North
    Haledon / Haledon. There is no way to fetch one without fetching its neighbours.

So a scope is always a SUPERSET of what was asked for, and the extra towns are named
rather than glossed over — `describe()` prints them. That is not a rounding error: those
tag-along towns get real rows written for them and, for on-market, their spells get ended
by the same run. Silently is the wrong way for that to happen.

The towns come out correctly labelled either way, just via different routes. A sale with a
deed behind it takes its town from the municipality on the deed; a scraped listing starts
with the zip's FIRST-LISTED town as a fallback label and is then resolved from its
coordinates by relabel_listings.py. Neither relies on a zip meaning one town. The
first-wins ordering in zips.json is load-bearing for that fallback — see its
`_zip_label_rule` — so `zip_town` here preserves it.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ZIPS_FILE = os.path.join(HERE, "config", "zips.json")


class Unknown(ValueError):
    """A zip or town name that is not in zips.json. Always fatal to the caller: a typo
    must never pass for a successful refresh of a town nothing touched."""


class Scope:
    """A resolved set of zips, plus what asking for it dragged in."""

    def __init__(self, zips, asked, zip_town):
        self.zips = zips                      # the zips to fetch
        self.asked = asked                    # town names the user actually named
        self.towns = sorted({t for z in zips for t in zip_town[z]})
        self.tagalong = [t for t in self.towns if t not in asked]

    def __bool__(self):
        return bool(self.zips)

    def __contains__(self, z):
        return z in self.zips

    def __len__(self):
        return len(self.zips)

    def __iter__(self):
        return iter(sorted(self.zips))

    def describe(self):
        out = ["SCOPED to %d zip(s): %s" % (len(self.zips), " ".join(sorted(self.zips))),
               "  towns covered: %s" % ", ".join(self.towns)]
        if self.tagalong:
            out.append("  ALSO PULLED IN (they share a zip with what you asked for — the")
            out.append("  fetchers cannot split a zip): %s" % ", ".join(self.tagalong))
        return "\n".join(out)


def load():
    """-> (zip_town, town_zips). zip_town maps a zip to EVERY town in it, first-listed
    first, because that order is the fallback label for scrape-only rows."""
    cfg = json.load(open(ZIPS_FILE))
    zip_town, town_zips = {}, {}
    for t in cfg["towns"]:
        town_zips.setdefault(t["name"], set()).update(t["zips"])
        for z in t["zips"]:
            zip_town.setdefault(z, []).append(t["name"])
    return zip_town, town_zips


def resolve(zips=None, towns=None):
    """-> Scope, or None when nothing was narrowed.

    None is NOT the same as a Scope holding every zip: callers key behaviour on the
    difference (listings.py only ends listing spells inside a scope, and would end all of
    them on a full run). Keep the distinction."""
    if not (zips or towns):
        return None
    zip_town, town_zips = load()
    by_lower = {n.lower(): n for n in town_zips}

    unknown = [z for z in (zips or []) if z not in zip_town]
    unknown += [t for t in (towns or []) if t.lower() not in by_lower]
    if unknown:
        raise Unknown("unknown zip/town: %s\n(see zips.json for the target list)"
                      % ", ".join(unknown))

    out, asked = set(zips or []), set()
    for t in (towns or []):
        name = by_lower[t.lower()]
        asked.add(name)
        out |= town_zips[name]
    # a bare --zip names no town, so everything its zips cover counts as asked-for rather
    # than as a surprise tag-along
    for z in (zips or []):
        asked.update(zip_town[z])
    return Scope(out, asked, zip_town)
