# Fetch runbook (browser-scrape)

How the scheduled agent gathers listings each run, until we swap in a paid API.
This is the **agent-side** half (match.py does everything after `raw/` exists).

> ⚠️ Scraping is brittle and against site ToS. Redfin is primary; Zillow is
> best-effort (it bot-blocks after ~2 hits). Pace requests, never hammer.

## Per run

1. **Fetch each target zip from Redfin** (active + recently sold) with a real
   browser. URLs (filter = 3+ beds, ≤ $650k, houses+townhouses):
   - Active: `https://www.redfin.com/zipcode/<ZIP>/filter/min-beds=3,max-price=650k,property-type=house+townhouse`
   - Sold (comps): `https://www.redfin.com/zipcode/<ZIP>/filter/include=sold-3mo,min-beds=3,property-type=house+townhouse`
   - Zips: `07076` (Scotch Plains), `07067` (Colonia).

2. **Extract** with `browser_evaluate` (these selectors worked 2026-06):
   ```js
   // ACTIVE listings — run on a Redfin zipcode page
   () => [...document.querySelectorAll('div.HomeCardContainer')].flatMap(c => {
     const a = c.querySelector('a[href*="/home/"]'); if (!a) return [];
     const t = c.innerText.replace(/\s+/g, ' ');
     const num = s => s ? Number(s.replace(/,/g, '')) : null;
     const m = re => (t.match(re) || [])[1] || null;
     const img = c.querySelector('img');
     let status = /COMING SOON/i.test(t) ? 'coming_soon'
                : /PENDING|UNDER CONTRACT|CONTINGENT/i.test(t) ? 'pending' : 'active';
     const oh = (t.match(/OPEN\s+[A-Z]{3},?\s*[\d: APM–-]+/i) || [])[0] || null;
     return [{ url: a.href.split('?')[0], photo: img && img.src, status, open_house: oh,
       price: num(m(/\$([\d,]{4,})/)), beds: num(m(/([\d.]+)\s*beds?/i)),
       baths: num(m(/([\d.]+)\s*baths?/i)), sqft: num(m(/([\d,]+)\s*sq ft(?!\s*lot)/i)) }];
   })
   ```
   For **sold** comps, same loop but keep cards whose text matches `/sold/i` and
   read the sold price into `sold_price`. **Derive `address` + `zip` from the
   URL** (`/NJ/Colonia/75-Lancaster-Rd-07067/...` → `75 Lancaster Rd`, `07067`) —
   the card's innerText address is unreliable.

3. **Zillow (best-effort second source)** — try once per zip:
   `https://www.zillow.com/homes/for_sale/<ZIP>_rb/3-_beds/0-650000_price/` then
   pull `article[data-test="property-card"]` (price/beds/sqft from card text,
   address from `<address>`). **If the page title is "Access to this page has
   been denied", STOP Zillow for this run** — do not retry; Redfin alone is fine.

4. **Pacing / backoff** — wait ~5–15s (jittered) between page loads; cap total
   pages; never parallel-hammer one host. Backoff helps rate limits but Zillow
   blocks on browser *fingerprint*, so just skip it when denied.

5. **Write** `raw/redfin.json` and `raw/zillow.json` in the schema match.py
   expects (see its header docstring): `{ "source", "fetched", "listings": [...] }`.
   Keep only in-target zips (07076 / 07067). Set `property_type: "Single Family"`
   for house-filtered results.

6. **Score + post**:
   ```bash
   python3 match.py $(date +%F) --post     # builds the digest + POSTs to the webhook
   ```
   `--post` reads `HOUSE_HUNT_SLACK_WEBHOOK` (env on the scheduler only — never
   in the repo) and sends the Block Kit digest (photo cards + View-listing
   buttons) to channel C0B9JHL9NE9.

## Watchlist intake (interactivity)
After posting, read new replies in the channel's listing threads and apply
commands (one per reply), then re-save `watchlist.json` / `mutes.json`:
- `track <address>`  → add the house to `watchlist.json` (captures list price now)
- `mute <address>`   → add to `mutes.json` so it stops appearing
- `note <address> "…"` → attach a note to the tracked house

## When we move to an API
Swap steps 1–3 for a single call to the listings API (RentCast/ATTOM) writing
the same `raw/*.json` shape — nothing downstream changes.
