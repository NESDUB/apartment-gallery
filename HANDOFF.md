# Nearby rental explorer — AI handoff

> **Update, later same day:** live-source integration described as missing
> below has since been built (Phases A, B and C — retrieval adapter, live
> search service, UI wiring). See the root `README.md`'s "Live search
> (beta)" section and `live/realtor_adapter.py`'s module docstring. This
> document is kept as-is for historical record of the state it describes.

**Handoff date:** November 12, 2026  
**Project owner / machine:** nes, macOS; working directory `/Users/nes`  
**Current status:** Working, tested local snapshot explorer with agent-friendly JSON presets. A bounded HomeHarvest audit is complete. **Live-source integration is NOT implemented.**

## 1. Read this first

The next work should be a **tested retrieval adapter**, not another cosmetic UI pass. The current HomeHarvest version has pagination defects, geography limitations, silent error paths, and a blocking API. The user specifically asked us to test those boundaries before deciding final live-search UI behavior. We did that and delivered a report. The latest request is this handoff; no instruction to deploy or publish has been given.

Do not tell the user the app now searches live, that changing ZIP fetches new results, or that the current catalog represents all available rentals. Preserve the working snapshot version while implementing and validating the next phase.

### First files to read

1. `/Users/nes/Desktop/HomeHarvest-Boundary-Audit-2026-11-12/FINDINGS.md` — measured findings, evidence distinctions, proposed adapter acceptance gates.
2. `/Users/nes/Desktop/Apartment-Gallery-33844/README.md` — current app behavior and launch.
3. `/Users/nes/Desktop/Apartment-Gallery-33844/dist/AGENT_API.md` — actual preset semantics and browser API.
4. `/Users/nes/Desktop/Apartment-Gallery-33844/dist/preset.schema.json` — v2 format.
5. App source files below, then the audit tests before touching the dependency.

## 2. User intent and constraints

The user wants a rental discovery application, not a fixed downloaded report:

- Retrieve listing metadata on demand from sources, without requiring a pre-downloaded disk catalog.
- Load original-resolution photos lazily and **ahead of scrolling**, not tiny thumbnails or the whole image library at once.
- Change location, radius, rent bounds, bedrooms, property types and other criteria freely.
- Retain the original search as **My default**: ZIP **33844**, **20 miles**, **2–3 bedrooms**, **$2,300/month maximum**, best value/amenities. These are preset values, not permanent UI restrictions.
- Filter available metadata, including amenities, policies, fees, dates and missing values.
- Have **Require / Exclude / Prefer** modes and machine-readable custom presets.
- Import/export JSON, let another AI apply presets, and inspect why results match.
- Use configurable description-mention rules for information missing from structured fields.
- Keep the UI compact, listings-first, with minimal top space on mobile and desktop.

### Visual direction

Keep Nearby's browsing functionality with Classico-inspired white/black, minimal typography, square edges and subtle dividers. Reference is `/Users/nes/Downloads/classico.html`. Do **not** copy Classico's furniture-shop layout. The latest app uses a desktop search/preset sidebar and a collapsed mobile workspace. No large hero or marketing introduction.

### Operational preferences

- **Do not use CX.** User says it is retired. Use the owner's `cpup` CLI when browser automation is needed.
- Before cpup work, read `/Users/nes/.codex/memories/reference_cpup_tool.md`, then discover flags with `node bin/cpup.js --guide` from `/Users/nes/projects/cpup`.
- User objected to substituting web search for testing the downloaded tools. Prefer local source inspection, direct tool execution and bounded source probes.
- Client-side persistence APIs are prohibited by project instructions: no localStorage, sessionStorage or IndexedDB. Current state is in memory; preset files are explicit exports.
- User welcomes concise macOS `say` summaries; retain written artifacts. Do not speak sensitive information.
- Do not spawn subagents unless the user or applicable instructions explicitly authorize them. No child agents are active from this work.
- Keep publication, authentication, purchases, and other unrelated side effects out of scope. No hosted deployment exists.

## 3. Artifact map

