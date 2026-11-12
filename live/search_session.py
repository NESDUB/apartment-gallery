"""
Phase B: an in-memory live retrieval service built on the verified Phase A
adapter (realtor_adapter.py). Pure Python — no HTTP, no UI wiring. That's
deliberate: Phase C (connecting the UI) is a separate, later step per the
handoff, and this module needs to be independently testable without a
browser or server first.

Design, matching the handoff's Phase B requirements directly:

- Each search gets a stable search_id. A session holds resolved geography,
  every raw page fetched so far (for diagnostics), accumulated matched
  records deduped by property_id, and an explicit lifecycle state.
- Pagination advances by RAW SOURCE POSITION (session.raw_checked_count),
  never by how many records survived local filtering — so a search that
  matches zero records in a page still correctly advances and keeps
  going, instead of looking exhausted.
- A step() call only ever fetches one additional window. Nothing here
  spins in a loop by itself — the caller (eventually the UI's "load more"
  trigger, in Phase C) decides when to call step() again. This keeps
  source-fetch work bounded and visible, matching "separate source-fetch
  budgets from photo prefetch."
- On failure, prior successfully-matched records are kept; only the
  session's state/error moves to failed (or limited, if a budget was hit
  instead of a hard failure). A canceled session's step() is a no-op, so
  stale work can never mutate state after cancellation.

Known inefficiency, not hidden: because realtor_adapter.fetch_raw_window()
works around the installed HomeHarvest's pagination bug by always
re-requesting from offset=0 with a growing limit (see that module's
docstring), each step() here re-fetches everything from the start
internally, not just the new slice. For a single-user local tool against
result sets in the hundreds, this is bounded and acceptable; it is not
free, and a future optimization could call HomeHarvest's lower-level
general_search() directly per 200-row chunk to avoid it. Not done here to
avoid adding new, less-tested surface against the installed library on
top of the already-verified Phase A path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import photo_adapter
import realtor_adapter as adapter

# A step fetches this many additional raw rows per call. Matches
# HomeHarvest's own fixed GraphQL page size (realtor_adapter.SOURCE_PAGE_SIZE)
# so one step corresponds to one real source page.
DEFAULT_STEP_SIZE = adapter.SOURCE_PAGE_SIZE

# Budgets: stop advancing a session automatically past these, even if the
# source might have more. A session can still be resumed by the caller
# choosing to keep calling step() past "limited" if it explicitly wants to.
DEFAULT_MAX_RAW_RECORDS = 2000
DEFAULT_MAX_WALL_SECONDS = 60


class SessionState(str, Enum):
    RESOLVING = "resolving"
    FETCHING = "fetching"
    MORE_AVAILABLE = "more_available"
    COMPLETE = "complete"
    LIMITED = "limited"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class SearchParams:
    location: str
    radius_miles: Optional[float]
    beds_min: int
    beds_max: int
    price_max: float
    price_min: float = 0
    step_size: int = DEFAULT_STEP_SIZE
    max_raw_records: int = DEFAULT_MAX_RAW_RECORDS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS


@dataclass
class SearchSession:
    search_id: str
    params: SearchParams
    state: SessionState = SessionState.RESOLVING
    geo: Optional[adapter.GeoResolution] = None
    raw_checked_count: int = 0
    raw_pages: list = field(default_factory=list)  # diagnostic history, not required for correctness
    matched_by_id: dict = field(default_factory=dict)
    photos_by_id: dict = field(default_factory=dict)  # full photo lists, cached once per property_id
    errors: list = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    canceled: bool = False

    def elapsed_s(self) -> float:
        return time.monotonic() - self.created_at

    def snapshot(self) -> dict:
        return {
            "search_id": self.search_id,
            "state": self.state.value,
            "geo": None
            if self.geo is None
            else {
                "requested_location": self.geo.requested_location,
                "resolved_text": self.geo.resolved_text,
                "area_type": self.geo.area_type,
                "centroid": self.geo.centroid,
            },
            "raw_checked_count": self.raw_checked_count,
            "unique_matched_count": len(self.matched_by_id),
            "matched_records": list(self.matched_by_id.values()),
            "errors": list(self.errors),
            "elapsed_s": round(self.elapsed_s(), 3),
        }


class SearchManager:
    """Holds active sessions in process memory. Nothing here persists to
    disk — restarting the process loses all in-flight sessions, which is
    fine for a local single-user tool (matches the no-localStorage rule
    the project already follows for the snapshot app)."""

    def __init__(self):
        self._sessions: dict[str, SearchSession] = {}

    def create(self, params: SearchParams) -> str:
        search_id = str(uuid.uuid4())
        self._sessions[search_id] = SearchSession(search_id=search_id, params=params)
        return search_id

    def get(self, search_id: str) -> Optional[SearchSession]:
        return self._sessions.get(search_id)

    def cancel(self, search_id: str) -> bool:
        session = self._sessions.get(search_id)
        if session is None:
            return False
        session.canceled = True
        session.state = SessionState.CANCELED
        return True

    def get_photos(self, search_id: str, property_id: str) -> Optional[list]:
        """Full photo list for a matched listing, from this session's cache
        (populated during step() for every record it matched). Returns
        None if the session or property_id is unknown — distinct from an
        empty list, which means the listing genuinely has no photos.
        """
        session = self._sessions.get(search_id)
        if session is None or property_id not in session.matched_by_id:
            return None
        return session.photos_by_id.get(property_id, [])

    def step(self, search_id: str) -> dict:
        """Advance one session by exactly one fetch window. Returns the
        session's snapshot. A canceled, complete, failed, or rate-limited
        session is left untouched — step() on a finished session is a
        harmless no-op, not an error, so a caller doesn't need to track
        whether it already stopped.
        """
        session = self._sessions.get(search_id)
        if session is None:
            raise KeyError(f"Unknown search_id {search_id!r}")

        if session.canceled or session.state in (
            SessionState.COMPLETE,
            SessionState.FAILED,
            SessionState.CANCELED,
        ):
            return session.snapshot()

        if session.elapsed_s() > session.params.max_wall_seconds:
            session.state = SessionState.LIMITED
            return session.snapshot()

        if session.geo is None:
            session.state = SessionState.RESOLVING
            try:
                session.geo = adapter.resolve_geography(session.params.location)
            except adapter.LocationUnresolved as exc:
                session.state = SessionState.FAILED
                session.errors.append({"kind": exc.kind, "message": exc.message})
                return session.snapshot()
            except adapter.AdapterError as exc:
                session.state = self._state_for_error(exc)
                session.errors.append({"kind": exc.kind, "message": exc.message})
                return session.snapshot()

        if session.raw_checked_count >= session.params.max_raw_records:
            session.state = SessionState.LIMITED
            return session.snapshot()

        session.state = SessionState.FETCHING
        step_size = min(session.params.step_size, session.params.max_raw_records - session.raw_checked_count)
        try:
            window = adapter.fetch_normalized_window(
                location=session.params.location,
                radius_miles=session.params.radius_miles,
                beds_min=session.params.beds_min,
                beds_max=session.params.beds_max,
                price_max=session.params.price_max,
                price_min=session.params.price_min,
                page_start=session.raw_checked_count,
                page_count=step_size,
                geo=session.geo,
            )
        except adapter.AdapterError as exc:
            # Prior matched records are kept — only the session's state and
            # error log change. This is the acceptance gate "successful
            # pages survive later failures."
            session.state = self._state_for_error(exc)
            session.errors.append({"kind": exc.kind, "message": exc.message})
            return session.snapshot()

        session.raw_pages.append(
            {
                "page_start": window.page_start,
                "raw_count": window.raw_count_this_page,
                "radius_rejected": window.radius_rejected_count,
                "matched": window.matched_count,
                "elapsed_s": window.elapsed_s,
            }
        )
        new_ids = [r["property_id"] for r in window.records if r["property_id"] not in session.photos_by_id]
        if new_ids:
            photo_result = photo_adapter.fetch_photos(new_ids)
            session.photos_by_id.update(photo_result.by_property_id)
            if photo_result.errors:
                session.errors.append({"kind": "photo_fetch_partial", "message": f"{len(photo_result.errors)} listing(s) had no photo data available"})
            photo_adapter.attach_covers(window.records, session.photos_by_id)

        for record in window.records:
            session.matched_by_id[record["property_id"]] = record

        fetched_this_step = window.raw_count_this_page
        session.raw_checked_count += fetched_this_step

        source_exhausted = window.source_total != -1
        if source_exhausted:
            session.state = SessionState.COMPLETE
        elif session.raw_checked_count >= session.params.max_raw_records:
            session.state = SessionState.LIMITED
        elif session.elapsed_s() > session.params.max_wall_seconds:
            session.state = SessionState.LIMITED
        else:
            session.state = SessionState.MORE_AVAILABLE

        return session.snapshot()

    @staticmethod
    def _state_for_error(exc: adapter.AdapterError) -> SessionState:
        if exc.kind == "rate_limited":
            return SessionState.RATE_LIMITED
        return SessionState.FAILED
