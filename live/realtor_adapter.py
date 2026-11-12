"""
Tested retrieval adapter for Realtor.com rental listings via HomeHarvest.

Why this exists (see ../../HomeHarvest-Boundary-Audit-2026-11-12/FINDINGS.md
for the full measured audit this is built from): installed HomeHarvest 0.8.18
has a confirmed pagination defect. In
homeharvest/core/scrapers/realtor/__init__.py, general_search() does:

    properties_list = properties_list[: self.limit - offset]

where `offset` is THIS GraphQL page's own offset variable and `self.limit`
is the caller's original total requested count, held constant across pages.
That formula is only correct when the top-level requested offset is 0 (so
the per-page `offset` variable always equals how many rows have already
been consumed). Call scrape_property(offset=5, limit=5) directly and it
slices properties_list[:5-5] = properties_list[:0] -> 0 rows, even though
115 source rows exist. Call offset=10, limit=5 and it slices
properties_list[:5-10] = properties_list[:-5] -> ~100 rows via negative
slicing. Both reproduced live against the real service (FINDINGS.md #3).

Workaround used here (NOT a patch to the installed package — nothing under
site-packages is modified): always call scrape_property with offset=0 and
limit=page_start+page_count. Because the top-level offset is 0, every page
HomeHarvest fetches internally keeps the buggy formula numerically correct
(each page's own `offset` variable equals exactly how many rows have been
consumed so far, which is what the formula assumes). We then slice the
returned list ourselves to [page_start:page_start+page_count]. This is
verified against the audit's own reproduction cases in
test_realtor_adapter.py before being trusted for anything live.

This module also fixes the audit's other confirmed defects for our own
use: it classifies errors instead of treating every failure as an empty
result (FINDINGS.md #6), it resolves geography explicitly and applies
a local haversine radius filter instead of trusting HomeHarvest's radius
parameter against a plain ZIP/area search (FINDINGS.md #2 — radius is a
no-op unless the resolved location is an address), and it classifies
listings by the same per-offer matching logic the original snapshot used
(see ../../Apartment-Search-33844-2026-11-12/build_report.py) so results
in the new path have the same shape as the existing dist/data/listings/*
records.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from homeharvest import scrape_property
from homeharvest.core.scrapers import ScraperInput
from homeharvest.core.scrapers.models import ListingType, ReturnType
from homeharvest.core.scrapers.realtor import RealtorScraper
from homeharvest.exceptions import AuthenticationError

SOURCE_PAGE_SIZE = 200  # HomeHarvest's own fixed GraphQL page size (confirmed in FINDINGS.md #4).
SOURCE_CAP = 10_000  # HomeHarvest's own validator cap (FINDINGS.md #9) — not independently stress-tested.
RADIUS_EARTH_MILES = 3958.7613
HTTP_TIMEOUT = (10, 20)  # (connect, read) seconds — HomeHarvest sets none itself (FINDINGS.md).

QUALIFYING_PROPERTY_TYPES = {"apartment", "condos", "townhomes", "multi_family", "duplex_triplex"}

# Same heuristics as ../../Apartment-Search-33844-2026-11-12/build_report.py,
# kept identical on purpose so a live record and a snapshot record flag the
# same way for the same text.
AGE_RESTRICTION_PATTERN = re.compile(r"55\+|62\+|active adult|age[- ]restricted|senior living", re.I)
INCOME_RESTRICTION_PATTERN = re.compile(
    r"income restriction|income restricted|income limitations|restricted-income|affordable housing program|income qualification",
    re.I,
)


class AdapterError(Exception):
    """Base for classified adapter failures. `kind` is a stable machine-readable tag."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class LocationUnresolved(AdapterError):
    def __init__(self, location: str):
        super().__init__("location_unresolved", f"Could not resolve location {location!r} to a known area.")
        self.location = location


class SourceBlocked(AdapterError):
    def __init__(self, message: str):
        super().__init__("blocked", message)


class SourceRateLimited(AdapterError):
    def __init__(self, message: str):
        super().__init__("rate_limited", message)


class SourceTransportError(AdapterError):
    def __init__(self, message: str):
        super().__init__("transport_error", message)


