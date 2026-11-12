# Nearby preset API v2

Start the local server. Wait until `window.nearby` exists, or listen for `nearby:ready` on `document`. All methods are synchronous after readiness. No credentials, persistence, AI calls, arbitrary JavaScript expressions, or regular expressions execute from presets.

## Stable browser API

```js
const fields = nearby.getFields();
const preset = nearby.getPreset();
preset.query.radiusMiles = 10;
const validation = nearby.validatePreset(preset);
if (validation.valid) nearby.applyPreset(preset);
const matches = nearby.getResults();
const evidence = matches.length ? nearby.explain(matches[0].propertyId) : null;
const coverage = nearby.getCoverage();
const bundle = nearby.exportPresets();
nearby.importPresets(bundle);
nearby.reset();
```

- `getPreset()` returns a copy of the complete active v2 preset.
- `validatePreset(object)` returns `{valid, errors}` without mutation. Errors have field paths. Runtime checks include catalog field existence and ordered min/max bounds in addition to the JSON Schema.
- `applyPreset(object)` validates first, then replaces the complete active preset. Returns `{preset, coverage, results}`. Invalid input throws and leaves current state unchanged. Applying is not saving to the library.
- `getFields()` returns field keys, types, coverage counts, and up to 150 suggested values. Keys are case-sensitive and must match exactly.
- `getResults()` returns matching property IDs, names, preference scores, and matching offers, sorted by preference score then query sort. This API ignores the optional UI-only shortlist toggle.
- `explain(propertyId)` returns source-value match results, description snippets and disqualifying phrase evidence. Per-rule offer evidence spans offers; the final match still enforces the same-offer constraint.
- `getCoverage()` reports snapshot coverage, whether the location is supported, partial-coverage status, and `live:false`.
- `importPresets(object)` imports a single v2 preset, a `{version:2,presets:[...]}` bundle, or a legacy `{version:1,presets:[[name,{basic,rules}],...]}` bundle. All entries validate before any library update. It does not apply imported presets. Duplicate names replace library entries. Maximum 100 entries per import.
- `exportPresets()` returns a JSON-serializable library copy. Export the active preset separately using `getPreset()` if it has not been saved to the library.
- `reset()` restores the built-in original preset; this is independent of any imported preset named My default.

`nearby:preset-changed` fires on `document` with `{preset,coverage}` in `event.detail`. The API is for browser automation, not a server HTTP search API. Stable DOM IDs include `json-editor`, `validate-json`, `apply-json`, `import-presets`, `export-preset`, `export-presets`, `preset-picker`, and `apply-preset`. Check `preset-message` for validation feedback.

## Preset semantics

See `preset.schema.json` and `examples/description-preset.json`. Query maximums may be `null` for no limit. Property types are source identifiers; an empty list means any. All Require/Exclude rules are ANDed. Prefer rules add `weight` points (default 1) per matched rule. Score is sorted descending before the chosen query sort. Offer rules must all match one offer that also satisfies query rent and bedroom bounds; displayed card prices come from eligible offers.

Missing values are unknown. For ordinary Require/Exclude rules, missing fields fail unless `allowUnknown:true`. Known/unknown operators explicitly test presence. Preference rules never exclude and missing values earn zero points. Exclude means “omit a positive match”; it is not proof the feature is absent.

## Description mentions

Use `field:"description", op:"mentions"`. Required settings:

- `terms`: one or more phrases; use synonyms as separate phrases.
- `match`: `any` or `all` phrases.
- `caseSensitive`: whether to preserve case during matching.
- `wholeWord`: require Unicode letter/number boundaries around a phrase, avoiding pool matching poolside.
- `ignoreNegated`: optionally ignore hits preceded by a small English negation lexicon.
- `negationWindow`: 0–12 preceding words, reset at `. ! ? ;` or a newline.
- `mode` and `allowUnknown`: same meanings as other rules.
- Optional `excludeTerms`: any such phrase anywhere makes this mention rule a non-match. This is a rule-local veto, not a global listing exclusion. Use a separate Exclude rule to reject those listings globally.
- Optional `weight`: 0–100 preference score.

Matching is literal phrase matching. It does not normalize hyphens, infer synonyms, infer amenities, extract amounts, or perform semantic AI interpretation. Negation is a heuristic, not language understanding; it may miss postposed negation or complex sentences and may over-filter phrases such as “not only.” Explicit exclusions and returned snippets help review ambiguity. No regular expressions are accepted, avoiding unbounded regex execution from imported files.

## Current source limitation

This is still a local snapshot of 782 records collected under the original scope: ZIP 33844, 20 miles, 2–3 bedrooms, rent at most $2,300. Query settings are no longer fixed: broader settings report partial coverage. A different location returns zero results rather than reusing distances from the wrong center. Only the exact location string `33844` currently resolves; free-form geocoding and live-source pagination are not implemented. Presets configure queries; they do not create unavailable source coverage.
