"""
Bounded live verification of realtor_adapter.py against the real service.

Mirrors the audit's own restraint (../../HomeHarvest-Boundary-Audit-2026-11-12
/probe.py, run_live_suite.py): a small fixed number of sequential live calls,
10/20s connect/read timeouts, no proxies, no repeated stress-testing. Run
this by hand when verifying a change — not on every test run, and not in a
loop.

    /tmp/apartment-search-py313/bin/python live_verify.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import realtor_adapter as adapter

ROOT = Path(__file__).resolve().parent


def main():
    results = {}

    print("1. Resolving geography for 33844...")
    geo = adapter.resolve_geography("33844")
    results["geo_33844"] = {
        "resolved_text": geo.resolved_text,
        "area_type": geo.area_type,
        "centroid": geo.centroid,
    }
    print(f"   -> {results['geo_33844']}")
    assert geo.centroid is not None, "Expected a centroid for 33844 (needed for radius filtering)"

    print("\n2. Re-running the audit's own documented-broken live case: offset=5, count=5...")
    page = adapter.fetch_raw_window("33844", page_start=5, page_count=5, beds_min=2, beds_max=3, price_max=2300)
    ids_5_5 = [r.get("property_id") for r in page.records]
    results["offset5_count5"] = {"count": len(page.records), "ids": ids_5_5, "elapsed_s": page.elapsed_s}
    print(f"   -> {len(page.records)} records (audit's raw API returned 0 here), ids={ids_5_5}")
    assert len(page.records) == 5, f"Expected 5 live records, got {len(page.records)}"

    print("\n3. Re-running the audit's other documented-broken live case: offset=10, count=5...")
    page2 = adapter.fetch_raw_window("33844", page_start=10, page_count=5, beds_min=2, beds_max=3, price_max=2300)
    ids_10_5 = [r.get("property_id") for r in page2.records]
    results["offset10_count5"] = {"count": len(page2.records), "ids": ids_10_5, "elapsed_s": page2.elapsed_s}
    print(f"   -> {len(page2.records)} records (audit's raw API returned 100 here), ids={ids_10_5}")
    assert len(page2.records) == 5, f"Expected 5 live records, got {len(page2.records)}"

    print("\n4. Confirming page 0-5, 5-10, 10-15 are genuinely non-overlapping sequential slices...")
    page0 = adapter.fetch_raw_window("33844", page_start=0, page_count=5, beds_min=2, beds_max=3, price_max=2300)
    ids_0_5 = [r.get("property_id") for r in page0.records]
    results["offset0_count5"] = {"ids": ids_0_5}
    print(f"   -> page[0:5]={ids_0_5}")
    print(f"      page[5:10]={ids_5_5}")
    print(f"      page[10:15]={ids_10_5}")
    all_ids = ids_0_5 + ids_5_5 + ids_10_5
    assert len(set(all_ids)) == 15, f"Expected 15 unique ids across 3 pages, got {len(set(all_ids))}: {all_ids}"

    print("\n5. Full normalized window for the actual app's default search (0-60, radius 20mi)...")
    t0 = time.monotonic()
    window = adapter.fetch_normalized_window(
        location="33844",
        radius_miles=20,
        beds_min=2,
        beds_max=3,
        price_max=2300,
        page_start=0,
        page_count=60,
        geo=geo,
    )
    results["normalized_window_0_60"] = {
        "source_total": window.source_total,
        "raw_count_this_page": window.raw_count_this_page,
        "radius_rejected_count": window.radius_rejected_count,
        "matched_count": window.matched_count,
        "elapsed_s": window.elapsed_s,
        "sample_names": [r["name"] for r in window.records[:5]],
    }
    print(f"   -> {json.dumps(results['normalized_window_0_60'], indent=2)}")
    print(f"   total wall time for step 5: {time.monotonic() - t0:.2f}s")

    (ROOT / "live_verify_results.json").write_text(json.dumps(results, indent=2, default=str))
    print("\nAll live assertions passed. Results saved to live_verify_results.json")


if __name__ == "__main__":
    main()
