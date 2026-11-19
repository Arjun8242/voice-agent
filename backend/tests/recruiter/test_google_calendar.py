"""The Google Calendar adapter (S15) against a mocked transport. No network, no real calendar.

Each test checks a rule booking/execute.py depends on: what gets sent on create, and how
Google's answers map to None / CalendarError.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.gcal.adapter import CalendarError, Event, Interval
from backend.gcal.google import GoogleCalendar

T = datetime(2026, 11, 9, 4, 30, tzinfo=timezone.utc)
EVENT = Event("a" * 32, T, T + timedelta(minutes=30), "Intro", "priya@example.com")


def calendar(handler):
    """handler(request) -> httpx.Response for every API call; the token endpoint always succeeds."""
    requests = []

    def route(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": f"token{len(requests)}", "expires_in": 3600})
        return handler(request)

    cal = GoogleCalendar("id", "secret", "refresh", "primary", http=httpx.Client(transport=httpx.MockTransport(route)))
    return cal, requests


def test_create_sends_our_id_the_attendee_and_asks_google_to_email_the_invite():
    cal, requests = calendar(lambda r: httpx.Response(200, json={"id": "a" * 32}))
    cal.create_event(EVENT)
    create = requests[-1]
    body = json.loads(create.content)
    assert create.url.params["sendUpdates"] == "all" and create.url.path == "/calendar/v3/calendars/primary/events"
    assert body["id"] == "a" * 32 and body["attendees"] == [{"email": "priya@example.com"}]
    assert create.headers["Authorization"] == "Bearer token1"


def test_the_access_token_is_reused_and_fetched_again_once_after_a_401():
    answers = iter([httpx.Response(200, json={"calendars": {"primary": {"busy": []}}}),
                    httpx.Response(401), httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})])
    cal, requests = calendar(lambda r: next(answers))
    cal.free_busy(T, T)
    cal.free_busy(T, T)
    tokens = [r for r in requests if r.url.host == "oauth2.googleapis.com"]
    assert len(tokens) == 2 and requests[-1].headers["Authorization"] == "Bearer token4"


def test_free_busy_reads_google_times_and_reports_a_wrong_calendar():
    busy = {"calendars": {"primary": {"busy": [{"start": "2026-11-09T04:30:00Z", "end": "2026-11-09T05:00:00Z"}]}}}
    cal, _ = calendar(lambda r: httpx.Response(200, json=busy))
    assert cal.free_busy(T, T + timedelta(hours=1)) == [Interval(T, T + timedelta(minutes=30))]

    cal, _ = calendar(lambda r: httpx.Response(200, json={"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}}))
    with pytest.raises(CalendarError):
        cal.free_busy(T, T)


def test_a_missing_or_deleted_event_reads_as_none():
    for answer in (httpx.Response(404), httpx.Response(410),
                   httpx.Response(200, json={"id": "a" * 32, "status": "cancelled", "start": {}, "end": {}})):
        cal, _ = calendar(lambda r, answer=answer: answer)
        assert cal.get_event("a" * 32) is None


def test_deleting_an_event_that_is_already_gone_is_fine_and_asks_google_to_email():
    for status in (204, 404, 410):
        cal, requests = calendar(lambda r, status=status: httpx.Response(status))
        cal.delete_event("a" * 32)
        assert requests[-1].url.params["sendUpdates"] == "all"


def test_a_timeout_is_reported_as_timeout_so_the_caller_reads_by_id_before_retrying():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    cal, _ = calendar(slow)
    with pytest.raises(CalendarError) as err:
        cal.create_event(EVENT)
    assert err.value.code == "timeout"


def test_missing_settings_stop_startup_with_their_names():
    with pytest.raises(ValueError, match="GOOGLE_REFRESH_TOKEN"):
        GoogleCalendar("id", "secret", "", "primary")
