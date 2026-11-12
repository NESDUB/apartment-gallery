"""
Offline/mocked tests for photo_adapter.py. No network requests.

    /tmp/apartment-search-py313/bin/python test_photo_adapter.py
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import photo_adapter

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        FAILED.append(name)
        print(f"FAIL  {name}  {detail}")


def fake_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status.side_effect = None
    return resp


def test_single_batch_success():
    payload = {
        "data": {
            "p0": {"property_id": "1", "photos": [{"href": "https://ap.rdcpix.com/a.jpg", "title": "Front", "tags": [{"label": "exterior"}]}]},
            "p1": {"property_id": "2", "photos": []},
        }
    }
    with patch("requests.Session.post", return_value=fake_response(payload)):
        result = photo_adapter.fetch_photos(["1", "2"])
    check("photos_attached_for_id_1", result.by_property_id.get("1") == [{"url": "https://ap.rdcpix.com/a.jpg", "title": "Front", "tags": ["exterior"]}], result.by_property_id)
    check("empty_photo_list_for_id_2", result.by_property_id.get("2") == [], result.by_property_id)
    check("no_errors", result.errors == {}, result.errors)


def test_missing_home_record_becomes_error():
    payload = {"data": {"p0": None}}
    with patch("requests.Session.post", return_value=fake_response(payload)):
        result = photo_adapter.fetch_photos(["1"])
    check("missing_record_is_an_error_not_a_crash", "1" in result.errors, result.errors)
    check("missing_record_not_in_results", "1" not in result.by_property_id)


def test_transport_failure_marks_whole_batch_as_errors():
    with patch("requests.Session.post", side_effect=Exception("connection reset")):
        result = photo_adapter.fetch_photos(["1", "2", "3"])
    check("transport_failure_errors_all_ids", set(result.errors) == {"1", "2", "3"}, result.errors)
    check("transport_failure_no_results", result.by_property_id == {})


def test_batching_splits_into_groups_of_20():
    calls = []

    def fake_post(self, url, json, timeout):
        calls.append(json["query"].count("home(property_id:"))
        return fake_response({"data": {f"p{i}": {"property_id": str(i), "photos": []} for i in range(json["query"].count("home(property_id:"))}})

    ids = [str(i) for i in range(45)]  # 20 + 20 + 5
    with patch("requests.Session.post", fake_post):
        photo_adapter.fetch_photos(ids)
    check("three_batches_sent", len(calls) == 3, calls)
    check("batch_sizes_20_20_5", calls == [20, 20, 5], calls)


def test_attach_covers_sets_first_photo_and_count():
    records = [
        {"property_id": "1", "cover_url": None, "photo_count": 0},
        {"property_id": "2", "cover_url": None, "photo_count": 0},
    ]
    photos_by_id = {
        "1": [{"url": "https://ap.rdcpix.com/a.jpg", "title": "a", "tags": []}, {"url": "https://ap.rdcpix.com/b.jpg", "title": "b", "tags": []}],
    }
    photo_adapter.attach_covers(records, photos_by_id)
    check("cover_set_for_id_1", records[0]["cover_url"] == "https://ap.rdcpix.com/a.jpg", records[0])
    check("photo_count_set_for_id_1", records[0]["photo_count"] == 2, records[0])
    check("id_2_stays_unset_when_no_photo_data", records[1]["cover_url"] is None and records[1]["photo_count"] == 0, records[1])


if __name__ == "__main__":
    test_single_batch_success()
    test_missing_home_record_becomes_error()
    test_transport_failure_marks_whole_batch_as_errors()
    test_batching_splits_into_groups_of_20()
    test_attach_covers_sets_first_photo_and_count()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("All checks passed.")
