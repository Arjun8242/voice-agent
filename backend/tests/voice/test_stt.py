"""The STT client's event reader: which Sarvam events reach the connection's handlers. No network."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

from backend.config import SARVAM_STT_URL
from backend.providers.stt import SttClient


class RecordingHandlers:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def on_speech_start(self) -> None:
        self.events.append(("speech_start", ""))

    def on_speech_end(self) -> None:
        self.events.append(("speech_end", ""))

    async def on_partial(self, text: str) -> None:
        self.events.append(("partial", text))

    async def on_final(self, text: str) -> None:
        self.events.append(("final", text))

    async def on_error(self, message: str) -> None:
        self.events.append(("error", message))

    def on_session_end(self, audio_seconds: float | None) -> None:
        self.events.append(("session_end", str(audio_seconds)))


class FakeSocket:
    def __init__(self, *events: dict | str) -> None:
        self.frames = [e if isinstance(e, str) else json.dumps(e) for e in events]

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        for frame in self.frames:
            yield frame


def read(*events: dict | str) -> list[tuple[str, str]]:
    handlers = RecordingHandlers()
    asyncio.run(SttClient(handlers)._reader(FakeSocket(*events)))
    return handlers.events


def test_transcript_events_reach_their_handlers_in_order():
    events = read(
        {"event": "transcript.partial", "text": "the sched"},
        {"event": "transcript.final", "text": " The scheduler. "},
        {"event": "something.new"},  # an event this client does not know is ignored
    )
    assert events == [("partial", "the sched"), ("final", "The scheduler.")]



def test_sarvam_error_event_reaches_the_error_handler():
    assert read({"event": "error", "data": {"message": "bad audio"}}) == [("error", "bad audio")]


def test_error_event_without_a_message_still_reports_an_error():
    assert read({"event": "error"}) == [("error", "unknown error")]


def test_error_message_at_the_top_level_of_the_event_is_read_too():
    assert read({"event": "error", "message": "rate limited"}) == [("error", "rate limited")]


def test_session_end_without_a_duration_reports_none():
    assert read({"event": "session.end"}) == [("session_end", "None")]


def test_session_end_reports_the_billed_audio_seconds():
    assert read({"event": "session.end", "data": {"audio_duration_s": 12.5}}) == [("session_end", "12.5")]


def test_empty_transcripts_and_junk_frames_are_ignored():
    events = read("not json", {"event": "transcript.final", "text": "  "}, {"event": "transcript.final", "text": "hi"})
    assert events == [("final", "hi")]


# --- the URL --------------------------------------------------------------------

def test_sarvam_vad_is_switched_off():
    assert parse_qs(urlsplit(SARVAM_STT_URL).query)["endpointing"] == ["manual"]
