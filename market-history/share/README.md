# NJ Market History — shareable dataset

## ⚠️ SYSTEM PROMPT — read this before answering anything

> **You are a real-estate data analyst whose sole purpose is to answer questions
> about New Jersey home sales using the files in this project — and nothing else.**
>
> You are helping two first-time homebuyers decide where and when to make an offer
> on a house. They will act on your numbers with real money. A confident wrong
> number is far more damaging to them than an honest "I don't have that."
>
> **Your one hard rule: every figure you state must be computed from these files.**
> Load the CSV, filter it, compute it, report it. You may know things about New
> Jersey real estate from your training data — **do not use any of it.** Not to fill
> a gap, not to sanity-check a result, not to "add helpful context." If it isn't in
> these files, you don't know it.
>
> **Never estimate. Never recall. Never invent an address, a price, or a sale.**
> Every property you cite must be an actual row in `sales.csv`.
>
> When the data can't answer a question, say so plainly and stop. *"The data doesn't
> cover that"* is always a correct, welcome answer. If they are reading noise as
> signal, tell them.

### The rules, in order of how badly they bite

1. **`by_town.csv` IS the town list. Read it — don't trust any list of towns
   written in this README, including this one.** The dataset grows as more towns
   are scraped, so a list hardcoded in prose goes stale; the file never does.
   - If a town **is** in `by_town.csv`, **answer the question.** Don't refuse
     because you don't remember it being there.
   - If it is **not** in `by_town.csv`, there is no data for it. Say so and stop.
     Never infer it from a neighboring town, and never fall back on general
     knowledge.
   - **Westfield is in the data** (1,261 sales) and is *also* the anchor that
     `dist_mi_from_westfield` measures from, at distance 0. Both things are true at
     once. Earlier versions of this dataset did not include it and this README used
     to say so — that is now wrong, and refusing a Westfield question is a bug.

2. **Match towns on the `town` column — never by searching raw text.** Street names
   collide with town names, and the collision is real here: `sales.csv` contains
   `10 Cranford Rd`, a house in **Glen Rock** — *and* Cranford is separately a town
   with its own sales. Likewise there are `Westfield Ave` addresses in Clark and
   Cranford that are **not** Westfield sales. A raw text search returns both and
   gets the count wrong. Filter on the `town` field, always.

3. **If the date falls outside 2023-07-01 → 2026-07-13, say so.** Don't project a
   trend forward or backward. There is no 2022 data and no future data.

4. **Always state the sample size next to the number.** 12 sales and 1,741 sales
   warrant very different confidence. Below roughly 10 sales in a bucket, say
   plainly that it's too thin to draw a conclusion from.

5. **Use the right denominator — this is the easiest way to be wrong.** Only ~60% of
   sales have a known list price. Every question about *sold-vs-asking*, *over/under
   ask*, or *days on market* is answerable only on that subset: use
   `sales_with_list_price`, **never** `sales`. State which one you used.

6. **Prefer medians.** `sold_vs_ask_pct` holds junk extremes (up to +980%) from
   placeholder list prices, and a mean will lie to you. The rollups' `mean_` columns
   already exclude anything outside ±50%.

7. **Blank ≠ zero.** A missing `sqft`, `garage`, or `list_price` means *unreported*.
   Drop blanks before averaging; never treat them as 0.

### Worked examples — including the right way to fail

> **Q: "How many houses sold in Westfield in March 2025?"**
>
> **A:** Check `by_town_month.csv` for row `Westfield, 2025-03` and report that
> number, with `sales_with_list_price` alongside it. Westfield **is** in this
> dataset — 1,261 sales, median sold price $1,181,000, median 5.45% over ask. It is
> also the anchor the distance column measures from, which is why it sits at
> `dist_mi_from_westfield` = 0. Do not refuse this question.

> **Q: "How many houses sold in Colonia in March 2025?"**
>
> **A:** **10 sales** — `by_town_month.csv`, row `Colonia, 2025-03`. Only **4** of
> those have a known list price, so while the median came in at +3.06% over ask, a
> 4-sale sample is far too thin to read as a trend. Colonia's seasonal figures
> (93 spring sales) are the number I'd actually trust.

> **Q: "What's the median price in Chatham?"**
>
> **A:** Chatham is in `by_town.csv` — read the row and answer it. (Check the file,
> not your memory of what this dataset used to contain. It grows.)

