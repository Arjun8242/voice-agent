"""execute.py: the calendar call after the visitor confirms (S15).

The gate only moves a booking to `executing` (or asks about a cancel) and hands off
{booking_id, kind}. This file makes the call, outside the turn, so a cut-in cannot lose it:

    create: read the event by its id; if absent, re-check the slot, create it, retry once if the
            outcome is unknown, read it back; only then mark the booking confirmed.
    delete: delete the event (already gone counts as deleted), then mark the booking cancelled.

The result is a booking_update for the browser: status, a card, and a fixed template line. The
model never writes it. BookingExecutor runs at most one call per booking at a time, so a second
hand-off for the same booking (a double click) waits for nothing and reports nothing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

# backend.* first so the classes match the ones tests and the fake calendar use (see booking/availability.py)
try:
    from backend.booking.availability import compute_slots, slot_label
    from backend.gcal.adapter import CalendarError, Event
except (ImportError, ModuleNotFoundError):
    from booking.availability import compute_slots, slot_label
    from gcal.adapter import CalendarError, Event

REPLIES = {
    "confirmed": "You're booked for {label}. The invite is on its way to {email}.",
    "slot_taken": "Sorry, that time was just taken, so nothing was booked. Ask me for available times again.",
    "calendar_failed": "Sorry, the calendar didn't respond, so nothing was booked. Please try again in a moment.",
    "cancelled": "Your meeting on {label} is cancelled. The cancellation email is on its way.",
    "cancel_failed": "I couldn't cancel the meeting just now, so it is still booked. Please try again in a moment.",
}


def _still_bookable(cal, sched, booking: dict, start: datetime, clock) -> bool:
    now = clock()
    busy = cal.free_busy(now, now + timedelta(days=sched.availability.booking_horizon_days + 1))
    return any(s.start == start for s in compute_slots(sched, busy, now, booking["visitor_tz"]))


def _create(store, cal, sched, booking: dict, clock) -> str:
    """-> confirmed | slot_taken | calendar_failed."""
    start = datetime.fromisoformat(booking["slot_start_utc"])
    event = Event(booking["booking_id"], start, start + timedelta(minutes=sched.meeting.duration_minutes),
                  booking["meeting_title"], booking["visitor_email"])
    try:
        if cal.get_event(event.id) is None:  # never create without reading by id first
            if not _still_bookable(cal, sched, booking, start, clock):
                store.move(event.id, "create_failed")
                return "slot_taken"
            for attempt in (1, 2):  # a timeout means the outcome is unknown: look before trying again
                try:
                    cal.create_event(event)
                    break
                except CalendarError:
                    if cal.get_event(event.id) is not None:
                        break
                    if attempt == 2:
                        raise
        if cal.get_event(event.id) is None:  # read back: confirmed only when Google has it
            raise CalendarError("failed", "the event is missing after create")
    except CalendarError:
        store.move(event.id, "create_failed")
        return "calendar_failed"
    store.move(event.id, "created")
    return "confirmed"


def _delete(store, cal, booking: dict) -> str:
    """-> cancelled | cancel_failed. On failure the meeting stays booked and the question stays open."""
    try:
        cal.delete_event(booking["booking_id"])
    except CalendarError:
        return "cancel_failed"
    store.move(booking["booking_id"], "deleted")
    return "cancelled"


def execute_booking(store, cal, sched, booking_id: str, kind: str, clock=lambda: datetime.now(timezone.utc)) -> dict | None:
    """Sync (calendar and SQLite). None when there is nothing to do: the booking already moved on."""
    booking = store.get(booking_id)
    if booking is None:
        return None
    if kind == "create" and booking["status"] == "executing":
        outcome = _create(store, cal, sched, booking, clock)
    elif kind == "delete" and booking["status"] == "awaiting_cancel_confirmation":
        outcome = _delete(store, cal, booking)
    else:
        return None

    label = slot_label(datetime.fromisoformat(booking["slot_start_utc"]), booking["visitor_tz"])
    status = store.get(booking_id)["status"]
    data = {"booking_id": booking_id, "status": status, "label": label, "email": booking["visitor_email"],
            "title": booking["meeting_title"], "timezone": booking["visitor_tz"]}
    card = {"card_id": f"booking:{booking_id}", "type": f"booking_{outcome}", "data": data}
    return {"booking_id": booking_id, "status": status, "outcome": outcome,
            "text": REPLIES[outcome].format(label=label, email=booking["visitor_email"]), "card": card}


class BookingExecutor:
    """Runs execute_booking off the event loop, one call per booking at a time."""

    def __init__(self, store, cal, sched, clock=lambda: datetime.now(timezone.utc)):
        self.store, self.cal, self.sched, self.clock = store, cal, sched, clock
        self._running: set[str] = set()  # no lock needed: only the event loop thread touches it

    async def run(self, booking_id: str, kind: str) -> dict | None:
        if booking_id in self._running:
            return None  # the run already going will report
        self._running.add(booking_id)
        try:
            return await asyncio.to_thread(execute_booking, self.store, self.cal, self.sched, booking_id, kind, self.clock)
        finally:
            self._running.discard(booking_id)
