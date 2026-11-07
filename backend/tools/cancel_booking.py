"""cancelBooking: cancel this session's booking (S14).

Only the booking tied to this session is touched, found in SQLite by session_id (never from
graph state or a model argument). A pending booking is just dropped: nothing is on the calendar.
A confirmed meeting is only asked about: the delete runs after the visitor confirms on screen.
"""

from __future__ import annotations

from datetime import datetime

from .schemas import Args, ToolError

try:
    from backend.booking.availability import slot_label
    from backend.booking.store import PENDING
except (ImportError, ModuleNotFoundError):
    from booking.availability import slot_label
    from booking.store import PENDING

def _changed() -> ToolError:
    return ToolError("try_again", "The booking changed just now. Ask the visitor again.")


def cancel_booking(args: Args, ctx: dict, store) -> tuple[dict, list[dict]]:
    booking = store.for_session(ctx["session_id"])
    if booking is None:
        raise ToolError("no_booking", "This visitor has no booking in this conversation. A meeting booked earlier can be declined from the Google invite.")
    booking_id, status = booking["booking_id"], booking["status"]
    label = slot_label(datetime.fromisoformat(booking["slot_start_utc"]), ctx["visitor_timezone"])

    if status in PENDING:
        if not store.move(booking_id, "drop"):
            raise _changed()
        return {"status": "cancelled", "label": label, "note": "Nothing was on the calendar yet."}, []
    if status == "executing":
        raise ToolError("in_progress", "The meeting is being created right now. Try again in a moment.")
    if status == "confirmed" and not store.move(booking_id, "request_cancel"):
        raise _changed()

    # confirmed (now awaiting_cancel_confirmation) or already waiting: ask on screen, again if needed
    data = {"booking_id": booking_id, "label": label}
    result = {"status": "awaiting_cancel_confirmation", **data, "next": "The meeting is not cancelled yet. The visitor confirms on screen."}
    return result, [{"card_id": f"cancel:{booking_id}", "type": "cancel_confirm", "data": data}]