| Artifact | Location / status |
|---|---|
| Current app | `/Users/nes/Desktop/Apartment-Gallery-33844/` |
| App ZIP | `/Users/nes/Desktop/Apartment-Gallery-33844.zip` — code and metadata, no bulk photos |
| Boundary audit | `/Users/nes/Desktop/HomeHarvest-Boundary-Audit-2026-11-12/` |
| Audit ZIP | `/Users/nes/Desktop/HomeHarvest-Boundary-Audit-2026-11-12.zip` |
| Original search evidence | `/Users/nes/Desktop/Apartment-Search-33844-2026-11-12/` |
| Downloaded repos | `/Users/nes/Desktop/real-estate-scrapers-2026-11-12-130031/repositories/` |
| Repo update report | `/Users/nes/Desktop/real-estate-scrapers-2026-11-12-130031/LAST_UPDATED.md` |
| HomeHarvest repo | `.../repositories/ZacharyHampton--HomeHarvest` |
| Python environment used | `/tmp/apartment-search-py313/bin/python` — temporary location; check existence before relying on it |
| Classico reference | `/Users/nes/Downloads/classico.html` |

The original repo folder and sibling ZIP contain 14 downloaded GitHub projects. HomeHarvest produced the successful search data; previous `aptscom`/`pyzill` attempts did not produce the working dataset. Do not imply all downloaded tools were integrated.

### Old media artifacts — retained, not current deliverables

- `/Users/nes/Desktop/Apartment-Listings-33844-Media-2026-11-12/` and its old `-PARTIAL.zip`: earlier partial thumbnail-oriented downloads.
- `/Users/nes/Desktop/Apartment-Listings-33844-Full-Resolution-2026-11-12/`: partial originals download, deliberately stopped when user chose lazy loading.

Do not resume bulk downloading or delete these folders without a reason and user direction. No bulk downloader is intentionally running. Do not link these old partial ZIPs as the current gallery.

## 4. Current application architecture

Buildless HTML/CSS/vanilla JS, served by a dependency-free local Python HTTP server.

| File | Responsibility |
|---|---|
| `server.py` | Static server only; binds `127.0.0.1`, defaults to port 8768, chooses another port if occupied; optionally opens browser. **No live search endpoint.** |
| `Start Gallery.command` | macOS launcher, runs `python3 server.py` from app directory |
| `dist/index.html` | Current preset-driven UI, no old fixed-filter toolbar |
| `dist/styles.css` | Base Nearby styles |
| `dist/classico.css` | Classico visual overrides; retains some superseded selectors |
| `dist/explorer.css` | Latest sidebar/mobile workspace layout, loaded last |
| `dist/app.js` | Card rendering, shortlist, photo queue, details modal, initialization |
| `dist/advanced-filters.js` | Query state, rule builders, JSON UI, preset library, agent API, coverage checks |
| `dist/presets.js` | v2 validation, literal description-mention matching, v1 migration |
| `dist/filter-engine.js` | Require/Exclude/Prefer evaluation, same-offer matching, weighted scores |
| `dist/data/index.json` | Current summary and 782 lightweight card records |
| `dist/data/filters.json` | 370-field searchable metadata index and per-record values |
| `dist/data/listings/<property_id>.json` | 782 detailed property files with metadata and photo URLs |
| `dist/data/manifest.json` | Snapshot counts/scope |
| `dist/preset.schema.json` | Structural JSON Schema; runtime applies additional checks |
| `dist/examples/description-preset.json` | Complete importable v2 example |
| `dist/AGENT_API.md` | Browser automation contract |
| `build_catalog.py`, `build_filters.py` | Optional rebuilds from original sibling evidence folder; not needed to view app |
| `tests/*.cjs` | Node-based isolated filter/preset tests |

### Launch and verify

```sh
cd /Users/nes/Desktop/Apartment-Gallery-33844
python3 server.py --no-open
# Open the URL printed by the server, usually http://127.0.0.1:8768/

node tests/filter-engine.test.cjs
node tests/presets.test.cjs
node --check dist/app.js
node --check dist/advanced-filters.js
node --check dist/presets.js
```

No owned app server was running at handoff inspection. Start a fresh one for QA. Stop owned QA servers when done. Do not kill unrelated processes or overwrite a user-run server. Static server fallback may change the port; use its printed URL.

### Current data facts

- Research snapshot: November 12, 2026.
- 1,838 raw results across earlier location queries; 1,547 distinct source property IDs; **782 screened records** in gallery. These are not guaranteed distinct physical homes or confirmed vacancies.
- 962 originally matching offer/floorplan entries; the current gallery's detail files preserve offer lists.
- 19,381 photo references after original-photo catalog enrichment. One listing lacks source photos: ID `9797231975`, 405 Caribbean Dr Unit Main.
- Radius is haversine straight-line distance from approximate ZIP center **28.08616, -81.58717**, not driving distance.
- The old collection screened out records outside the original budget/bedroom/radius scope. Widening current filters cannot recover them.
- Current query controls allow broader values, but show partial-coverage warnings. A location other than literal `33844` produces zero matches with an explicit unsupported-location notice, not misleading reused distances.

