"""store.py: the one SQLite table for booking, and the status changes it allows (S14).

Google is the calendar of record. This table only remembers which booking, and which Google
event (the same uuid4().hex id), belong to which session, and where each booking is in the flow.

Every status change is one UPDATE ... WHERE status IN (...). SQLite applies it atomically, so of
two identical requests (a double click, a reconnect replay) exactly one gets through.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PENDING = ("awaiting_details", "awaiting_confirmation")  # reserves nothing; replaced by the next startBooking
CLOSED = ("cancelled", "failed")

# event -> (statuses it may start from, status it moves to)
TRANSITIONS = {
    "submit_details": (PENDING, "awaiting_confirmation"),  # from awaiting_confirmation too: the visitor edits the form
    "confirm": (("awaiting_confirmation",), "executing"),
    "created": (("executing",), "confirmed"),
    "create_failed": (("executing",), "failed"),
    "drop": (PENDING, "cancelled"),
    "request_cancel": (("confirmed",), "awaiting_cancel_confirmation"),
    "keep": (("awaiting_cancel_confirmation",), "confirmed"),
    "deleted": (("awaiting_cancel_confirmation",), "cancelled"),
}
DETAIL_FIELDS = {"visitor_name", "visitor_email", "meeting_title"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    booking_id     TEXT PRIMARY KEY,  -- uuid4().hex; also the Google event id
    session_id     TEXT NOT NULL,
    slot_start_utc TEXT NOT NULL,
    visitor_tz     TEXT NOT NULL,
    visitor_name   TEXT,
    visitor_email  TEXT,
    meeting_title  TEXT,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL
)"""


def _marks(values) -> str:
    return ", ".join("?" * len(values))


class BookingStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn, conn:
            conn.execute(SCHEMA)

    def _connect(self):
        # a connection per call: tool handlers run in worker threads, and a shared connection would need a lock
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def get(self, booking_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)).fetchone()
        return dict(row) if row else None

    def for_session(self, session_id: str) -> dict | None:
        """The session's live booking (not cancelled or failed), newest first."""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM bookings WHERE session_id = ? AND status NOT IN ({_marks(CLOSED)}) ORDER BY rowid DESC LIMIT 1",
                (session_id, *CLOSED),
            ).fetchone()
        return dict(row) if row else None

    def create_pending(self, session_id: str, slot_start: datetime, visitor_tz: str) -> dict:
        """Replace the session's pending booking, if any, with a new one awaiting details."""
        booking_id = uuid.uuid4().hex
        with self._connect() as conn, conn:
            conn.execute(f"DELETE FROM bookings WHERE session_id = ? AND status IN ({_marks(PENDING)})", (session_id, *PENDING))
            conn.execute(
                "INSERT INTO bookings (booking_id, session_id, slot_start_utc, visitor_tz, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (booking_id, session_id, slot_start.isoformat(), visitor_tz, "awaiting_details", datetime.now(timezone.utc).isoformat()),
            )
        return self.get(booking_id)

    def move(self, booking_id: str, event: str, **details) -> bool:
        """Apply one event. False when the booking is not in a status the event may start from."""
        allowed, to = TRANSITIONS[event]
        if set(details) - DETAIL_FIELDS:
            raise ValueError(f"unknown booking fields: {sorted(set(details) - DETAIL_FIELDS)}")
        sets = ", ".join(["status = ?", *(f"{name} = ?" for name in details)])  # names come from DETAIL_FIELDS only
        with self._connect() as conn, conn:
            cur = conn.execute(
                f"UPDATE bookings SET {sets} WHERE booking_id = ? AND status IN ({_marks(allowed)})",
                (to, *details.values(), booking_id, *allowed),
            )
        return cur.rowcount == 1