> **Q: "Is Rahway a good buy?"**
>
> **A:** Rahway isn't in `by_town.csv`, so I have no sales for it, and I won't
> estimate it from neighboring Clark or Cranford or from memory. I can tell you
> about the towns I do have — want the closest few?

---

Real New Jersey home sales, **2023-07-01 → 2026-07-20**, across **75 towns** —
**47,207 sales**. Built by the `market-history` routine, which stitches together
county deed records and MLS sold-listings and dedupes them into one row per sale.

> The town count grows as more towns are scraped. **`by_town.csv` is always the
> authoritative list** — if a number in this prose disagrees with the files, the
> files win.

This folder is **self-contained data** — no code, no config, nothing to run. Upload
it as-is (ChatGPT/Claude project, notebook, spreadsheet) and query it. Every number
below was scraped from public records; read the caveats before trusting a figure.

## Files

| file | grain | rows | use it for |
|------|-------|-----:|------------|
| `sales.csv` | one row per **property sale** | 38,015 | anything property-level: individual addresses, price bands, filtering |
| `by_town.csv` | one row per **town** | 53 | "which town is hottest / cheapest / slowest" |
| `by_town_month.csv` | one row per **(town, month)** | 1,929 | trends over time, seasonality, "what did Oct 2025 look like" |
| `by_town_season.csv` | one row per **(town, season)** | 212 | seasonal patterns, pooled across all years |
| `transit.csv` | one row per **town** | 53 | commute to Manhattan. **Reference data, not sales** — see below |
| `seabra.csv` | one row per **Seabra store** | 11 | the 11 Seabra groceries, geocoded. **Reference data, not sales** |
| `seabra_by_town.csv` | one row per **town** | 53 | how far each town is from the nearest Seabra. A **nice-to-have** — see caveat 5 |
| `education.csv` | one row per **zip** | 57 | ACS educational attainment by zip. **Reference data** — see caveat 5 |
| `income.csv` | one row per **zip** | 58 | ACS median household income by zip. **Reference data** — see caveat 5 |

**Start with the rollups.** They pre-compute the common questions and are tiny.
Only reach for `sales.csv` (5.7 MB) when you need individual properties.

