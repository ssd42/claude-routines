# SPIKE — persistence across devices (favourites + notes that follow you)

**Status:** proposal. Nothing built. **The choice of backend is already made** — this
document plans it, it does not re-open it. §2 records what was rejected so nobody
re-litigates it in six months.

**Ask:** star a house on the laptop, open the phone on the way to a viewing, and it's
there. Same for the free-text "what I liked / what I didn't" note. Today every page's
state is `localStorage` — per device *and* per browser — so the laptop and the phone
share nothing at all.

**Decision:** a **Cloudflare Worker in front of Workers KV**, keyed by a random
unguessable **space-id** that lives in `localStorage` and travels in a URL. No login,
no accounts, no passwords. Alongside it, **export/import a JSON file**, built in v1, so
the data is never trapped inside a vendor.

---

## 1. The shape

```
  offer/*.html ──(read)──► localStorage          instant, offline, source of truth
       │                        │
       │ (debounced write)      │ (merge on load)
       ▼                        ▲
   https://<worker>.workers.dev/s/<space-id>
       │
       └──► Workers KV          one key per space, value = one JSON blob
```

Two tiers, and the second one is not optional:

| tier | what | why it exists |
|---|---|---|
| **1 — sync** | Worker + KV under a random space-id | the actual feature: two devices, one list |
| **2 — export/import** | a "download my data" button and a "load a file" button | the vendor escape hatch. Cloudflare changes its free tier, or we get bored of it, and the data walks out in a file. Costs ~20 lines. Build it in v1, not "later". |

