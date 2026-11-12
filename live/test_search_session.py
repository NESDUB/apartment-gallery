"""
Offline/mocked tests for search_session.py (Phase B). No network requests.
Mocks at the same RealtorScraper boundary as test_realtor_adapter.py, so
these exercise the real adapter code path underneath, not a stand-in.

    /tmp/apartment-search-py313/bin/python test_search_session.py
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeharvest.core.scrapers.realtor import RealtorScraper
from homeharvest.exceptions import AuthenticationError

import realtor_adapter as adapter
from search_session import SearchManager, SearchParams, SessionState

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        FAILED.append(name)
        print(f"FAIL  {name}  {detail}")


def fake_graphql_building(total, beds=2, price=1500, property_type="apartment"):
    def fake(self, query, variables, operation_name):
        offset = variables.get("offset", 0)
        rows = [
            {
                "property_id": f"p{i}",
                "href": f"https://example.test/{i}",
                "description": {"beds": beds, "type": property_type, "text": "desc"},
                "location": {
                    "address": {
                        "line": f"{i} Test St",
                        "city": "Haines City",
                        "postal_code": "33844",
                        "coordinate": {"lat": 28.08616, "lon": -81.58717},
                    }
                },
                "list_price": price,
                "last_update_date": "2026-11-01",
                "details": [],
                "tags": [],
            }
            for i in range(offset, min(offset + 200, total))
        ]
        return {"data": {"homeSearch": {"total": total, "results": rows}}}

    return fake


LOCATION_OK = {"text": "33844", "area_type": "postal_code", "centroid": {"lat": 28.08616, "lon": -81.58717}}


def fake_empty_photo_response(*args, **kwargs):
    """Session.step() now also fetches photos per matched record
    (photo_adapter.fetch_photos) — these tests are about session
    lifecycle, not photo content (see test_photo_adapter.py for that), so
    every batch here just returns an empty photo list for each id asked
    for. Patched globally for this whole file to keep it a real offline
    test — without this, fetch_photos would make live network calls.
    """
    query = kwargs.get("json", {}).get("query", "")
    count = query.count("home(property_id:")
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.side_effect = None
    resp.json.return_value = {"data": {f"p{i}": {"property_id": str(i), "photos": []} for i in range(count)}}
    return resp


def params(**overrides):
    base = dict(location="33844", radius_miles=20, beds_min=2, beds_max=3, price_max=2300, step_size=50, max_raw_records=500, max_wall_seconds=60)
    base.update(overrides)
    return SearchParams(**base)


def test_normal_completion_across_multiple_steps():
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=120)
    ):
        mgr = SearchManager()
        sid = mgr.create(params())

        snap1 = mgr.step(sid)
        check("step1_more_available", snap1["state"] == "more_available", snap1["state"])
        check("step1_raw_checked_50", snap1["raw_checked_count"] == 50, snap1["raw_checked_count"])
        check("step1_matched_50", snap1["unique_matched_count"] == 50, snap1["unique_matched_count"])

        snap2 = mgr.step(sid)
        check("step2_raw_checked_100", snap2["raw_checked_count"] == 100, snap2["raw_checked_count"])
        check("step2_still_more_available", snap2["state"] == "more_available", snap2["state"])

        snap3 = mgr.step(sid)
        # 100 + 50 requested = 150, but source only has 120 -> exhausted -> complete.
        check("step3_complete", snap3["state"] == "complete", snap3["state"])
        check("step3_matched_120_not_150", snap3["unique_matched_count"] == 120, snap3["unique_matched_count"])

        # step() on an already-complete session is a harmless no-op.
        snap4 = mgr.step(sid)
        check("step_after_complete_is_noop", snap4 == snap3 or snap4["state"] == "complete")


def test_no_matches_still_advances_raw_position():
    """A page where nothing matches (wrong beds) must not look exhausted or
    stuck — raw_checked_count still advances, state stays more_available."""
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=500, beds=5)  # never matches beds 2-3
    ):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50))
        snap = mgr.step(sid)
        check("zero_matches_but_advances", snap["raw_checked_count"] == 50 and snap["unique_matched_count"] == 0, snap)
        check("zero_matches_state_more_available", snap["state"] == "more_available", snap["state"])


def test_unresolved_location_fails_immediately():
    with patch.object(RealtorScraper, "handle_location", return_value=None):
        mgr = SearchManager()
        sid = mgr.create(params(location="Nowhereville, ZZ"))
        snap = mgr.step(sid)
        check("unresolved_fails", snap["state"] == "failed", snap["state"])
        check("unresolved_error_recorded", snap["errors"] and snap["errors"][0]["kind"] == "location_unresolved", snap["errors"])


def test_failure_mid_session_keeps_prior_matches():
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50))

        with patch.object(RealtorScraper, "_graphql_post", fake_graphql_building(total=500)):
            snap1 = mgr.step(sid)
            check("pre_failure_matched_50", snap1["unique_matched_count"] == 50, snap1)

        def raise_auth(self, query, variables, operation_name):
            raise AuthenticationError("blocked", response=None)

        with patch.object(RealtorScraper, "_graphql_post", raise_auth):
            snap2 = mgr.step(sid)
            check("failure_state_is_failed", snap2["state"] == "failed", snap2["state"])
            check("failure_keeps_prior_50_matches", snap2["unique_matched_count"] == 50, snap2["unique_matched_count"])
            check("failure_raw_checked_count_unchanged", snap2["raw_checked_count"] == 50, snap2["raw_checked_count"])


def test_cancellation_blocks_further_steps():
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=500)
    ):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50))
        mgr.step(sid)
        mgr.cancel(sid)
        snap_after_cancel = mgr.step(sid)
        check("canceled_state", snap_after_cancel["state"] == "canceled", snap_after_cancel["state"])
        check(
            "canceled_raw_checked_frozen",
            snap_after_cancel["raw_checked_count"] == 50,
            snap_after_cancel["raw_checked_count"],
        )


def test_budget_limited_raw_records():
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=5000)
    ):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50, max_raw_records=120))
        mgr.step(sid)  # 50
        mgr.step(sid)  # 100
        snap = mgr.step(sid)  # would be 150, capped to 20 more -> 120, hits budget
        check("budget_caps_raw_checked_at_max", snap["raw_checked_count"] == 120, snap["raw_checked_count"])
        check("budget_state_limited", snap["state"] == "limited", snap["state"])

        snap2 = mgr.step(sid)
        check("limited_session_step_is_noop", snap2["raw_checked_count"] == 120 and snap2["state"] == "limited")


def test_offer_matching_integration_through_session():
    """End-to-end through the session: a building whose only unit is
    outside beds/price must not appear in matched_records, matching
    Phase A's normalize_record contract."""
    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=10, beds=4, price=5000)
    ):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50))
        snap = mgr.step(sid)
        check("non_matching_offers_excluded", snap["unique_matched_count"] == 0, snap)
        check("source_still_fully_checked", snap["raw_checked_count"] == 10, snap["raw_checked_count"])
        check("exhausted_short_page_marks_complete", snap["state"] == "complete", snap["state"])