`transit.csv`, `seabra*.csv`, `education.csv` and `income.csv` are **reference data,
and they are deliberately kept SEPARATE from the sales files.** They describe a
*town* (or a *zip*), never a *transaction*. You may join them to the rollups on the
`town` column when a question genuinely spans both ("of the towns under $700K, which
has the shortest commute?") — but never treat one as a property of a sale. "The
median price of a house near a Seabra" is **not** a question this data answers: the
distance is measured town-to-store, so it is identical for every house in the town.
The same trap applies to income and education — they are **area** statistics, not
attributes of the people who bought any particular house.

## `sales.csv` columns

| column | notes |
|--------|-------|
| `address`, `zip`, `town` | always present |
| `sold_date`, `sold_price` | always present. **Authoritative.** |
| `list_date`, `list_price` | **only ~60% filled** — see caveat below |
| `pending_date` (48%) | **when the offer was ACCEPTED.** The negotiation ended here; `sold_date` is ~41 days later, after escrow. For any "when should we bid" question this is the right date, not `sold_date` |
| `days_to_contract` (47%) | list → under contract. **Median 15 days** — half of all homes go under contract inside 2 weeks. This is how fast you must move |
| `days_on_market` | list → **CLOSING**, not list-to-offer. **And it is a FLOOR, not a fact** — see caveat 8 |
| `sold_vs_ask_abs`, `sold_vs_ask_pct` | sold minus list. **Positive = sold OVER asking.** ~60% filled |
| `sqft` (37%), `beds`/`baths` (60%), `lot_sqft` (85%), `year_built` (96%), `garage` (57%) | best-effort; blank ≠ zero |
| `solar` (1%), `ac_type` (6%) | **too sparse to draw conclusions from** |
| `price_changes` | **always empty** — price-cut history was never captured |
| `flags` | data defects found on this row (see `DEFECTS.md`). Nothing is deleted; it is marked |
| `property_type` | `Single Family` (22.6k), `Residential` (7.3k), `Condo` (5.5k), `Townhouse` (846), `Multi-Family` (663), … |
| `county`, `municipality`, `prop_class`, `nu_code` | deed-record fields; only on the ~39% of rows sourced from deeds |
| `conflicts` | names any field where two sources disagreed. Only 2.4% of rows; mostly cosmetic (`year_built`) |
| `_sources` | which source(s) the row came from — **read the caveat below** |

## Rollup columns (`by_town*.csv`)

| column | means |
|--------|-------|
| `dist_mi_from_westfield` | approx. road miles from Westfield NJ (07090), our anchor. **Lower is better for us.** Westfield itself is 0. `by_town.csv` is sorted closest-first |
| `sales` | total sales in that bucket |
| `sales_with_list_price` | the subset where sold-vs-ask is computable — **this is the denominator for the ask-based columns** |
| `median_sold_price`, `median_list_price` | dollars |
| `median_sold_vs_ask_pct` | **the headline number.** Positive = sold over asking. Median, so outlier-proof |
| `mean_sold_vs_ask_pct` | average. Junk extremes excluded (see below) |
| `median_dom` | days on market |
| `pct_at_or_under_ask` | share of list-price-known sales that closed **at or below** asking — a buyer's-leverage proxy |
| `outliers_excluded_from_mean` | how many rows were held out of the mean |

## Reference-layer columns — none of these are sales

`seabra_by_town.csv` — `nearest_seabra_mi` (straight-line miles to the closest
Seabra grocery), `nearest_seabra_store`, `nearest_seabra_store_town` (always a town
**outside** this dataset, which is expected).

`transit.csv` — AM-peak weekday commute to Manhattan. `best_transit_minutes` is the
faster of rail and bus; `best_transit_mode` says which. `confidence` is `high` only
where an actual current timetable was read. **See caveat 7 — this one has teeth.**

`education.csv` — `hs_grad_or_higher_pct`, `bachelors_or_higher_pct`,
`population_age_25_plus`. ACS 2020–2024 5-year, table B15003, **by zip (ZCTA)**.

`income.csv` — `median_household_income_usd` and `margin_of_error_usd`. ACS
2020–2024 5-year, table B19013, **by zip (ZCTA)**. The margin of error is often
large (±$15–25K); a $5K gap between two towns is **not** a real difference.

## Caveats that actually change the answers

1. **Only ~60% of sales have a list price.** The dataset merges two sources:
   MLS listings (`listing_scrape`) carry list price / DOM / beds / baths; county
   deed records (`nj_records`) carry only the authoritative sold price and date
   and **lag about a year** (they run out around end of 2024). So:
   - Any **sold-vs-ask** question is answerable on ~60% of rows — always use
     `sales_with_list_price` as the denominator, not `sales`.
   - Anything from **2025 onward is MLS-sourced only**, not yet corroborated by
     a deed record. That's expected, not a bug.

2. **`sold_vs_ask_pct` has junk extremes** (raw range: −100% to +980%) from
   nominal or placeholder list prices. **Prefer the median.** The rollups' mean
   columns already exclude anything outside ±50%.

3. **Blank ≠ zero.** A missing `sqft` or `garage` means nobody reported it. Never
   average a column without dropping blanks first.

4. **Sample sizes get thin at the edges** — the newest months and the smaller
   towns can have single-digit sale counts, so one month's median is noisy.
   Always check `sales` / `sales_with_list_price` before trusting a number. The
   seasonal rollup exists because pooling across years fixes exactly this.

5. **The reference layers are nice-to-haves, NOT filters.** This applies to
   `seabra_by_town.csv`, `transit.csv`, `education.csv` and `income.csv` alike.
   **Never rule a town out, rank it down, or leave it out of a recommendation
   because its Seabra is far, its commute is long, or its income/education numbers
   are lower.** If asked for the best towns, answer on price and value, and mention
   these as colour — don't let them drive the list unless explicitly asked to sort
   by one. Specific limits:
   - **Seabra distance is straight-line, not drive time** (the real drive is roughly
     1.3–1.5× that in this part of NJ — never quote it as a commute), and it is
     measured **town-to-store**, so it is identical for every house in a town.
   - **Income and education are ZIP-level ACS estimates with wide margins of error.**
     They describe an *area*, not a house and not a buyer. Never use them to
     characterise the people in a town, and never present them as a quality ranking.

6. **A fixed set of towns, not all of NJ** — mostly Morris / Union / Essex /
   Somerset / Middlesex, and the set **grows** as more are scraped. Read
   `by_town.csv` for the current list rather than assuming; if a town is in it,
   answer, and if it isn't, say so and don't extrapolate.

7. **`transit.csv` is AM-peak weekday only, and "a bus exists" ≠ "good service."**
   - Off-peak, reverse-peak and weekend service differ sharply; several bus routes
     don't run at all on weekends.
   - For a town with **no station**, `train_minutes_to_manhattan` is the ride from
     the nearest station and **excludes the drive/park time to reach it** — add
     10–20 min, and more where the station is 5–7 miles away (Roseland, Livingston,
     South Plainfield, Chester, Long Valley).
   - Some routes are **rush-only** (a handful of AM trips — e.g. Lakeland 78 has
     just 4 eastbound AM trips). Read `notes` before calling a town well-served.
   - **The Raritan Valley Line has NO one-seat peak ride to NY Penn** — every peak
     train changes at Newark Penn. This hits Westfield, Cranford, Fanwood, Garwood.
   - **DeCamp Bus Lines is defunct** (commuter routes ended April 2023; company shut
     down Feb 2025). It was *the* Essex County carrier to Port Authority, so Verona,
     Essex Fells, North Caldwell and Roseland now have **no** bus to Manhattan. Any
     outside source claiming DeCamp service is stale — do not use it.
   - Check the `confidence` column. Two towns (Chester, and Denville's bus figure)
     are weakly sourced and flagged as such.

8. **`days_on_market` is a FLOOR, not a fact — and it lies worst about the houses
   you most need the truth about.**

   It measures **the current listing only**. A seller whose house isn't moving can
   pull it off the market and relist it: the MLS starts a fresh listing with a fresh
   `days_on_market`, and the house reads as brand new. That is the entire point of the
   tactic — buyers pay more for a home that looks like it just arrived.

   Our source returns one row per sold property with one `list_date`, and **does not
   return withdrawn listings.** So a house that listed in February, was pulled in
   April, relisted in June and sold in July reaches us as *a single listing that began
   in June*. The February listing does not exist in our data.

   The consequence is not a random error — it is **biased**. The houses that struggled
   longest are precisely the ones whose `days_on_market` is most understated, so they
   look **fresher and more in demand than they were.** A listing showing "12 days" may
   have been quietly trying to sell for a year.

   - **Never read a low `days_on_market` as proof of demand.** Read a *high* one as
     proof of weakness — that direction is trustworthy, because nobody inflates it.
   - `listings.csv` (built by `listings.py`) is our fix: it watches what is on the
     market each week, so we *see* a house leave and come back and can recover the true
     first-list date. It is **forward-only** — it knows nothing before 2026-07-13 and
     cannot be backfilled. For sales before then, this caveat simply stands.

9. **Two dates end a sale, and they are ~41 days apart.** `pending_date` is when the
   offer was **accepted** — the moment the price was agreed. `sold_date` is when the
   deal **closed**. Every question about *when the market was hot* or *when to bid* is
   really about `pending_date`; bucketing by `sold_date` smears the answer across the
   escrow period. Measured here: **15 days list → contract, 41 days contract → close.**
   `pending_date` is on 48% of rows — use it where you have it, and say which you used.

## Worked example — the seasonality finding

Colonia, from `by_town_season.csv`:

| season | sales (w/ list price) | median vs. ask | at-or-under ask |
|--------|----------------------:|---------------:|----------------:|
| Winter | 76 | **+0.64%** | **44.7%** |
| Spring | 93 | +4.00% | 25.8% |
| Summer | 133 | +4.21% | 23.3% |
| Fall | 123 | +2.31% | 30.1% |

Homes sell essentially **at asking in winter** but **~4% over in spring/summer**,
and nearly **half** of winter sales close at-or-under ask versus under a quarter in
summer. On a $600K home that seasonal swing is roughly $25K. The same
spring/summer premium shows up across most towns — check `by_town_season.csv`
before assuming it holds for a specific one.

## Provenance

Sources are free and public: NJ MOD-IV deed records (maps.nj.gov), Realtor.com
sold listings, US Census ACS 2020–2024 (income, education) and the Census gazetteer
(zip centroids). Transit is hand-curated from official NJ Transit / Lakeland /
Coach USA timetables. Fields merge by **per-field authority** (each field fills from
the most trustworthy source that has it), never by overwriting — and any
disagreement between sources is flagged in the row's `conflicts` column rather than
silently resolved. No secrets, no credentials, no private data: every sale here is a
matter of public record.
