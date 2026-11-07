"""availability.py: turn Google's busy times into bookable slots (S13).

Pure: no clock, no calendar, no I/O. The rules come from scheduling.yaml (the Scheduling
model in kb/validate.py). Every busy interval is extended by buffer_minutes after its end.
Slots sit on a grid of the meeting length, starting at start_time in the calendar's timezone.
`now` must be timezone-aware.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


try:
    from backend.gcal.adapter import Interval
    from backend.kb.validate import Scheduling
except (ImportError, ModuleNotFoundError):
    from gcal.adapter import Interval
    from kb.validate import Scheduling

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Slot:
    id: str
    start: datetime
    label: str


def slot_label(start: datetime, visitor_tz: str) -> str:
    return start.astimezone(ZoneInfo(visitor_tz)).strftime("%a %d %b, %H:%M %Z")


def compute_slots(sched: Scheduling, busy: list[Interval], now: datetime, visitor_tz: str) -> list[Slot]:
    a = sched.availability
    for name in ("start_time", "end_time", "min_notice_hours", "buffer_minutes"):
        if getattr(a, name) is None:
            raise ValueError(f"scheduling.yaml.availability.{name} is not set")

    host = ZoneInfo(sched.calendar.timezone)
    length = timedelta(minutes=sched.meeting.duration_minutes)
    pad = timedelta(minutes=a.buffer_minutes)
    earliest = now + timedelta(hours=a.min_notice_hours)
    latest = now + timedelta(days=a.booking_horizon_days)
    blocked = [(b.start, b.end + pad) for b in busy]  # the buffer comes after a busy time, not before

    slots = []
    for offset in range(a.booking_horizon_days + 1):
        day = now.astimezone(host).date() + timedelta(days=offset)
        if DAYS[day.weekday()] not in a.working_days:
            continue
        # step in UTC so a daylight-saving change in the calendar's timezone cannot skew the grid
        cursor = datetime.combine(day, time.fromisoformat(a.start_time), tzinfo=host).astimezone(timezone.utc)
        stop = datetime.combine(day, time.fromisoformat(a.end_time), tzinfo=host).astimezone(timezone.utc)
        while cursor + length <= stop:
            clear = not any(cursor < end and cursor + length > start for start, end in blocked)
            if earliest <= cursor <= latest and clear:
                slots.append(Slot(cursor.strftime("%Y-%m-%dT%H:%MZ"), cursor, slot_label(cursor, visitor_tz)))
            cursor += length
    return slots