### Photo behavior

Original `r.jpg` URLs work; `s.jpg` URLs are tiny thumbnails. Earlier guessed `o.jpg` URLs often failed. The API `photos(size: MAX, https: true)` supplied correct originals. The gallery primarily uses that catalog and documented fallback URL conventions; do not replace all URLs with an untested suffix.

Images are assigned `src` only as they approach view. Lookahead is about two viewport heights, bounded to **1,200–2,400px**. Up to **8** image requests run concurrently; visible photos take priority. Card rendering batches are 24. Original dimensions vary; there is no upscaling promise. CDN hosts are `ap.rdcpix.com` and `ar.rdcpix.com`. Photo failures have Retry controls.

`window.galleryStats` exposes requested/loaded/failed/active/queued counts, lookahead, concurrency, total/matching records and rendered cards. These cumulative image counters reset on page load, not every filter change.

## 5. Presets and agent API

The v2 preset contains `version`, `name`, `query`, and `rules`. The authoritative example/schema are in `dist/`. Query fields:

```json
{
  "location": "33844",
  "radiusMiles": 20,
  "minRent": 0,
  "maxRent": 2300,
  "minBeds": 2,
  "maxBeds": 3,
  "propertyTypes": [],
  "text": "",
  "sort": "distance"
}
```

`maxRent`/`maxBeds` can be null for no upper bound. Sorts: distance, price, space, photos. Property types are source identifiers, not arbitrary UI labels.

### Browser API

Wait for `window.nearby` or `nearby:ready` on `document`.

```js
const p = nearby.getPreset();
p.query.radiusMiles = 10;
const validation = nearby.validatePreset(p);
if (validation.valid) nearby.applyPreset(p);
const results = nearby.getResults();
const evidence = results.length ? nearby.explain(results[0].propertyId) : null;
```

Also available: `getFields`, `getCoverage`, `importPresets`, `exportPresets`, `reset`. `nearby:preset-changed` includes `{preset,coverage}`. Methods are synchronous after initialization. This is a **browser API**, not an HTTP backend or connected LLM. `getResults()` ignores the UI-only shortlist toggle, as documented.

- Applying replaces the whole active preset after validation, not a merge.
- Import validates all bundle entries before mutation; invalid input does not partially import.
- Applying does not automatically save a preset to the session library.
- Export active preset separately from exporting saved library entries.
- Legacy v1 preset bundles migrate to v2.
- UI file imports: max 1 MB; bundle max 100 presets; preset max 100 rules.
- Stable DOM IDs and exact method contracts are in `AGENT_API.md`.

### Matching semantics

- All Require/Exclude rules are combined with AND.
- Prefer rules add weighted scores; results rank by preference before the selected secondary sort.
- Offer rules must jointly match the same offer that also meets query price/bedroom bounds.
- Missing fields are not false. Require/Exclude omit unknowns unless `allowUnknown:true`; known/unknown operators explicitly test presence.
- Description `mentions` supports any/all phrases, synonyms expressed as separate terms, case sensitivity, whole-word boundaries, phrase vetoes, and optional negation look-back (0–12 words).
- `excludeTerms` vetoes that mention rule; it does **not** globally exclude a listing unless placed in a corresponding exclusion rule.
- Negation is a small English heuristic, not semantic understanding. It can miss “pool not available,” misread “not only,” or other complex language. Evidence snippets support review.
- No user-provided regex or scripts execute. Description matching does not infer confirmed amenities or extract arbitrary numeric facts.
- Source metadata names are mostly preserved, not fully normalized into an ontology. Suggested field values are capped at 150, but exact values can be typed.

## 6. Boundary audit: confirmed blockers

**Read the complete audit before implementing pagination.** Installed HomeHarvest 0.8.18 corresponds to downloaded commit:

`8a6ac96db419b56a18d295935217649039bcdd0a`

The repository was clean at handoff inspection. No dependency patch was applied.

### Live tests

Seven bounded sequential calls; 15 POSTs; all live HTTP responses were 200. Durations 1.365–3.275s, not a performance guarantee.

