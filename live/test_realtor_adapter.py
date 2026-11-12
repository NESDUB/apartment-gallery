"""
Offline/mocked regression tests for realtor_adapter.py.

No network requests. Reuses the exact synthetic GraphQL response shape from
../../HomeHarvest-Boundary-Audit-2026-11-12/probe.py so these tests are
checked against the same documented defect, not a reinvented approximation
of it. Run with:

    /tmp/apartment-search-py313/bin/python test_realtor_adapter.py

Exits nonzero on any failed assertion; prints PASS per case otherwise.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeharvest.core.scrapers.realtor import RealtorScraper
from homeharvest.exceptions import AuthenticationError
import requests

import realtor_adapter as adapter

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        FAILED.append(name)
        print(f"FAIL  {name}  {detail}")


def fake_graphql(total, property_id_prefix="p"):
    """Matches probe.py's offline() fake exactly: a flat source of `total`
    rows, served in 200-row pages keyed by whatever offset the caller asks
    for the SOURCE graphql call (not our adapter's public offset=0 trick)."""

    def fake(self, query, variables, operation_name):
        offset = variables.get("offset", 0)
        rows = [
            {
                "property_id": f"{property_id_prefix}{i}",
                "href": f"https://example.test/{property_id_prefix}{i}",
                "flags": {},
                "description": {"beds": 2, "type": "apartment", "text": "desc"},
                "location": {
                    "address": {
                        "line": f"{i} Test St",
                        "city": "Haines City",
                        "postal_code": "33844",
                        "coordinate": {"lat": 28.08616, "lon": -81.58717},
                    }
                },
                "list_price": 1500,
                "last_update_date": "2026-11-01",
                "details": [],
                "tags": [],
            }
            for i in range(offset, min(offset + 200, total))
        ]
        return {"data": {"homeSearch": {"total": total, "results": rows}}}

    return fake


def test_pagination_bug_is_actually_fixed():
    """The audit's own documented reproduction cases, re-run through our
    adapter instead of the raw public API, to prove the workaround holds."""
    with patch.object(RealtorScraper, "handle_location", return_value={"text": "33844", "area_type": "postal_code"}), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql(115)
    ):
        # Audit case: offset=5, limit=5 against raw scrape_property returned 0.
        page = adapter.fetch_raw_window("33844", page_start=5, page_count=5)
        check(
            "offset5_count5_returns_5_not_0",
            len(page.records) == 5 and [r["property_id"] for r in page.records] == [f"p{i}" for i in range(5, 10)],
            f"got {[r.get('property_id') for r in page.records]}",
        )

        # Audit case: offset=10, limit=5 against raw scrape_property returned 100.
        page = adapter.fetch_raw_window("33844", page_start=10, page_count=5)
        check(
            "offset10_count5_returns_5_not_100",
            len(page.records) == 5 and [r["property_id"] for r in page.records] == [f"p{i}" for i in range(10, 15)],
            f"got {len(page.records)} records",
        )

        # Normal page boundary the audit also reproduced as broken (200,200 -> 0).
        page = adapter.fetch_raw_window("33844", page_start=0, page_count=115)
        check("full_window_returns_all_115", len(page.records) == 115, f"got {len(page.records)}")

        page = adapter.fetch_raw_window("33844", page_start=100, page_count=15)
        check(
            "tail_window_past_100_returns_last_15",
            [r["property_id"] for r in page.records] == [f"p{i}" for i in range(100, 115)],
            f"got {[r.get('property_id') for r in page.records]}",
        )


def test_source_total_semantics():
    with patch.object(RealtorScraper, "handle_location", return_value={"text": "33844", "area_type": "postal_code"}), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql(115)
    ):
        # Asking for exactly as many as exist is still ambiguous (we have no
        # out-of-band total — FINDINGS.md #1 — so matching exactly could
        # mean "that's all" or "we just didn't ask for more"). Only asking
        # for MORE than exists and getting back fewer proves exhaustion.
        page = adapter.fetch_raw_window("33844", page_start=0, page_count=115)
        check("exact_match_is_still_unknown_total", page.source_total == -1, f"got {page.source_total}")

        page = adapter.fetch_raw_window("33844", page_start=0, page_count=300)
        check("over_asking_reveals_true_total", page.source_total == 115, f"got {page.source_total}")

        # Asking for fewer than exist means we don't actually know the true total yet.
        page = adapter.fetch_raw_window("33844", page_start=0, page_count=5)
        check("total_unknown_flag_when_not_exhausted", page.source_total == -1, f"got {page.source_total}")


