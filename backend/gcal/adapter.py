"""adapter.py: the four calendar calls booking needs (S13).

Sync on purpose: tool handlers already run in a worker thread (tools/registry.py),
and the booking flow can use asyncio.to_thread. All datetimes are timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Event:
    id: str  # uuid4().hex;
    start: datetime
    end: datetime
    summary: str
    attendee_email: str


class CalendarError(Exception):
    """code: timeout (outcome unknown), conflict (event id already exists), failed."""

    def __init__(self, code: str, details: str = ""):
        super().__init__(f"{code}: {details}" if details else code)
        self.code = code
        self.details = details


class CalendarAdapter(Protocol):
    def free_busy(self, start: datetime, end: datetime) -> list[Interval]: ...

    def create_event(self, event: Event) -> Event: ...

    def get_event(self, event_id: str) -> Event | None:  # None when it does not exist
        ...

    def delete_event(self, event_id: str) -> None:  # an event that is already gone counts as deleted
        ...
