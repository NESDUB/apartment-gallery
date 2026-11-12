"""
Bounded live verification of search_session.py (Phase B) against the real
service. Same restraint as live_verify.py: a small fixed number of steps,
no loop, no repeated runs as a stress test.

    /tmp/apartment-search-py313/bin/python live_verify_session.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search_session import SearchManager, SearchParams

ROOT = Path(__file__).resolve().parent


def main():
    mgr = SearchManager()
    sid = mgr.create(
        SearchParams(
            location="33844",
            radius_miles=20,
            beds_min=2,
            beds_max=3,
            price_max=2300,
            step_size=200,  # one real source page per step
            max_raw_records=600,
            max_wall_seconds=60,
        )
    )
    print(f"Created session {sid}")

    history = []
    for i in range(4):
        snap = mgr.step(sid)
        slim = {k: v for k, v in snap.items() if k != "matched_records"}
        history.append(slim)
        print(f"\nStep {i + 1}: state={snap['state']} raw_checked={snap['raw_checked_count']} "
              f"matched={snap['unique_matched_count']} elapsed={snap['elapsed_s']}s")
        if snap["errors"]:
            print(f"  errors={snap['errors']}")
        if snap["state"] in ("complete", "failed", "canceled", "rate_limited"):
            print(f"  session reached terminal state '{snap['state']}' after step {i + 1}")
            break

    final = mgr.get(sid).snapshot()
    print(f"\nFinal: {len(final['matched_records'])} matched records, "
          f"{final['raw_checked_count']} raw source rows checked, state={final['state']}")
    for r in final["matched_records"][:5]:
        print(f"  - {r['name']} | ${r['min_rent']} | {r.get('radius_miles')}mi")

    assert final["state"] in ("complete", "more_available", "limited"), f"Unexpected terminal state: {final['state']}"
    assert final["unique_matched_count"] >= 0

    (ROOT / "live_verify_session_results.json").write_text(
        json.dumps({"history": history, "final": {k: v for k, v in final.items() if k != "matched_records"}}, indent=2, default=str)
    )
    print("\nLive session verification passed. Results saved to live_verify_session_results.json")


if __name__ == "__main__":
    main()