def test_multi_source_page_boundary():
    """Exercises the >200-row internal pagination path (two source pages)."""
    with patch.object(RealtorScraper, "handle_location", return_value={"text": "Orlando, FL", "area_type": "city"}), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql(450)
    ):
        page = adapter.fetch_raw_window("Orlando, FL", page_start=190, page_count=20)
        check(
            "spans_source_page_boundary_correctly",
            [r["property_id"] for r in page.records] == [f"p{i}" for i in range(190, 210)],
            f"got {[r.get('property_id') for r in page.records]}",
        )


def test_cap_rejected():
    try:
        adapter.fetch_raw_window("33844", page_start=9990, page_count=20)
        check("cap_exceeded_raises", False, "did not raise")
    except adapter.AdapterError as exc:
        check("cap_exceeded_raises", exc.kind == "cap_exceeded", exc.kind)


def test_error_classification():
    with patch.object(RealtorScraper, "handle_location", return_value={"text": "33844", "area_type": "postal_code"}):
        def raise_auth(self, query, variables, operation_name):
            raise AuthenticationError("blocked by source", response=None)

        with patch.object(RealtorScraper, "_graphql_post", raise_auth):
            try:
                adapter.fetch_raw_window("33844", 0, 5)
                check("auth_error_classified", False, "did not raise")
            except adapter.AdapterError as exc:
                check("auth_error_classified", exc.kind == "blocked", exc.kind)

        def raise_timeout(self, query, variables, operation_name):
            raise requests.exceptions.Timeout("simulated timeout")

        with patch.object(RealtorScraper, "_graphql_post", raise_timeout):
            try:
                adapter.fetch_raw_window("33844", 0, 5)
                check("timeout_classified", False, "did not raise")
            except adapter.AdapterError as exc:
                check("timeout_classified", exc.kind == "transport_error", exc.kind)


def test_location_unresolved():
    with patch.object(RealtorScraper, "handle_location", return_value=None):
        try:
            adapter.resolve_geography("Nowhereville, ZZ")
            check("unresolved_location_raises", False, "did not raise")
        except adapter.LocationUnresolved as exc:
            check("unresolved_location_raises", exc.kind == "location_unresolved", exc.kind)


def test_normalize_record_offer_matching():
    center = (28.08616, -81.58717)
    raw_with_matching_unit = {
        "property_id": "1",
        "href": "https://example.test/1",
        "description": {"type": "apartment", "text": "nice place"},
        "location": {"address": {"line": "1 Test St", "coordinate": {"lat": 28.08616, "lon": -81.58717}}},
        "units": [
            {"description": {"beds": 2, "baths": 2, "sqft": 900}, "list_price": 1500, "availability": {"date": None}},
            {"description": {"beds": 4, "baths": 3, "sqft": 1800}, "list_price": 2600, "availability": {"date": None}},
        ],
    }
    record, reason = adapter.normalize_record(raw_with_matching_unit, center, 20, 2, 3, 2300)
    check("matching_unit_accepted", record is not None and record["min_rent"] == 1500, reason)
    check("non_matching_unit_excluded_from_offers", len(record["offers"]) == 1 if record else False)

    raw_no_matching_unit = dict(raw_with_matching_unit)
    raw_no_matching_unit["units"] = [raw_with_matching_unit["units"][1]]  # only the 4BR/$2600 unit
    record, reason = adapter.normalize_record(raw_no_matching_unit, center, 20, 2, 3, 2300)
    check("building_rejected_when_no_unit_qualifies", record is None and reason == "no_bedroom_specific_price_match", reason)


def test_normalize_record_radius_rejection():
    center = (28.08616, -81.58717)
    far_away = {
        "property_id": "2",
        "href": "https://example.test/2",
        "description": {"type": "apartment", "beds": 2, "text": ""},
        "location": {"address": {"line": "far", "coordinate": {"lat": 40.7128, "lon": -74.0060}}},  # NYC
        "list_price": 1500,
    }
    record, reason = adapter.normalize_record(far_away, center, 20, 2, 3, 2300)
    check("far_away_record_rejected_by_radius", record is None and reason == "outside_radius", reason)

    record, reason = adapter.normalize_record(far_away, center, None, 2, 3, 2300)
    check("radius_filter_skipped_when_radius_none", record is not None, reason)


