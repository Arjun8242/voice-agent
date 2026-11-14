"""The STT client's event reader: which Sarvam events reach the connection's handlers. No network."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

from backend.providers.stt import SttClient, stt_url


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


def test_speech_and_transcript_events_reach_their_handlers_in_order():
    events = read(
        {"event": "vad.speech_start"},
        {"event": "transcript.partial", "text": "the sched"},
        {"event": "vad.speech_end"},
        {"event": "transcript.final", "text": " The scheduler. "},
        {"event": "something.new"},  # an event this client does not know is ignored
    )
    assert events == [("speech_start", ""), ("partial", "the sched"), ("speech_end", ""), ("final", "The scheduler.")]


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


# --- the URL per mode ---------------------------------------------------------

def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_recruiter_mode_keeps_the_provider_default_silence():
    assert "silence_duration_ms" not in query(stt_url("recruiter"))


def test_an_unknown_mode_is_treated_like_recruiter_mode():
    assert stt_url("something else") == stt_url("recruiter")


def test_interview_mode_asks_for_one_second_of_silence_and_changes_nothing_else():
    recruiter, interview = query(stt_url("recruiter")), query(stt_url("interview"))
    assert interview.pop("silence_duration_ms") == ["1000"]  # the plan's starting value; Sarvam's default is 500
    assert interview == recruiter  # language, model and stream type are untouched
    assert urlsplit(stt_url("interview")).path == urlsplit(stt_url("recruiter")).path


def test_the_client_connects_to_the_url_it_holds_when_audio_first_arrives(monkeypatch):
    opened: list[str] = []

    def connect(url, **kwargs):
        opened.append(url)
        raise OSError("no network in tests")

    monkeypatch.setattr("backend.providers.stt.websockets.connect", connect)

    async def scenario():
        handlers = RecordingHandlers()
        client = SttClient(handlers)
        client.url = stt_url("interview")  # set after creation, as the connection does on session_start
        client.send_audio(b"\x00\x00")
        await asyncio.sleep(0.05)
        assert handlers.events == [("error", "no network in tests")]

    asyncio.run(scenario())
    assert opened == [stt_url("interview")]