def test_covers_attached_and_get_photos_available():
    def fake_photo_response(*args, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        count = query.count("home(property_id:")
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.side_effect = None
        resp.json.return_value = {
            "data": {
                f"p{i}": {
                    "property_id": str(i),
                    "photos": [{"href": f"https://ap.rdcpix.com/{i}-a.jpg", "title": "Front", "tags": []}],
                }
                for i in range(count)
            }
        }
        return resp

    with patch.object(RealtorScraper, "handle_location", return_value=LOCATION_OK), patch.object(
        RealtorScraper, "_graphql_post", fake_graphql_building(total=5)
    ), patch("requests.Session.post", side_effect=fake_photo_response):
        mgr = SearchManager()
        sid = mgr.create(params(step_size=50))
        snap = mgr.step(sid)
        first = snap["matched_records"][0]
        check("cover_url_attached_via_session", first["cover_url"] is not None, first)
        check("photo_count_attached_via_session", first["photo_count"] == 1, first)

        photos = mgr.get_photos(sid, first["property_id"])
        check("get_photos_returns_cached_list", photos == [{"url": f"https://ap.rdcpix.com/{first['property_id'][1:]}-a.jpg", "title": "Front", "tags": []}], photos)

        check("get_photos_unknown_property_returns_none", mgr.get_photos(sid, "does-not-exist") is None)
        check("get_photos_unknown_session_returns_none", mgr.get_photos("bad-session-id", first["property_id"]) is None)


if __name__ == "__main__":
    with patch("requests.Session.post", side_effect=fake_empty_photo_response):
        test_normal_completion_across_multiple_steps()
        test_no_matches_still_advances_raw_position()
        test_unresolved_location_fails_immediately()
        test_failure_mid_session_keeps_prior_matches()
        test_cancellation_blocks_further_steps()
        test_budget_limited_raw_records()
        test_offer_matching_integration_through_session()
    test_covers_attached_and_get_photos_available()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("All checks passed.")
