"""Calendar adapters: the fake for tests and Google for real, chosen by CALENDAR_BACKEND."""

try:
    from config import CALENDAR_BACKEND
except (ImportError, ModuleNotFoundError):
    from backend.config import CALENDAR_BACKEND

from .adapter import CalendarAdapter, CalendarError, Event, Interval
from .fake import FakeCalendar


def create_calendar() -> CalendarAdapter:
    if CALENDAR_BACKEND == "fake":
        return FakeCalendar()
    if CALENDAR_BACKEND == "google":
        from .google import GoogleCalendar  # imported only when chosen, so the fake needs no Google settings

        return GoogleCalendar()
    raise ValueError(f"CALENDAR_BACKEND must be 'fake' or 'google', not {CALENDAR_BACKEND!r}")
