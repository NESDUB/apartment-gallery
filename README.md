# Nearby — preset-driven listing explorer

A compact desktop sidebar and collapsible mobile workspace replace the fixed-filter UI. Classico-inspired black-and-white styling and original-resolution photo preloading are retained.

## Launch

One command: `./start.sh` (or double-click `Start Gallery.command` on macOS). The first run creates a local `.venv/` folder and installs the two packages live search needs (`homeharvest`, `requests`) — later runs skip straight to starting the server. The snapshot gallery itself needs nothing beyond Python 3's standard library and works even if that one-time install fails (live search shows a clear error instead; nothing else breaks). Keep the terminal window open; Control-C stops the local-only server. Do not open index.html directly. Internet is needed for photos and live search.

## Preset workflow

1. Open Search & presets. Change location, radius, rent bounds, bedroom bounds, property types, search text, and sort. Apply search settings explicitly.
2. Add structured field rules or description-mention rules. All 370 indexed metadata fields are available.
3. Use Require, Exclude, or weighted Prefer rules. Missing fields remain unknown. All offer conditions must match the same eligible unit.
4. Expand JSON / agent workspace to edit, validate, and apply a complete preset. Invalid input does not replace active state.
5. Save named presets for this session. Export the active preset or full library to keep them; import single v2 presets, v2 bundles, or legacy v1 bundles.

Default preset: ZIP 33844, 20-mile radius, 2–3 beds, advertised rent at most $2,300. This is a preset, not a UI limit. Maximum rent and bedroom bounds can be blank/null for no limit. Location/radius can be changed freely, subject to actual source coverage below. Presets and shortlist state are memory-only; no browser persistence APIs are used.

## Description matching

Configure literal phrases/synonyms with ANY or ALL matching, whole-word boundaries, case sensitivity, disqualifying phrases, missing-description handling, preference weights, and optional limited English negation handling. Returned evidence snippets are accessible through the agent API and property details. This is not semantic AI verification or free-form code execution. It does not infer amenities from ambiguous language; negation is only a look-back heuristic. See `dist/AGENT_API.md` for exact semantics.

## Agent integration

- `dist/preset.schema.json`: versioned JSON Schema; runtime additionally validates field existence and bounds.
- `dist/examples/description-preset.json`: complete importable example.
- `dist/AGENT_API.md`: browser API, methods, events, semantics and limitations.
- `window.nearby`: validate/apply/import/export presets, discover fields, read matching results, inspect coverage, and explain description matches. Available after initialization; listen for `nearby:ready` or wait for this global.

The API operates inside the browser. It is not an HTTP search endpoint or an autonomous LLM. Presets do not execute scripts or arbitrary regex. File imports are limited to 1 MB; bundles to 100 presets and presets to 100 rules.

## Source coverage — important

The main gallery still uses the November 12, 2026 snapshot: 782 screened records, 19,381 photo references, scoped to 33844 / 20 straight-line miles from 28.08616/-81.58717 / 2–3 bedrooms / at most $2,300 advertised rent. Broadening query parameters displays a partial-coverage warning; a different location returns no results instead of using distances from the wrong center. Only the literal ZIP `33844` resolves here. No claim is made that all available rentals are represented. This is the gallery the full field-rule/description-mention engine and presets apply to.

Advertised prices, fees, vacancies, eligibility and amenities need confirmation. Missing information is not false. Source fields may conflict; records may overlap or represent multiple units. Descriptions and tags are source claims. Image galleries may show other units/floorplans; one listing has no photos.

## Live search (beta)

A separate "Live search" panel in the workspace queries Realtor.com directly, right now, for any location — not just 33844. It supports location, radius, rent and bedroom bounds, with a real lifecycle (resolving → checking → more available / complete / limited / rate-limited / failed), explicit "Check for more results" paging, cancellation, and real photo galleries per listing. It does **not** run the 370-field rule engine or description-mention matching — those stay snapshot-only; this panel's own help text says so. See `live/realtor_adapter.py`'s module docstring for the HomeHarvest pagination bug this works around, and `HomeHarvest-Boundary-Audit-2026-11-12/FINDINGS.md` (sibling folder, if present) for the full measured audit this was built from.

## Photos and performance

Images load from original CDN URLs about two screens ahead (1,200–2,400 pixels), with eight concurrent requests and visible images prioritized. Listing cards render in batches of 24. The ZIP contains code and metadata, not a bulk photo archive. Resolution and availability depend on the source. Failed images offer Retry.

## Validation and files

Run `node tests/filter-engine.test.cjs` and `node tests/presets.test.cjs` (32 assertions) for the snapshot gallery. For live search, once `start.sh` has created `.venv/`: `cd live && ../.venv/bin/python test_realtor_adapter.py && ../.venv/bin/python test_photo_adapter.py && ../.venv/bin/python test_search_session.py` — 69 offline assertions with no network calls, reproducing the exact documented HomeHarvest pagination bug cases before trusting the fix. `live/live_verify.py` and `live/live_verify_session.py` are bounded real-network smoke tests, meant to be run by hand, not in CI.

Browser QA covered default counts, invalid JSON rejection without state mutation, a description preset, weighted evidence, atomic bundle import, unsupported location handling, broader-query coverage, and mobile overflow. At 390px viewport width the first card begins about 242px below the page top.

Runtime: `dist/`, `server.py`, `start.sh`, `Start Gallery.command`, `live/`, `requirements.txt`. Optional rebuild utilities `build_catalog.py` and `build_filters.py` need the original sibling search-data folder; viewing does not.