class SourceMalformedResponse(AdapterError):
    def __init__(self, message: str):
        super().__init__("malformed_response", message)


@dataclass
class GeoResolution:
    requested_location: str
    resolved_text: Optional[str]
    area_type: Optional[str]
    city: Optional[str]
    state_code: Optional[str]
    postal_code: Optional[str]
    centroid: Optional[tuple] = None  # (lat, lon)


@dataclass
class RawPage:
    """One correctly-sliced window of raw HomeHarvest property dicts."""

    records: list
    source_total: int
    page_start: int
    page_count_requested: int
    elapsed_s: float


@dataclass
class NormalizedWindow:
    geo: GeoResolution
    source_total: int
    raw_count_this_page: int
    radius_rejected_count: int
    matched_count: int
    records: list
    page_start: int
    page_count_requested: int
    elapsed_s: float


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance, matching build_report.py's CENTER-based formula exactly
    (same constant, same clamp against float rounding pushing asin above domain)."""
    a, b, c, d = map(math.radians, [lat1, lon1, lat2, lon2])
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return RADIUS_EARTH_MILES * 2 * math.asin(min(1, math.sqrt(h)))


def _classify_transport_exception(exc: Exception) -> AdapterError:
    if isinstance(exc, AuthenticationError):
        return SourceBlocked(str(exc))
    if isinstance(exc, requests.exceptions.Timeout):
        return SourceTransportError(f"Timed out: {exc}")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return SourceTransportError(f"Connection failed: {exc}")
    if isinstance(exc, requests.exceptions.HTTPError):
        return SourceTransportError(f"HTTP error: {exc}")
    return SourceTransportError(f"{type(exc).__name__}: {exc}")


def resolve_geography(location: str) -> GeoResolution:
    """Resolve a location string the same way HomeHarvest's own search does
    (via its SEARCH_GQL_URL search_suggestions call), without running a full
    property search. Raises LocationUnresolved on no match, or a classified
    AdapterError on transport failure.
    """
    scraper_input = ScraperInput(
        location=location,
        listing_type=ListingType.FOR_RENT,
        return_type=ReturnType.raw,
    )
    scraper = RealtorScraper(scraper_input)

    original_post = requests.post

    def bounded_post(*args, **kwargs):
        kwargs.setdefault("timeout", HTTP_TIMEOUT)
        return original_post(*args, **kwargs)

    requests.post = bounded_post
    try:
        info = scraper.handle_location()
    except Exception as exc:  # noqa: BLE001 - must classify, not crash
        raise _classify_transport_exception(exc) from exc
    finally:
        requests.post = original_post

    if not info:
        raise LocationUnresolved(location)

    centroid = None
    raw_centroid = info.get("centroid")
    if isinstance(raw_centroid, dict) and isinstance(raw_centroid.get("lat"), (int, float)) and isinstance(
        raw_centroid.get("lon"), (int, float)
    ):
        centroid = (raw_centroid["lat"], raw_centroid["lon"])

    return GeoResolution(
        requested_location=location,
        resolved_text=info.get("text"),
        area_type=info.get("area_type"),
        city=info.get("city"),
        state_code=info.get("state_code"),
        postal_code=info.get("postal_code"),
        centroid=centroid,
    )


def fetch_raw_window(
    location: str,
    page_start: int,
    page_count: int,
    beds_min: Optional[int] = None,
    beds_max: Optional[int] = None,
    price_max: Optional[int] = None,
    price_min: Optional[int] = None,
) -> RawPage:
    """Fetch exactly [page_start:page_start+page_count) raw source rows,
    working around the installed HomeHarvest pagination defect (see module
    docstring). Always requests offset=0 internally; slices ourselves.
    """
    if page_start < 0 or page_count <= 0:
        raise ValueError("page_start must be >= 0 and page_count must be > 0")
    end = page_start + page_count
    if end > SOURCE_CAP:
        raise AdapterError(
            "cap_exceeded",
            f"page_start+page_count={end} exceeds HomeHarvest's {SOURCE_CAP} source cap "
            "(FINDINGS.md #9) — narrow the query instead of paging past it.",
        )

    captured_total = {"value": None}
    start = time.monotonic()

    import homeharvest.core.scrapers.realtor as realtor_module

    original_post = realtor_module.requests.post

    def bounded_post(*args, **kwargs):
        kwargs.setdefault("timeout", HTTP_TIMEOUT)
        return original_post(*args, **kwargs)

    realtor_module.requests.post = bounded_post
    try:
        raw = scrape_property(
            location=location,
            listing_type="for_rent",
            return_type="raw",
            extra_property_data=False,
            parallel=False,
            offset=0,
            limit=end,
            beds_min=beds_min,
            beds_max=beds_max,
            price_max=price_max,
            price_min=price_min,
        )
    except Exception as exc:  # noqa: BLE001 - must classify, not crash
        raise _classify_transport_exception(exc) from exc
    finally:
        realtor_module.requests.post = original_post

    elapsed = time.monotonic() - start

    # scrape_property(return_type="raw") returns a plain list; there is no
    # public total/cursor (FINDINGS.md #1). We only know "at least len(raw)"
    # unless raw is short of `end`, in which case that IS the true total
    # (the source ran out before our requested end).
    source_total_known = len(raw) < end
    window = raw[page_start:end]

    return RawPage(
        records=window,
        source_total=len(raw) if source_total_known else -1,  # -1 = "at least len(raw)", unknown true total
        page_start=page_start,
        page_count_requested=page_count,
        elapsed_s=elapsed,
    )


def _best_matching_offers(raw: dict, beds_min: int, beds_max: int, price_max: float, price_min: float = 0) -> list:
    """Same per-offer matching logic as build_report.py: a building/record
    only counts if at least one of its own offers (unit-level if present,
    else the building-level listing itself) jointly satisfies beds+price.
    Mirrors FINDINGS.md #8's requirement that offer-level rules match one
    eligible unit rather than substituting a building-minimum price.
    """
    offers = []
    for unit in raw.get("units") or []:
        unit_desc = unit.get("description") or {}
        beds = unit_desc.get("beds")
        rent = unit.get("list_price")
        if beds in range(beds_min, beds_max + 1) and isinstance(rent, (int, float)) and price_min < rent <= price_max:
            offers.append(
                {
                    "beds": beds,
                    "baths": unit_desc.get("baths"),
                    "rent": rent,
                    "sqft": unit_desc.get("sqft"),
                    "availability": (unit.get("availability") or {}).get("date"),
                    "level": "community unit/floor-plan feed; exact unit number not supplied",
                }
            )

    if not offers:
        desc = raw.get("description") or {}
        list_price = raw.get("list_price")
        if (
            desc.get("beds") in range(beds_min, beds_max + 1)
            and isinstance(list_price, (int, float))
            and price_min < list_price <= price_max
        ):
            baths = (desc.get("baths_full") or 0) + (desc.get("baths_half") or 0) * 0.5
            offers.append(
                {
                    "beds": desc["beds"],
                    "baths": baths or None,
                    "rent": list_price,
                    "sqft": desc.get("sqft"),
                    "availability": None,
                    "level": "individual listing",
                }
            )

    # Dedup identical offers the same way build_report.py does.
    deduped = list({(o["beds"], o["baths"], o["rent"], o["sqft"], o["availability"]): o for o in offers}.values())
    deduped.sort(key=lambda o: (o["beds"], o["rent"], o.get("sqft") or 0))
    return deduped


def normalize_record(raw: dict, center: tuple, radius_miles: Optional[float], beds_min: int, beds_max: int, price_max: float, price_min: float = 0):
    """Returns a dict shaped like the existing dist/data/listings/<id>.json
    records, or None if the record doesn't qualify (wrong property type,
    missing coordinates, outside radius, or no offer matches beds+price).
    `center`/`radius_miles` may be None to skip the local radius filter
    (e.g. an address-exact search where HomeHarvest's own radius applies).
    """
    desc = raw.get("description") or {}
    kind = desc.get("type")
    if kind not in QUALIFYING_PROPERTY_TYPES:
        return None, "wrong_property_type"

    addr = (raw.get("location") or {}).get("address") or {}
    geo = addr.get("coordinate") or {}
    lat, lon = geo.get("lat"), geo.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None, "missing_coordinates"

    distance_miles = None
    if center is not None:
        distance_miles = haversine_miles(center[0], center[1], lat, lon)
        if radius_miles is not None and distance_miles > radius_miles:
            return None, "outside_radius"

    offers = _best_matching_offers(raw, beds_min, beds_max, price_max, price_min)
    if not offers:
        return None, "no_bedroom_specific_price_match"

    key = str(raw.get("property_id") or raw.get("href"))
    name = desc.get("name") or addr.get("line") or "Address withheld"
    text = desc.get("text") or ""
    age_restricted = bool(AGE_RESTRICTION_PATTERN.search(name + " " + text))
    income_restricted = bool(INCOME_RESTRICTION_PATTERN.search(text))
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    flags = []
    if age_restricted:
        flags.append("Age eligibility restriction disclosed; not included in general shortlist")
    if income_restricted:
        flags.append("Income/affordable-housing eligibility must be checked")
    if any(o["sqft"] and (o["sqft"] > 2500 or o["sqft"] < 500) for o in offers):
        flags.append("Questionable area: may be whole building or lot rather than rental unit")
    if any(o["availability"] and o["availability"] > today for o in offers):
        flags.append("Some options are future availability")
    if not addr.get("line"):
        flags.append("Street address withheld")

    record = {
        "property_id": key,
        "name": name,
        "is_named": bool(desc.get("name")),
        "property_type": kind,
        "address": addr.get("line"),
        "unit": addr.get("unit"),
        "city": addr.get("city"),
        "zip": addr.get("postal_code"),
        "coordinates": {"lat": lat, "lon": lon},
        "radius_miles": round(distance_miles, 2) if distance_miles is not None else None,
        "url": raw.get("href"),
        "source_last_updated": raw.get("last_update_date"),
        "offers": offers,
        "details": [t for group in raw.get("details") or [] for t in group.get("text") or []],
        "tags": raw.get("tags") or [],
        "description": text,
        "age_restricted": age_restricted,
        "income_restricted": income_restricted,
        "flags": flags,
        "min_rent": min(o["rent"] for o in offers),
        "cover_url": None,  # filled in by photo_adapter.attach_covers() — not fetched here
        "photo_count": 0,
    }
    return record, None


def fetch_normalized_window(
    location: str,
    radius_miles: Optional[float],
    beds_min: int,
    beds_max: int,
    price_max: float,
    page_start: int,
    page_count: int,
    price_min: float = 0,
    geo: Optional[GeoResolution] = None,
) -> NormalizedWindow:
    """Full pipeline for one page: resolve geography (unless already
    resolved and passed in, so a multi-page caller doesn't re-resolve every
    call), fetch the raw window, apply local radius + offer matching.

    page_start/page_count are in RAW SOURCE POSITION terms (FINDINGS.md
    acceptance gate: "Source pages advance by raw source positions, not by
    how many rows survive local filters") — callers paging through results
    must advance page_start by page_count regardless of how many records
    in a given page end up matching.
    """
    if geo is None:
        geo = resolve_geography(location)

    center = geo.centroid
    raw_page = fetch_raw_window(
        location=location,
        page_start=page_start,
        page_count=page_count,
        beds_min=beds_min,
        beds_max=beds_max,
        price_max=price_max,
        price_min=price_min,
    )

    records = []
    radius_rejected = 0
    for raw in raw_page.records:
        normalized, reason = normalize_record(raw, center, radius_miles, beds_min, beds_max, price_max, price_min)
        if normalized is not None:
            records.append(normalized)
        elif reason == "outside_radius":
            radius_rejected += 1

    return NormalizedWindow(
        geo=geo,
        source_total=raw_page.source_total,
        raw_count_this_page=len(raw_page.records),
        radius_rejected_count=radius_rejected,
        matched_count=len(records),
        records=records,
        page_start=page_start,
        page_count_requested=page_count,
        elapsed_s=raw_page.elapsed_s,
    )
