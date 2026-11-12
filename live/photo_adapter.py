"""
Photo-URL fetching for live search results.

Mirrors the exact technique the original offline search used
(../../Apartment-Search-33844-2026-11-12/fetch_original_photo_catalog.py):
a single GraphQL query with up to 20 aliased home(property_id:...)
sub-queries, each requesting photos(size:MAX, https:true) — the field
that was confirmed live to return correct, working full-resolution CDN
URLs (README's "Photo behavior" section; guessed o.jpg suffixes often
failed). This bypasses HomeHarvest's own extra_property_data path
entirely (that one is forced off — FINDINGS.md #7) by posting the same
GraphQL request HomeHarvest's own scraper would, directly.

This only fetches the photo URL *list* (href/title/tags), not image
bytes — the actual <img> tags still load lazily client-side exactly as
the existing snapshot app already does. Fetching the URL list for a
whole page of search results up front is cheap (a few KB of JSON) and
is what lets a grid of cards show a cover photo immediately without a
separate round-trip per card hover/open.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests
from homeharvest.core.scrapers import DEFAULT_HEADERS

GRAPHQL_URL = "https://www.realtor.com/frontdoor/graphql"
BATCH_SIZE = 20
HTTP_TIMEOUT = (10, 20)


@dataclass
class PhotoResult:
    by_property_id: dict  # property_id -> list[{"url","title","tags"}]
    errors: dict  # property_id -> error message
    elapsed_s: float


def fetch_photos(property_ids: list) -> PhotoResult:
    """Batched fetch of full photo lists for up to many property_ids.
    Never raises on a per-property failure — missing/erroring ids just
    end up in `errors`, consistent with the adapter's "missing is not
    false" principle elsewhere in this project.
    """
    start = time.monotonic()
    by_id: dict = {}
    errors: dict = {}
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for batch_start in range(0, len(property_ids), BATCH_SIZE):
        batch = property_ids[batch_start : batch_start + BATCH_SIZE]
        fields = " ".join(
            f'p{i}:home(property_id:"{pid}") {{ property_id photos(size:MAX,https:true){{href title tags{{label}}}} }}'
            for i, pid in enumerate(batch)
        )
        query = "query GetHomeDetails { " + fields + " }"
        try:
            response = session.post(
                GRAPHQL_URL,
                json={"operationName": "GetHomeDetails", "query": query, "variables": {}},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - classify per-id, don't crash the whole batch
            for pid in batch:
                errors[pid] = str(exc)
            continue

        for i, pid in enumerate(batch):
            item = (data.get("data") or {}).get(f"p{i}")
            if item is None:
                errors[pid] = str(data.get("errors") or "No home record returned")
                continue
            photos = item.get("photos") or []
            by_id[pid] = [
                {
                    "url": photo.get("href"),
                    "title": photo.get("title"),
                    "tags": [t.get("label") for t in (photo.get("tags") or []) if t.get("label")],
                }
                for photo in photos
                if photo.get("href")
            ]

    return PhotoResult(by_property_id=by_id, errors=errors, elapsed_s=time.monotonic() - start)


def attach_covers(records: list, photos_by_id: dict) -> None:
    """Mutates each record in place: sets cover_url to the first photo and
    photo_count to the real count, for any record whose id is in
    photos_by_id. Records with no photo data (not fetched, or a fetch
    error) keep cover_url=None / photo_count=0 — the honest "no photo"
    state the existing app.js card() renderer already handles
    (shows "No source photos" rather than a broken image).
    """
    for record in records:
        photos = photos_by_id.get(record["property_id"])
        if photos:
            record["cover_url"] = photos[0]["url"]
            record["photo_count"] = len(photos)