1. **ZIP radius ignored.** ZIP 33844 with radius 1 and 20 sent identical geographic query/variables and identical initial IDs. Radius only enters the source request when location resolves to an address. Address-radius query construction was tested synthetically, not live against ground truth.
2. **Pagination bug reproduced.** `offset=5, limit=5` returned 0 despite 110 source rows. `offset=10, limit=5` returned 100 despite a requested five. A normal page boundary (`offset=200, limit=200`) returned 0 in controlled testing.
3. **Source total exists.** ZIP source query reported 115; Orlando reported 1,737. Public `scrape_property()` returns a list and discards total/cursor/completion metadata.
4. **Page size is 200 regardless of small requested limit.** Five requested ZIP records downloaded all 115 available source rows. Orlando `limit=201` downloaded two 200-record pages (~2.10 MB and ~1.95 MB), returning 201.
5. **No streaming.** Public call returns after internal pagination. Orlando first source page arrived around 1.71s; public result around 3.28s. `parallel=False` does not make it an iterator.
6. **Enrichment disabled.** Base scraper forces `self.extra_property_data=False`, overriding caller input. No GetHome request was sent in the enriched-one test.
7. **Mixed units.** In 299 unique test records, all had at least one known joint matching offer, but 699 included unit entries were outside criteria or lacked necessary values. Twelve records lacked description text.

### Controlled error tests — not live incidents

- GraphQL error envelopes without data became empty lists.
- Simulated 429/500 JSON error responses became empty lists; simulated 403 raised AuthenticationError.
- A second-page GraphQL error returned first-page records with no incomplete flag.
- A second-page timeout exception raised without returning the successful earlier page publicly.
- An unresolved location returned an empty list.
- A blocked worker process could be terminated; HomeHarvest itself exposes no cancellation token.

### Source-level causes and limits

- In `general_search`, slicing is `properties_list[: self.limit - offset]`. This mixes an absolute page offset with a requested count and permits negative slicing.
- Proposed remaining-count logic is relative to the initial offset: `max(0, requested_count - (page_offset - start_offset))`. This is a design proposal, **not a tested/applied production patch**.
- The validator rejects limit > 10,000 and offset+limit > 10,000. The live service's actual maximum was not independently stress-tested.
- General HTTP handling does not uniformly classify statuses/errors before JSON parsing. Default requests do not have explicit connect/read timeouts. Audit instrumentation added 10/20s timeouts.
- Amenity/description/custom rule filtering is not a public source-search parameter; it is post-retrieval work. Some date/update options are also post-filtered.

### Audit reproduction

```sh
cd /Users/nes/Desktop/HomeHarvest-Boundary-Audit-2026-11-12
/tmp/apartment-search-py313/bin/python probe.py offline
/tmp/apartment-search-py313/bin/python failure_tests.py
/tmp/apartment-search-py313/bin/python transport_tests.py
```

These make no network requests. `run_live_suite.py` does make bounded live requests and stops on detected 403/429 or timeout. Do not run repeatedly as a stress test. Preserve `live_*.json`, `provenance.json`, and report evidence; distinguish synthetic findings from observed service responses.

## 7. Recommended next implementation sequence

### Phase A — freeze and regression-test the retrieval contract

1. Preserve the current working app and dependency revision. Prefer an isolated adapter module or explicitly tracked fork; do not silently modify site-packages.
2. Reproduce pagination defects with tests at offset 0, 5, 10, 200, page remainders and cap boundaries.
3. Fix consistent count/offset semantics. Assert returned count never exceeds requested allowance and empty local-filter results never imply source exhaustion.
4. Classify HTTP status, GraphQL errors, malformed payload, unresolved location, timeouts and legitimate empty pages distinctly.
5. Add bounded timeouts, retry policy, source-request budgets and cancellation. Respect access denials/rate limits; do not add bypass behavior.

### Phase B — build an in-memory live retrieval service

1. Resolve geography explicitly; preserve requested and resolved center/method. Do not pass ZIP+radius and assume it works.
2. Fetch source-sized pages once, retain raw pages in memory, and emit progressive page/search events.
3. Preserve source total, raw positions, checked count, unique records, matching properties/offers, completeness and errors.
4. Advance pagination by source offsets/raw page positions, not post-filtered match count.
5. Reuse the tested rule semantics. Normalize listings into the UI contract without inventing unknowns. Evaluate description rules only after description state is known.
6. Keep prior successful pages on later failure. Assign a search ID; canceled/stale searches cannot alter current results.
7. Limit work explicitly when matches are rare. Separate source-fetch budgets from photo prefetch.

