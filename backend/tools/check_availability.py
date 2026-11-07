"""checkAvailability: up to 3 bookable slots in the visitor's timezone, as one slots card (S13).

Google's busy times become slots in booking/availability.py. Nothing is booked or reserved here.
The visitor's timezone comes from ctx (the session), never from the model.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .schemas import Args, ToolError

# backend.* first so the classes match the ones tests and the fake calendar use (see booking/availability.py)
try:
    from backend.booking.availability import compute_slots
    from backend.gcal.adapter import CalendarError
except (ImportError, ModuleNotFoundError):
    from booking.availability import compute_slots
    from gcal.adapter import CalendarError

MAX_SLOTS = 3  # few enough to read out loud


def _day(text: str | None, name: str) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ToolError("invalid_date", f"{name} must look like YYYY-MM-DD, not {text!r}.")


def _clock_time(text: str | None, name: str) -> time | None:
    if text is None:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise ToolError("invalid_time", f"{name} must look like HH:MM (24-hour), not {text!r}.")


def _spread(slots: list, zone: str) -> list:
    """The first slot of each day before any second slot of a day, so a week offers days, not one morning."""
    seen, firsts, rest = set(), [], []
    for s in slots:
        day = s.start.astimezone(ZoneInfo(zone)).date()
        (rest if day in seen else firsts).append(s)
        seen.add(day)
    return sorted((firsts + rest)[:MAX_SLOTS], key=lambda s: s.start)


def fresh_slots(cal, sched, now: datetime, zone: str):
    """Every bookable slot from fresh free/busy. Shared with startBooking, which re-checks the chosen slot."""
    try:
        busy = cal.free_busy(now, now + timedelta(days=sched.availability.booking_horizon_days + 1))
    except CalendarError as err:
        raise ToolError("calendar_unavailable", f"The calendar could not be read ({err.code}). Say so and try again later.")
    try:
        return compute_slots(sched, busy, now, zone)
    except ValueError as err:  # a scheduling rule is not set in scheduling.yaml
        raise ToolError("not_configured", str(err))


def check_availability(args: Args, ctx: dict, cal, sched, clock=lambda: datetime.now(timezone.utc)) -> tuple[dict, list[dict]]:
    first, last = _day(args.date_from, "date_from"), _day(args.date_to, "date_to")
    earliest, latest = _clock_time(args.time_from, "time_from"), _clock_time(args.time_to, "time_to")
    zone = ctx["visitor_timezone"]
    slots = fresh_slots(cal, sched, clock(), zone)

    local = lambda slot: slot.start.astimezone(ZoneInfo(zone))
    slots = [s for s in slots if (first is None or local(s).date() >= first) and (last is None or local(s).date() <= last)
             and (earliest is None or local(s).time() >= earliest) and (latest is None or local(s).time() <= latest)]
    shown = [{"slot_id": s.id, "label": s.label} for s in _spread(slots, zone)]
    result = {"timezone": zone, "slots": shown}
    if not shown:
        result["note"] = "No free time matches. Say so and ask the visitor for another day or time."
    cards = [{"card_id": "slots", "type": "slots", "data": result}] if shown else []
    return result, cards
