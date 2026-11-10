"""booking_gate node: apply one click on a booking card (S14). Code only, no LLM.

Clicks reach the graph as state["ui_action"] = {"action": ..., "payload": {...}}, and ingest routes
them here. The booking is read from SQLite on every click, never from graph state. Every reply is a
fixed template, so the model can never be the one saying a meeting is booked. Confirm and
confirm_cancel only change the status and emit a booking_execute event: the calendar call runs
outside the turn (S15), so a cut-in cannot lose its result.

Actions: select_slot {slot_id}, submit_details {booking_id, name, email, title?}, confirm {booking_id},
cancel {booking_id} (before confirm), confirm_cancel {booking_id}, keep_booking {booking_id}.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from langgraph.config import get_config, get_stream_writer

try:
    from backend.booking.availability import slot_label
    from backend.tools.schemas import StartBookingArgs, ToolError
    from backend.tools.start_booking import start_booking
except (ImportError, ModuleNotFoundError):
    from booking.availability import slot_label
    from tools.schemas import StartBookingArgs, ToolError
    from tools.start_booking import start_booking

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME, MAX_EMAIL, MAX_TITLE = 80, 254, 80

REPLIES = {
    "form": "Please type your name and email in the form on screen.",
    "summary": "Please check the summary on screen and tap Confirm to book it.",
    "booking": "Booking your meeting now.",
    "already": "That meeting is already booked or being booked.",
    "dropped": "Okay, I've dropped that booking. Nothing was put on the calendar.",
    "cancelling": "Cancelling your meeting now.",
    "kept": "Okay, your meeting stays booked.",
    "stale": "That card is out of date. Ask me for available times again.",
    "unknown": "Sorry, I didn't understand that click.",
}
# startBooking's errors are written for the model; the visitor hears these instead
VISITOR_ERRORS = {
    "slot_unavailable": "That time was just taken. Ask me for available times again.",
    "already_booked": "You already have a meeting booked. Say cancel if you want a different time.",
    "calendar_unavailable": "I can't reach the calendar right now. Please try again in a moment.",
}


def _details(payload: dict, default_title: str) -> dict | str:
    """The form's fields, cleaned; or the message to show when one is not valid."""
    name = " ".join(str(payload.get("name") or "").split())  # also strips line breaks
    email = str(payload.get("email") or "").strip()
    title = " ".join(str(payload.get("title") or "").split())[:MAX_TITLE] or default_title  # goes into the calendar invite
    if not name or len(name) > MAX_NAME:
        return f"Please type your name, up to {MAX_NAME} characters."
    if len(email) > MAX_EMAIL or not EMAIL.match(email):
        return "That email address doesn't look right. Please check it."
    return {"visitor_name": name, "visitor_email": email, "meeting_title": title}


def apply_click(action, payload: dict, ctx: dict, store, cal, sched, clock) -> tuple[str, list[dict], dict | None]:
    """-> (reply, cards, booking_execute or None). Sync: it reads SQLite and, for select_slot, the calendar."""
    if action == "select_slot":
        try:
            result, cards = start_booking(StartBookingArgs(slot_id=str(payload.get("slot_id") or "")), ctx, cal, sched, store, clock)
        except ToolError as err:
            return VISITOR_ERRORS.get(err.code, REPLIES["stale"]), [], None
        return REPLIES["form"], cards, None

    booking = store.for_session(ctx["session_id"])
    if booking is None or payload.get("booking_id") != booking["booking_id"]:  # an old card, or another session's id
        return REPLIES["stale"], [], None
    booking_id, status = booking["booking_id"], booking["status"]

    if action == "submit_details":
        details = _details(payload, sched.meeting.title)
        if isinstance(details, str):
            return details, [], None
        if not store.move(booking_id, "submit_details", **details):
            return REPLIES["stale"], [], None
        data = {"booking_id": booking_id, "label": slot_label(datetime.fromisoformat(booking["slot_start_utc"]), ctx["visitor_timezone"]),
                "timezone": ctx["visitor_timezone"], "duration_minutes": sched.meeting.duration_minutes,
                "name": details["visitor_name"], "email": details["visitor_email"], "title": details["meeting_title"]}
        return REPLIES["summary"], [{"card_id": f"summary:{booking_id}", "type": "booking_summary", "data": data}], None

    if action == "confirm":
        if store.move(booking_id, "confirm"):
            return REPLIES["booking"], [], {"booking_id": booking_id, "kind": "create"}
        if status == "executing":
            # hand off again: a cut-in may have lost the first hand-off after the status changed. Safe because
            # the create reads the event by id first, and S15 runs one calendar call per booking at a time.
            return REPLIES["already"], [], {"booking_id": booking_id, "kind": "create"}
        return (REPLIES["already"] if status == "confirmed" else REPLIES["stale"]), [], None

    if action == "cancel":
        return (REPLIES["dropped"] if store.move(booking_id, "drop") else REPLIES["stale"]), [], None

    if action == "confirm_cancel":
        # the status stays until the delete succeeds (S15): delete first, then mark cancelled
        if status == "awaiting_cancel_confirmation":
            return REPLIES["cancelling"], [], {"booking_id": booking_id, "kind": "delete"}
        return REPLIES["stale"], [], None

    if action == "keep_booking":
        return (REPLIES["kept"] if store.move(booking_id, "keep") else REPLIES["stale"]), [], None

    return REPLIES["unknown"], [], None


def create_booking_gate_node(store, calendar, scheduling, clock=lambda: datetime.now(timezone.utc)):
    async def booking_gate_node(state: dict) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        click = state.get("ui_action") or {}
        payload = click.get("payload") if isinstance(click.get("payload"), dict) else {}
        ctx = {"session_id": get_config()["configurable"]["thread_id"], "visitor_timezone": state.get("visitor_timezone") or "UTC"}

        reply, cards, execute = await asyncio.to_thread(apply_click, click.get("action"), payload, ctx, store, calendar, scheduling, clock)
        for card in cards:
            write({"type": "card", "card": card})
        if execute:
            write({"type": "booking_execute", **execute})
        write({"type": "token", "text": reply})  # spoken and shown like an answer

        stage = {**state.get("stage_ms", {}), "booking_gate": round((time.perf_counter() - start) * 1000, 1)}
        return {"final_text": reply, "cards": cards, "booking_execute": execute, "ui_action": None, "stage_ms": stage}

    return booking_gate_node
