# layers/ — town-grain reference data

Everything in this routine is one of exactly **two grains**. Knowing which you're
holding is the whole organising idea:

| grain | lives | what it is | built by |
|-------|-------|------------|----------|
| **sale-grain** | `../sales.csv`, `../market.csv` | one row per **transaction**, scraped from public records | `aggregate.py` |
| **town-grain** | **here, in `layers/`** | one row per **town** — an attribute of a *place*, not of a sale | curated / one-shot, joined in by `build_share.py` |

If a new dataset describes a **town**, it belongs here. If it describes a
**sale**, it belongs in the scrape. That question answers itself every time, and
it's the reason this folder exists.

## The layers

| layer | source file | grain | what it answers |
|-------|-------------|-------|-----------------|
| `wawa/` | 31 Wawas near the target set, geocoded. `nearest_wawa_mi` per town. ⚠️ The supplied list was pre-cut at ~5mi, so it is **incomplete for the 9 towns beyond that** — `beyond_supplied_radius` flags them. Its bundled `near_target_towns` field was discarded (26 pairs broke its own 5mi rule); distance is computed, never taken on trust. |
| `trader_joes/` | 11 North Jersey Trader Joe's, geocoded. `nearest_tj_mi` per town. **Only OPEN stores count** — the coming-soon West Orange branch is excluded until it trades. Unlike Seabra, four stores sit *inside* target towns (Westfield 0.3mi), which is expected. |
| `seabra/` | `seabra.json` | 11 store points | how far is a town from a Seabra grocery |
| `transit/` | `transit.json` | town | how long is the commute to Manhattan |
| `education/` | `education_rates.csv` | zip (ZCTA) | ACS educational attainment — **not yet wired into `build_share.py`** |
| `geo/` | `zip_centroids.json` | zip (ZCTA) | support layer: zip → lat/lon, so distances can be computed |

`geo/` is infrastructure, not an amenity — nothing about it goes in `share/` on its
own; it exists so other layers can measure distance.

## The contract

1. **Keyed on `town`** (or on `zip`, which `../zips.json` maps to a town). That key
   is what lets a layer join to `by_town.csv` without being welded to it.
2. **Ships as its OWN file in `share/`.** Never as extra columns on a sales file.
   A town attribute is not a property attribute — fusing them means the two can no
   longer be read, versioned, or dropped independently. (This was tried with Seabra
   and reverted; don't repeat it.)
3. **`aggregate.py` never reads this folder.** Layers are joined in at *share* time
   by `build_share.py`, not at *scrape* time. The scrape stays purely sale-grain.
4. **Amenities are NICE-TO-HAVES, never filters.** A layer must never exclude a
   town, rank it down, or drop it from a recommendation. `share/README.md` — which
   is the system prompt for whatever LLM reads the bundle — says so explicitly, and
   it needs to keep saying so for every layer added. Don't let a layer become a
   score.
5. **State your precision.** Every layer says in its own `_doc`/`_caveats` how it
   was derived and where it's soft (Seabra: straight-line not drive-time,
   town-to-store not house-to-store, one store at zip-centroid precision). A number
   with no stated slop invites false confidence, and these numbers get spent.

## Adding a layer

Drop `layers/<name>/<name>.json|csv` with a `_doc` header describing source,
method, and caveats → read it in `build_share.py` → write `share/<name>.csv` (and
a `<name>_by_town.csv` if it needs deriving) → document it in `share/README.md`'s
file table **and** add its nice-to-have caveat.

Next candidate: `education/` is sitting here parsed but unjoined — it's zip-grain,
so rolling it to a town needs a population-weighted average across the town's zips
(Edison has 3).
