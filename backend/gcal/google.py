"""google.py: the real calendar, Google Calendar API v3 over httpx (S15).

Auth is an OAuth refresh token for Arjun's own account, from .env: GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GOOGLE_CALENDAR_ID. The access token is fetched on
first use, reused until a minute before it expires, and fetched again once if Google answers 401.

sendUpdates=all on create and delete is what makes Google email the invite and the cancellation.
Errors become CalendarError: timeout (the outcome is unknown, so booking/execute.py reads the event
by id before trying again), conflict (409: the event id exists), failed (anything else).
Sync, like the adapter: tool handlers and the executor already run in worker threads.
"""

from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import quote

import httpx

from .adapter import CalendarError, Event, Interval

try:
    from config import GOOGLE_CALENDAR_ID, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
except (ImportError, ModuleNotFoundError):
    from backend.config import GOOGLE_CALENDAR_ID, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
TIMEOUT_S = 3.0  # per request; a booking tool allows 8 s in total (tools/registry.py), and may need a token first


def _parse(when: str) -> datetime:
    return datetime.fromisoformat(when)  # Google sends RFC 3339, e.g. 2026-11-09T04:30:00Z


class GoogleCalendar:
    def __init__(self, client_id: str = GOOGLE_CLIENT_ID, client_secret: str = GOOGLE_CLIENT_SECRET,
                 refresh_token: str = GOOGLE_REFRESH_TOKEN, calendar_id: str = GOOGLE_CALENDAR_ID, http: httpx.Client | None = None):
        missing = [name for name, value in (("GOOGLE_CLIENT_ID", client_id), ("GOOGLE_CLIENT_SECRET", client_secret),
                                            ("GOOGLE_REFRESH_TOKEN", refresh_token), ("GOOGLE_CALENDAR_ID", calendar_id)) if not value]
        if missing:
            raise ValueError(f"CALENDAR_BACKEND=google needs {', '.join(missing)} in .env")
        self._client_id, self._client_secret, self._refresh_token = client_id, client_secret, refresh_token
        self._calendar = quote(calendar_id, safe="")  # a calendar id can be an email address
        self._calendar_id = calendar_id
        self._http = http or httpx.Client(timeout=TIMEOUT_S)
        self._token: str | None = None
        self._token_expires = 0.0

    # --- transport ---------------------------------------------------------------

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as err:
            raise CalendarError("timeout", f"{method} {url}: {type(err).__name__}")
        except httpx.HTTPError as err:
            raise CalendarError("failed", f"{method} {url}: {type(err).__name__}")

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        resp = self._send("POST", TOKEN_URL, data={
            "client_id": self._client_id, "client_secret": self._client_secret,
            "refresh_token": self._refresh_token, "grant_type": "refresh_token",
        })
        if resp.status_code != 200:  # the body names the reason (e.g. invalid_grant) and holds no secret
            raise CalendarError("failed", f"token refresh {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        self._token, self._token_expires = body["access_token"], time.monotonic() + body.get("expires_in", 3600)
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in (1, 2):
            resp = self._send(method, f"{API}{path}", headers={"Authorization": f"Bearer {self._access_token()}"}, **kwargs)
            if resp.status_code != 401 or attempt == 2:
                return resp
            self._token = None  # revoked or expired early: fetch a new access token once

    @staticmethod
    def _fail(resp: httpx.Response, what: str) -> CalendarError:
        return CalendarError("conflict" if resp.status_code == 409 else "failed", f"{what} {resp.status_code}: {resp.text[:200]}")

    # --- the four calls -------------------------------------------------------------

    def free_busy(self, start: datetime, end: datetime) -> list[Interval]:
        resp = self._call("POST", "/freeBusy", json={"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                                                     "items": [{"id": self._calendar_id}]})
        if resp.status_code != 200:
            raise self._fail(resp, "freeBusy")
        calendar = resp.json().get("calendars", {}).get(self._calendar_id, {})
        if calendar.get("errors"):  # e.g. notFound: the calendar id is wrong or not shared with this account
            raise CalendarError("failed", f"freeBusy: {calendar['errors']}")
        return [Interval(_parse(b["start"]), _parse(b["end"])) for b in calendar.get("busy", [])]

    def create_event(self, event: Event) -> Event:
        body = {
            "id": event.id,  # our uuid4().hex, so a retry can find it by id
            "summary": event.summary,
            "start": {"dateTime": event.start.isoformat()},
            "end": {"dateTime": event.end.isoformat()},
            "attendees": [{"email": event.attendee_email}],
        }
        resp = self._call("POST", f"/calendars/{self._calendar}/events", params={"sendUpdates": "all"}, json=body)
        if resp.status_code not in (200, 201):
            raise self._fail(resp, "create")
        return event

    def get_event(self, event_id: str) -> Event | None:
        resp = self._call("GET", f"/calendars/{self._calendar}/events/{event_id}")
        if resp.status_code in (404, 410):
            return None
        if resp.status_code != 200:
            raise self._fail(resp, "get")
        data = resp.json()
        if data.get("status") == "cancelled":  # Google still returns a deleted event for a while
            return None
        attendees = data.get("attendees") or [{}]
        return Event(data["id"], _parse(data["start"]["dateTime"]), _parse(data["end"]["dateTime"]),
                     data.get("summary", ""), attendees[0].get("email", ""))

    def delete_event(self, event_id: str) -> None:
        resp = self._call("DELETE", f"/calendars/{self._calendar}/events/{event_id}", params={"sendUpdates": "all"})
        if resp.status_code not in (200, 204, 404, 410):  # already gone counts as deleted
            raise self._fail(resp, "delete")