def test_normalize_record_property_type_and_coordinates():
    bad_type = {"property_id": "3", "description": {"type": "single_family"}}
    record, reason = adapter.normalize_record(bad_type, None, None, 2, 3, 2300)
    check("wrong_property_type_rejected", record is None and reason == "wrong_property_type", reason)

    missing_coords = {"property_id": "4", "description": {"type": "apartment"}, "location": {"address": {}}}
    record, reason = adapter.normalize_record(missing_coords, None, None, 2, 3, 2300)
    check("missing_coordinates_rejected", record is None and reason == "missing_coordinates", reason)


def test_age_and_income_restriction_flags():
    base = {
        "property_id": "5",
        "href": "https://example.test/5",
        "description": {"type": "apartment", "text": "", "name": ""},
        "location": {"address": {"line": "5 Test St", "coordinate": {"lat": 28.08616, "lon": -81.58717}}},
        "list_price": 1500,
        "units": [{"description": {"beds": 2}, "list_price": 1500}],
    }

    age = dict(base)
    age["description"] = {"type": "apartment", "text": "A 55+ active adult community.", "name": "Sunset Villas"}
    record, _ = adapter.normalize_record(age, None, None, 2, 3, 2300)
    check("age_restriction_detected", record["age_restricted"] is True, record["flags"])
    check("age_flag_present", any("Age eligibility" in f for f in record["flags"]))

    income = dict(base)
    income["description"] = {"type": "apartment", "text": "Income restricted; affordable housing program.", "name": ""}
    record, _ = adapter.normalize_record(income, None, None, 2, 3, 2300)
    check("income_restriction_detected", record["income_restricted"] is True, record["flags"])

    plain = dict(base)
    plain["description"] = {"type": "apartment", "text": "A nice place to live.", "name": "Normal Apartments"}
    record, _ = adapter.normalize_record(plain, None, None, 2, 3, 2300)
    check("no_false_positive_restriction", record["age_restricted"] is False and record["income_restricted"] is False, record)


def test_street_address_withheld_flag():
    no_address = {
        "property_id": "6",
        "href": "https://example.test/6",
        "description": {"type": "apartment", "text": "", "name": "Some Complex"},
        "location": {"address": {"coordinate": {"lat": 28.08616, "lon": -81.58717}}},  # no "line"
        "units": [{"description": {"beds": 2}, "list_price": 1500}],
    }
    record, _ = adapter.normalize_record(no_address, None, None, 2, 3, 2300)
    check("street_withheld_flag_present", any("Street address withheld" in f for f in record["flags"]), record["flags"])


def test_cover_url_and_photo_count_default_unset():
    """normalize_record never fetches photos itself (that's photo_adapter's
    job, run separately) — confirms it doesn't silently fabricate either."""
    base = {
        "property_id": "7",
        "href": "https://example.test/7",
        "description": {"type": "apartment", "text": "", "name": "X"},
        "location": {"address": {"line": "7 Test St", "coordinate": {"lat": 28.08616, "lon": -81.58717}}},
        "units": [{"description": {"beds": 2}, "list_price": 1500}],
    }
    record, _ = adapter.normalize_record(base, None, None, 2, 3, 2300)
    check("cover_url_unset_by_default", record["cover_url"] is None, record["cover_url"])
    check("photo_count_zero_by_default", record["photo_count"] == 0, record["photo_count"])


def test_haversine_matches_build_report_center():
    # Known pair used throughout the existing snapshot tooling: center to itself is 0.
    d = adapter.haversine_miles(28.08616, -81.58717, 28.08616, -81.58717)
    check("haversine_self_distance_zero", abs(d) < 1e-9, d)
    # Rough sanity bound: Haines City, FL to Orlando, FL is on the order of 35-45 miles.
    d2 = adapter.haversine_miles(28.08616, -81.58717, 28.5383, -81.3792)
    check("haversine_haines_city_to_orlando_plausible", 30 < d2 < 55, d2)


if __name__ == "__main__":
    test_pagination_bug_is_actually_fixed()
    test_source_total_semantics()
    test_multi_source_page_boundary()
    test_cap_rejected()
    test_error_classification()
    test_location_unresolved()
    test_normalize_record_offer_matching()
    test_normalize_record_radius_rejection()
    test_normalize_record_property_type_and_coordinates()
    test_age_and_income_restriction_flags()
    test_street_address_withheld_flag()
    test_cover_url_and_photo_count_default_unset()
    test_haversine_matches_build_report_center()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("All checks passed.")
