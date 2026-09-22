/* Shared favourites client, exposed as window.FAVS.

   NOT `FAV`: market.html already has `const FAV` for the 524 Farley benchmark, and a
   page-scope const shadows a window global, so the name silently resolved to the wrong
   object.

   Shared favourites client. Loaded by market.html (to star) and favourites.html (to
   browse). Deliberately tiny and dependency-free.

   TWO MODES, decided at load time by asking the server:
     writable   offer/serve.py is running -> stars appear, clicks write favourites.json
     read-only  GitHub Pages, or a plain http.server -> the list still shows, no stars

   The file is the source of truth, not the browser. Nothing here touches localStorage:
   a favourite that lived only in one browser would be invisible to the phone, to git and
   to anything else we build, which is the whole reason this is a file. */
window.FAVS = (function () {
  const API = "api/favourites";
  let state = { writable: false, favourites: [] };
  const listeners = [];

  /* A house needs one identity that survives a price change, a relist or a re-scrape.
     listings.csv already uses number|street|zip, so use the same shape -- two pages
     agreeing on a key matters more than the key being clever. */
  function keyFor(address, zip) {
    const a = (address || "").trim().toLowerCase().replace(/\s+/g, " ");
    const m = a.match(/^(\d+[a-z]?)\s+(.*)$/);
    const num = m ? m[1] : a;
    const street = (m ? m[2] : "").replace(/\b(st|street|ave|avenue|rd|road|dr|drive|ln|lane|pl|place|ct|court|ter|terrace|blvd|boulevard|pkwy|parkway|cir|circle|tpke|turnpike|trl|trail|way|sq|square)\b\.?/g, "").trim();
    return `${num}|${street}|${(zip || "").trim()}`.replace(/\s+/g, " ");
  }

  async function load() {
    try {
      const r = await fetch(API, { cache: "no-store" });
      if (r.ok) { state = await r.json(); state.writable = true; return state; }
    } catch (e) { /* no local server: fall through to the static file */ }
    try {
      const r = await fetch("favourites.json", { cache: "no-store" });
      if (r.ok) { state = { writable: false, ...(await r.json()) }; }
    } catch (e) { state = { writable: false, favourites: [] }; }
    return state;
  }

  async function toggle(house) {
    if (!state.writable) return state;
    const key = keyFor(house.address, house.zip);
    const on = has(key);
    const r = await fetch(API, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: on ? "remove" : "add", key,
        address: house.address, town: house.town, zip: house.zip,
        added: new Date().toISOString().slice(0, 10),
        ask_when_added: house.ask || null
      })
    });
    if (r.ok) { state = await r.json(); listeners.forEach(f => f(state)); }
    return state;
  }

  const has = key => (state.favourites || []).some(f => (f.key || "").toLowerCase() === key.toLowerCase());
  const all = () => state.favourites || [];
  const writable = () => !!state.writable;
  const onChange = f => listeners.push(f);

  return { load, toggle, has, all, writable, keyFor, onChange };
})();
