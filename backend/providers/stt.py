"""stt.py: Real-time speech-to-text client backed by Sarvam AI WebSocket.

Sarvam's VAD is off (endpointing=manual): Silero (pipeline/vad.py) decides where speech starts and
ends. Only speech is sent, between speech_start and speech_end messages, and Sarvam sends the final
transcript after speech_end. The speech handlers are called from here, not from Sarvam's events.
"""

import asyncio
import base64
import json
from asyncio import Queue, QueueFull
from typing import Protocol

import websockets

from backend.pipeline.vad import SileroVad, SpeechGate

try:
    from config import (
        SARVAM_API_KEY,
        SARVAM_STT_URL,
        STT_KEEPALIVE_S,
        STT_QUEUE_MAX,
        VAD_INTERVIEW_SILENCE_MS,
        VAD_SILENCE_MS,
    )
except (ImportError, ModuleNotFoundError):
    from backend.config import (
        SARVAM_API_KEY,
        SARVAM_STT_URL,
        STT_KEEPALIVE_S,
        STT_QUEUE_MAX,
        VAD_INTERVIEW_SILENCE_MS,
        VAD_SILENCE_MS,
    )

MAX_AUDIO_BYTES = 8000  # 250 ms per message; Sarvam rejects more than 500 ms (16000 bytes) on stream_type=fast


class SttHandlers(Protocol):
    def on_speech_start(self) -> None: ...
    def on_speech_end(self) -> None: ...
    async def on_partial(self, text: str) -> None: ...
    async def on_final(self, text: str) -> None: ...
    async def on_error(self, message: str) -> None: ...
    def on_session_end(self, audio_seconds: float | None) -> None: ...


class SttClient:
    """Lazy-open STT WebSocket client. send_audio() is sync; close() is sync.

    The socket opens with the first audio, so it is ready when speech starts. mode ("interview" or
    anything else) sets how much silence ends speech; the connection sets it when the interview starts.
    """

    def __init__(self, handlers: SttHandlers) -> None:
        self._handlers = handlers
        self._queue: Queue[str] = Queue(maxsize=STT_QUEUE_MAX)
        self._task: asyncio.Task | None = None
        self._gate = SpeechGate()
        self._vad: SileroVad | None = None  # the model loads with the first audio
        self._mode = "recruiter"

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, mode: str) -> None:
        self._mode = mode
        self._gate.silence_ms = VAD_INTERVIEW_SILENCE_MS if mode == "interview" else VAD_SILENCE_MS

    def send_audio(self, pcm: bytes) -> None:
        """Run Silero on the audio; send Sarvam only speech, wrapped in speech_start and speech_end."""
        if self._vad is None:
            self._vad = SileroVad(self._gate)
        self._open()
        for event in self._vad.feed(pcm):
            if event.kind == "start":
                self._handlers.on_speech_start()
                self._send({"event": "speech_start"})
            for i in range(0, len(event.audio), MAX_AUDIO_BYTES):
                chunk = event.audio[i:i + MAX_AUDIO_BYTES]
                self._send({"event": "audio_input", "audio": base64.b64encode(chunk).decode()})
            if event.kind == "end":
                self._send({"event": "speech_end"})
                self._handlers.on_speech_end()

    def _send(self, message: dict) -> None:
        """Queue a message for Sarvam (send_audio has opened the socket)."""
        try:
            self._queue.put_nowait(json.dumps(message))
        except QueueFull:
            pass

    def _open(self) -> None:
        """Start the socket task if none is running (the first audio, or after Sarvam closed it)."""
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    def close(self) -> None:
        """Cancel the background task (closes the WebSocket via task cancellation)."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        try:
            async with websockets.connect(
                SARVAM_STT_URL,
                additional_headers={"api-subscription-key": SARVAM_API_KEY},
                ping_interval=5,
            ) as ws, asyncio.TaskGroup() as tg:
                tg.create_task(self._sender(ws))
                tg.create_task(self._reader(ws))
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001 - any socket failure is reported to the page as an STT error
            await self._handlers.on_error(str(e))

    async def _sender(self, ws) -> None:
        """Drain the queue and forward frames to the WebSocket; ping when idle so Sarvam keeps the socket."""
        while True:
            try:
                msg = await asyncio.wait_for(self._queue.get(), STT_KEEPALIVE_S)
            except TimeoutError:
                msg = json.dumps({"event": "ping"})
            await ws.send(msg)

    async def _reader(self, ws) -> None:
        """Read events from the WebSocket and dispatch to handlers."""
        async for raw in ws:
            try:
                ev = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            event = ev.get("event", "")

            if event in ("transcript.partial", "transcript.final"):
                text = str(ev.get("text") or "").strip()
                if not text:
                    continue
                if event == "transcript.final":
                    await self._handlers.on_final(text)
                else:
                    await self._handlers.on_partial(text)

            elif event == "error":
                await self._handlers.on_error(_field(ev, "message") or "unknown error")

            elif event == "session.end":
                self._handlers.on_session_end(_field(ev, "audio_duration_s"))  # what Sarvam bills for this socket


def _field(ev: dict, name: str):
    """A field from the top level of a Sarvam event or from its data object (both shapes appear in the docs)."""
    data = ev.get("data")
    return ev.get(name) if name in ev else data.get(name) if isinstance(data, dict) else None


def create_stt(handlers: SttHandlers) -> SttClient:
    """Return a ready-to-use SttClient bound to the given handlers."""
    return SttClient(handlers)
