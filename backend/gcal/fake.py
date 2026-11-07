"""fake.py: in-memory calendar for tests (S13).

fail_next makes the next call to a method raise CalendarError. With after_effect=True the
call runs first, so the caller sees a timeout for an event that really was created.
"""

from __future__ import annotations

from datetime import datetime

from .adapter import CalendarError, Event, Interval


class FakeCalendar:
    def __init__(self, busy: list[Interval] | None = None):
        self.busy = list(busy or [])  # busy time that is not one of our events
        self.events: dict[str, Event] = {}
        self._failures: list[tuple[str, str, bool]] = []

    def fail_next(self, method: str, code: str = "timeout", after_effect: bool = False) -> None:
        self._failures.append((method, code, after_effect))

    def _call(self, method: str, action):
        failure = next((f for f in self._failures if f[0] == method), None)
        if failure:
            self._failures.remove(failure)
            if not failure[2]:
                raise CalendarError(failure[1], "injected")
        result = action()
        if failure:
            raise CalendarError(failure[1], "injected")
        return result

    def free_busy(self, start: datetime, end: datetime) -> list[Interval]:
        def action():
            booked = [Interval(e.start, e.end) for e in self.events.values()]
            return [i for i in [*self.busy, *booked] if i.start < end and i.end > start]

        return self._call("free_busy", action)

    def create_event(self, event: Event) -> Event:
        def action():
            if event.id in self.events:
                raise CalendarError("conflict", f"event {event.id} already exists")
            self.events[event.id] = event
            return event

        return self._call("create_event", action)

    def get_event(self, event_id: str) -> Event | None:
        return self._call("get_event", lambda: self.events.get(event_id))

    def delete_event(self, event_id: str) -> None:
        self._call("delete_event", lambda: self.events.pop(event_id, None))
