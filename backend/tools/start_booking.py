"""startBooking: the visitor picked a slot; start a booking that waits for their details (S14).

The model may start a booking but never confirm it. This writes one pending row and nothing
else: no calendar event, no reservation. The chosen slot is re-checked against fresh free/busy.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .check_availability import fresh_slots
from .schemas import Args, ToolError

# backend.* first so the classes match the ones tests and the fake calendar use (see booking/availability.py)
try:
    from backend.booking.availability import slot_label
    from backend.booking.store import PENDING
except (ImportError, ModuleNotFoundError):
    from booking.availability import slot_label
    from booking.store import PENDING


def start_booking(args: Args, ctx: dict, cal, sched, store, clock=lambda: datetime.now(timezone.utc)) -> tuple[dict, list[dict]]:
    session, zone = ctx["session_id"], ctx["visitor_timezone"]
    current = store.for_session(session)
    if current and current["status"] not in PENDING:
        when = slot_label(datetime.fromisoformat(current["slot_start_utc"]), zone)
        raise ToolError("already_booked", f"This visitor already has a meeting on {when}. Offer to cancel it with cancelBooking first.")

    slot = next((s for s in fresh_slots(cal, sched, clock(), zone) if s.id == args.slot_id), None)
    if slot is None:
        raise ToolError("slot_unavailable", f"{args.slot_id} is not a free slot. Call checkAvailability and offer the fresh slots.")

    booking = store.create_pending(session, slot.start, zone)
    data = {"booking_id": booking["booking_id"], "slot_id": slot.id, "label": slot.label, "timezone": zone,
            "default_title": sched.meeting.title}
    result = {"status": "awaiting_details", **data, "next": "Nothing is booked yet. The visitor types their name and email in the form on screen."}
    return result, [{"card_id": f"booking:{booking['booking_id']}", "type": "booking_form", "data": data}]