The space-id is a **random 128-bit token**, rendered as ~22 URL-safe characters
(`crypto.randomUUID()` is fine, or `crypto.getRandomValues` base64url'd). It is minted
in the browser on first use, stored in `localStorage`, and put on the URL as
`?space=<id>` when you want to hand it to the other device. That's the whole
"onboarding": open the link once on the phone, it saves the id, done.

---

## 2. What was considered and rejected

Recorded so the argument doesn't get replayed.

| option | why not |
|---|---|
| **Firebase / Firestore** | Genuinely better on paper — **20k writes/day** against KV's 1k, plus real-time cross-device sync you get for free. But it needs an **SDK and a build step**, and that breaks the property this whole site is built on: dependency-free, no build, **works from `file://`**. And its anonymous auth gives every *device* its own identity — which is backwards from what we want. We'd end up ignoring the identity and using a shared random id anyway, *plus* writing security rules on top. More machinery to arrive at the same model. |
| **Supabase** | Same shape as Firebase, heavier. And row-level security is a config you can get wrong silently — on a **public repo** where the URL and anon key are readable by anyone, a misconfigured RLS policy is a real, ordinary mistake, not a hypothetical one. |
| **Private GitHub gist + per-device token** | The token never enters the repo, which is the appealing part. But tokens expire, and the first-run experience is "paste a GitHub PAT into a text box on your phone." That's a bad enough moment to sink the feature. |
| **URL-only state** | Already half-built (`market.html` puts filters in the hash). Zero infra, and it stays. But it cannot hold a paragraph of free-text notes about a house, and the whole point of favourites is the notes. |

**None of these are wrong. Cloudflare wins because it keeps the site dependency-free
and no-build** — everything else asks us to give that up.

---

## 3. The security model, said plainly

**The space-id in the URL *is* the password.** Anyone who has the link can read every
favourite and note in that space, and can overwrite them. There is no second factor,
no account, no per-user permission. If the link leaks, the space leaks.

That is a deliberate trade, and here is the honest case for it:

- **The blast radius is a list of houses two people like, and their opinions of the
  kitchens.** It's private, mildly, in the way a text thread is private. It is not
  financial, not credential, not identifying beyond "these people are shopping in
  Union County."
- **An unguessable 128-bit id is not findable.** It won't be crawled, brute-forced, or
  enumerated. The realistic leak is *us* — pasting the URL into a Slack channel or a
  screenshot — not an attacker.
- **The alternative costs a login**, and a login for a two-person house hunt is the
  kind of feature that never gets used because signing in on a phone is annoying.

**What would change if that trade stops being acceptable:** the moment this holds
anything that would embarrass or cost us — an offer number we're planning, a lender
letter, anything with a name and a dollar figure attached — the model has to change.
The cheapest upgrade path, in order:

1. **A second shared secret**, held only in the two browsers, used to encrypt notes
   client-side before they're sent. The Worker then stores ciphertext and genuinely
   cannot read it. This is a real option and not much code.
2. **Cloudflare Access** in front of the Worker, gated on two email addresses. Free
   tier covers it. This is the "we actually want auth" answer.

**Write, not just read, is the sharper edge.** Whoever has the link can also *delete*
your favourites. Mitigation is boring and sufficient: the export file (tier 2), and a
Worker that keeps the **previous** blob under `<id>:prev` on every write, so one bad
overwrite is recoverable. That's one extra KV write per save — see §4 before agreeing
to it.

---

## 4. The budget, and the one limit that actually binds

Free-tier facts, from the current docs:

| | free tier | resets |
|---|---|---|
| **Workers** requests | 100,000/day | daily |
| **Workers** CPU | 10 ms per invocation | per call |
| **KV reads** | 100,000/day | 00:00 UTC |
| **KV writes** | **1,000/day** | 00:00 UTC |
| **KV deletes** | 1,000/day | 00:00 UTC |
| **KV list** | 1,000/day | 00:00 UTC |
| **KV storage** | 1 GB | — |

Paid starts at **$5/mo** if we ever blow through it.

**Expected usage for two people: ~50 reads and ~20 writes a day.** That is two orders
of magnitude of headroom on reads and roughly **50×** on writes. 10 ms of CPU is
enormous for "parse JSON, put it in KV" — this Worker does no work (§5).

So nothing here is close to binding **except one thing, and it's a foot-gun:**

> **1,000 writes/day dies instantly to a save-on-every-keystroke notes box.** A
> 200-character note typed at a normal pace is ~200 writes. Five notes and the day's
> quota is gone — and the failure mode is silent: KV starts refusing writes, and the
> page cheerfully thinks it saved.

**Therefore: debounce, hard.** Rules for v1:

- **Free-text notes: debounce ~2 s of idle, and flush on blur / page-hide** (
  `visibilitychange` — a phone backgrounding the tab must not lose the note).
- **Favourite toggles: also debounced**, batched into the same blob. Starring six
  houses in a row is one write, not six.
- **One key per space, one blob.** Not one key per house. A blob write is a write
  whether it changed one field or forty, and KV additionally rate-limits writes to
  *the same key* to about one per second — which the debounce already respects.
- **Never write when nothing changed.** Compare the serialised blob to the last one
  sent; identical means skip. This alone kills most accidental writes.
- **Surface the write state on the page** — a quiet "saved · 12:04" / "saving…" /
  "offline — saved on this device only". Silent sync is how you find out three weeks
  later that nothing synced.

With that, the `<id>:prev` backup in §3 doubles the write count and is still nowhere
near the ceiling. Keep it.

---

## 5. The Worker stays dumb — and that is the actual win

**The Worker does exactly two things:**

```
  GET  /s/<space-id>   ->  the stored JSON blob, or {} if there's nothing yet
  PUT  /s/<space-id>   ->  validate it's JSON, cap the size, store it, return ok
```

No schema on the server. No queries. No merge logic. No analysis. It does not know
what a favourite *is*. It's a JSON locker with a long key.

That is not laziness, it's the design:

- **A dumb store can't be wrong about our data.** All the meaning — what a favourite
  is, how notes attach, how a delisted house is handled — lives in code we can read in
  one file, versioned in this repo, not in a vendor console.
- **A Worker URL is a plain HTTP GET.** That means `aggregate.py` (or a future
  scheduled routine) can read the favourites with `urllib.request` and nothing else —
  no SDK, no auth dance, no service account. **This is what unlocks the
  "estimate what a favourited house will need" card in [`../TODO.md`](../TODO.md):**
  a scheduled run fetches the blob, reads the favourites, and does the work in
  Python where all the other analysis already lives.
- **That's a concrete advantage over Firebase**, and worth stating: reading Firestore
  from Python means a service account credential — i.e. a *secret* — in a project
  whose defining constraint is that it has none. A public GET has no such problem.
- **All analysis happens in Python.** The browser stars and types; Python reads and
  reasons. Same split the rest of `market-history` already has.

Practical Worker details, all boring:
- **CORS**: must return `Access-Control-Allow-Origin`. `file://` pages send
  `Origin: null`, so a strict allow-list has to include `null` *and* the Pages origin,
  or this only works when served. Decide deliberately; `null` is not a security
  boundary anyway (§3 already conceded the id is the password).
- **Cap the body** at, say, 256 KB and reject bigger. KV values can hold far more, but
  nothing legitimate here is that large and a cap stops a runaway loop filling the
  space.
- **Reject a malformed id** (length + charset) before touching KV.

---

## 6. localStorage stays the source of truth

**The Worker is a sync layer, not the database.** The page must read and write
`localStorage` first, render from it, and treat the network as an afterthought.

- **Load:** render from `localStorage` immediately. Fetch the remote blob in the
  background; if it arrives and differs, merge and re-render.
- **Save:** write `localStorage` synchronously, always. Queue the remote `PUT`
  (debounced, §4). If it fails, keep the queue and retry on the next interaction.
- **If Cloudflare is unreachable — or we never set it up, or the space-id is
  missing — every page still works exactly as it does today.** That is a hard
  requirement, not a nice-to-have. This site's whole appeal is that it opens from a
  file and does not need anything.

**Merge rule — decide this before writing code, because "last write wins" will eat a
note eventually.** Two devices, one blob, no locking. Proposal:

- Favourites are a **map keyed by house identity** (§7), each entry carrying an
  `updated_at`. Merge = union of keys; on a key collision, **newer `updated_at` wins**.
  Un-starring is a **tombstone** (`removed_at`), not a deletion, so an old blob from
  the phone can't resurrect a house you deleted on the laptop.
- Notes are free text and are the thing worth protecting. On a genuine conflict —
  both sides edited the same house's note since the last common sync — **keep both**,
  concatenated with a marker, and let the human sort it out. Losing a paragraph
  silently is worse than an ugly note.
- Clocks are device clocks and can be wrong. Accept it; the failure is two-people-scale.

---

## 7. What a favourite actually is

This matters more than the transport, and it's where a naive version breaks.

**A favourite needs an identity that survives a re-scrape.** The listing rows are
rebaked whenever `listings.py` runs; an array index or a row position is meaningless
by the next fetch. Use the stable listing identity (`property_key` / `mls_id` — the
same identity the listing pipeline already carries), and fall back to a normalised
`address + zip` key when that's absent. Store the key you used, so a later change of
scheme is diagnosable.

**Snapshot the listing at favourite-time.** When you star a house, copy into the blob:
price, address, town, beds/baths, sqft, lot, photo URL, listing URL, and the date you
starred it. Do not store a pointer and look it up later.

Why: **listings are perishable** — the whole §3 argument of
[`SPIKE-market.md`](SPIKE-market.md). A house delists, the row vanishes from
`listings.js`, and a pointer-based favourite becomes a note attached to nothing. Your
"loved the kitchen, hated the street" has to still make sense in November.

**Keeping delisted favourites is a feature, not garbage collection.** "Houses we
lost, and what they went for" is real signal about what we can actually win — it's
the one dataset that tells you whether your price band is realistic. A delisted
favourite should stay in the list, visibly marked *"no longer listed — last seen
$725,000, starred 14 Aug"*, and if it later shows up in `sales.csv`, the page can say
what it actually sold for. That comparison is worth more than the favourite was.

Sketch of the blob, so the shape is arguable:

```json
{
  "v": 1,
  "updated_at": "2026-07-21T14:02:11Z",
  "favourites": {
    "<listing-key>": {
      "starred_at": "2026-07-14",
      "snapshot": {"addr": "29 Rutgers Rd", "town": "Clark", "price": 735000,
                   "beds": 3, "baths": 2.5, "sqft": 2109, "lot": 15085,
                   "photo": "https://…", "url": "https://…"},
      "note": "kitchen is original. street is louder than the photos suggest.",
      "updated_at": "2026-07-20T09:31:00Z"
    }
  },
  "removed": {"<listing-key>": "2026-07-18T11:00:00Z"}
}
```

Two people, a few dozen favourites, a paragraph each: **well under 100 KB.** Storage
is a non-issue.

---

## 8. Setup cost

| step | |
|---|---|
| Cloudflare account | free, email + password |
| `npm i -g wrangler`, `wrangler login` | one command each |
| `wrangler kv namespace create FAVOURITES` | one command |
| `wrangler.toml` — name, the KV binding, nothing else | ~6 lines |
| `wrangler deploy` | one command; prints the `*.workers.dev` URL |

**~15 minutes**, once, on the laptop. After that it is a URL. Note the irony worth
accepting: `wrangler` is a Node dependency — but it's a *deploy-time* tool on one
machine, not a runtime dependency of the site. **The site itself stays dependency-free
and build-free**, which is the property we refused to trade in §2.

---

## 9. Secrets — the rule this repo cannot bend

`github.com/ssd42/claude-routines` is **public** (root [`../../CLAUDE.md`](../../CLAUDE.md)).

- **No Cloudflare API token, account id, or `wrangler` credential goes into any
  tracked file.** `wrangler login` keeps its credential in the user's home directory —
  leave it there.
- **The Worker URL is not a secret and may be committed.** It's a public endpoint by
  design.
- **The space-id is effectively a password (§3) and must NEVER be committed** — not in
  a page, not in `build_data.py`, not in a README, not in a test fixture, not in a
  commit message. It lives in `localStorage` and in whatever private channel we use to
  move it between devices. `.gitignore` already blocks `*secret*` / `.env*` as a
  backstop, but the rule is "don't write it down in-repo."
- **The page must never hard-code a default space-id.** Mint it at runtime, per
  browser. A committed default id would be a shared, world-readable space — the exact
  failure §3 is designed to avoid.
- **If a space-id ever lands in a commit: treat it as public.** Mint a new one, copy
  the data across, abandon the old. It's cheap precisely because there's no account
  attached — that's a genuine upside of this design.
- **If a scheduled routine ever reads the blob**, the space-id becomes a routine env
  var (`MARKET_HISTORY_SPACE_ID` or similar), referenced by name in config, never by
  value — same handling as the house-hunt Slack webhook.

---

## 10. What I'd cut from v1

- **No accounts, no login, no email.** That's the whole premise; listing it so nobody
  adds it "for safety" later without re-reading §3.
- **No real-time sync, no polling, no WebSockets.** Sync on page load and on save.
  Two people are not editing the same note at the same second; building for that is
  building for someone else's problem. (It's also the one thing Firebase would have
  given us free — and we still don't need it.)
- **No per-house KV keys, no server-side merge, no conflict UI.** One blob, the merge
  rule in §6, done in the browser. The moment the Worker knows the schema, it's a
  backend, and we've bought an operational burden for two users.
- **No sharing spaces with other people, no read-only links.** That's a permission
  system wearing a costume.
- **No sync of page *filters*** (price cap, sort, ticked towns). Tempting since it's
  the same pipe — but the URL hash already makes any view a shareable link, and
  syncing filters across devices means your phone's view lurches when the laptop
  changes something. **Favourites and notes only.** (Town *groups* are a different
  question and get their own document —
  [`SPIKE-saved-searches.md`](SPIKE-saved-searches.md) §2.)
- **No version history / undo UI.** The `<id>:prev` key (§3) is a recovery mechanism
  we can read manually if something goes wrong. That's enough.

---

## 11. Scope

| step | what |
|---|---|
| 1 | The Worker: `GET`/`PUT /s/<id>`, CORS, size cap, id validation, `:prev` backup. Maybe 60 lines. |
| 2 | `wrangler.toml` + KV namespace + deploy (§8). Worker URL goes in the page as a constant. |
| 3 | A small `sync.js` — mint/read the space-id, load-merge, debounced save, offline queue, status line. Duplicated into each page or included as one shared `<script>`; **not** an ES module (`file://` blocks those). |
| 4 | Favourite identity + snapshot (§7), wired into `market.html` rows and `sold.html`. |
| 5 | The favourites page: starred houses, notes box, delisted ones marked, export/import buttons (tier 2). |
| 6 | Sanity pass: **(a)** kill the network and confirm every page still loads and stars; **(b)** type a 300-char note and confirm it produced **one** write, not 300; **(c)** star on device A, load device B, confirm it appears; **(d)** un-star on A, load a *stale* B, confirm the house stays dead (tombstone works); **(e)** delist a favourited house from `listings.js` and confirm the card and note survive. |

**Estimate: small-to-medium.** The Worker is trivial. The real work is §6 (merge) and
§7 (identity + snapshot), and both are browser-side.

---

## 12. The thing that worries me

Not the security model — §3 is a considered trade and I'd make it again for two people
tracking houses.

**It's that sync failure is invisible.** A stale snapshot on `market.html` at least has
a date at the top screaming at you. A sync that quietly stopped working three weeks ago
looks *exactly* like a sync that's working — until the phone shows five favourites and
the laptop shows eleven, and you can't tell which one is behind or what got lost.

So the same contract as everything else here applies: **say how much you know, and how
old it is.** The favourites page shows *"synced 4 minutes ago"* or *"this device only —
last synced 3 days ago"*, prominently, and the export button sits right next to it. If
we build this, that status line is part of v1, not a polish item.