A live service can run locally and hold data in process memory; disk catalog files are not required. Keep an explicit snapshot/offline mode if useful. Preserve schema versioning when adding source or search-budget options.

### Phase C — connect UI to truthful progressive state

- Replace snapshot-centric “Listings 782” presentation with **Matches found** plus running count and state.
- Show source total only as source-reported, scoped and timestamped; it is not the custom-match total.
- States should distinguish resolving, fetching, evaluating, more available, complete, limited, rate-limited, failed and canceled.
- Use “No matches yet” while work is pending; only declare no matches when search legitimately finishes.
- Label rankings “best among fetched results.” Avoid card rearrangement while a person reads; offer to apply updated rankings.
- Show draft-vs-applied preset status and whether a change refilters buffered data or initiates a new source query.
- Keep shortlist selections across searches; label stale listings.
- Add result export separately from preset export, including scope/timestamps/completeness.
- Do not add a fake enrichment toggle or pretend source failures are empty results.

## 8. Validation completed and current caveats

### Current app

- `tests/filter-engine.test.cjs`: 12 assertions passed.
- `tests/presets.test.cjs`: 20 assertions passed.
- JS syntax checks passed.
- Browser testing covered initial 782 records, preset application, malformed JSON leaving state unchanged, atomic bundle rejection, description evidence/weighted scores, unsupported-location zero results, broader-scope warnings, default restoration and no mobile horizontal overflow.
- Example description preset with its first rule changed to Require produced 57 results in the current snapshot; that rule allowed missing descriptions. Do not equate 57 with 57 verified laundry amenities.
- Mobile 390px: first card starts roughly 242 CSS pixels from page top with workspace collapsed.
- Current app is still tied to full local `index.json` + `filters.json`; replacing those with streaming records requires lifecycle/state work, not just swapping a fetch URL.
- Current `getResults()` returns all current matches synchronously; a live adapter will need explicit asynchronous paging/events or versioned API changes.
- Current API preset library is memory-only. Result export is not implemented.
- Old CSS and screenshots exist; `explorer.css`, `explorer-mobile.png` and `explorer-desktop.png` represent the latest design. Other previews can depict superseded layouts.

### Audit limits

No rate-limit stress tests, full 10k retrieval, production adapter, concurrent-user testing, long-running duplicate-churn study, arbitrary geocoding validation, or comprehensive parameter-combination coverage. Do not infer those properties from seven live probes.

## 9. Browser QA notes

Use dedicated cpup Chrome, not everyday Chrome unless specifically needed and consented. Example:

```sh
cd /Users/nes/projects/cpup
node bin/cpup.js --guide
node bin/cpup.js --browser dedicated --list-tabs
node bin/cpup.js --browser dedicated --tab-url '127.0.0.1:8768' --select-tab --map
```

- Existing dedicated tabs may include the local app and Classico reference. Re-list; do not assume tab IDs.
- Device emulation persists. Use `--device iphone` or `--device desktop` explicitly.
- cpup navigation/actions/eval flag ordering is not necessarily shell argument order. Prefer `--do` for supported ordered steps and separate calls for setup/evaluation.
- Browser `--eval` top-level lexical declarations can persist; use IIFEs or redeclarable variables to avoid “Identifier already declared.”
- Background tabs can stall requestAnimationFrame/image observers. `--select-tab` before waits/screenshots.
- Screenshot immediately after rerender may catch image fade-in/placeholders; wait for current card image naturalWidth, not just cumulative loaded counters.
- Normal UI automation sometimes failed to focus offscreen controls; known DOM controls were exercised with `.click()` / change events via eval for validation. Do not interpret every CLI action-order failure as an app bug.
- Do not stop the owner's unrelated cpup monitor or other services.

## 10. Definition of a successful continuation

A subsequent AI should first deliver a regression-tested adapter demonstrating correct nonzero-offset paging, explicit geographic scope, distinguishable errors/empty states, progressive partial results, cancellation isolation, and same-offer filtering. Only then connect the UI's search/count/progress controls to it. Preserve current preset import/export, description evidence, compact styling and photo preload behavior.

**Do not claim live integration complete until an end-to-end test changes source query parameters, receives fresh source records, applies a custom description preset, survives a simulated failed page, and reports incomplete vs complete accurately.**
