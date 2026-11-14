"""stt.py: Real-time speech-to-text client backed by Sarvam AI WebSocket.

Corresponds to src/providers/stt.ts.
"""

import asyncio
import base64
import json
from asyncio import Queue, QueueFull
from typing import Protocol
import websockets

try:
    from config import SARVAM_API_KEY, SARVAM_STT_URL, STT_INTERVIEW_SILENCE_MS, STT_QUEUE_MAX
except (ImportError, ModuleNotFoundError):
    from backend.config import SARVAM_API_KEY, SARVAM_STT_URL, STT_INTERVIEW_SILENCE_MS, STT_QUEUE_MAX


def stt_url(mode: str) -> str:
    """The Sarvam realtime URL for a conversation mode: interview mode asks for a longer end-of-speech silence."""
    if mode == "interview":
        return f"{SARVAM_STT_URL}&silence_duration_ms={STT_INTERVIEW_SILENCE_MS}"
    return SARVAM_STT_URL


class SttHandlers(Protocol):
    def on_speech_start(self) -> None: ...
    def on_speech_end(self) -> None: ...
    async def on_partial(self, text: str) -> None: ...
    async def on_final(self, text: str) -> None: ...
    async def on_error(self, message: str) -> None: ...
    def on_session_end(self, audio_seconds: float | None) -> None: ...


class SttClient:
    """Lazy-open STT WebSocket client. send_audio() is sync; close() is sync.

    url is read when the socket opens (on the first audio), so the connection can still set it
    after it learns the mode from the browser's session_start.
    """

    def __init__(self, handlers: SttHandlers, url: str = SARVAM_STT_URL) -> None:
        self._handlers = handlers
        self.url = url
        self._queue: Queue[str] = Queue(maxsize=STT_QUEUE_MAX)
        self._task: asyncio.Task | None = None

    def send_audio(self, pcm: bytes) -> None:
        """Encode PCM to base64, enqueue the JSON frame. Lazy-opens the connection."""
        msg = json.dumps({
            "event": "audio_input",
            "audio": base64.b64encode(pcm).decode(),
        })
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

        try:
            self._queue.put_nowait(msg)
        except QueueFull:
            pass

    def close(self) -> None:
        """Cancel the background task (closes the WebSocket via task cancellation)."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        try:
            async with websockets.connect(
                self.url,
                additional_headers={"api-subscription-key": SARVAM_API_KEY},
                ping_interval=5,
            ) as ws:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._sender(ws))
                    tg.create_task(self._reader(ws))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._handlers.on_error(str(e))

    async def _sender(self, ws) -> None:
        """Drain the queue and forward frames to the WebSocket."""
        while True:
            msg = await self._queue.get()
            await ws.send(msg)

    async def _reader(self, ws) -> None:
        """Read events from the WebSocket and dispatch to handlers."""
        async for raw in ws:
            try:
                ev = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            event = ev.get("event", "")

            if event == "vad.speech_start":
                self._handlers.on_speech_start()

            elif event == "vad.speech_end":
                self._handlers.on_speech_end()

            elif event in ("transcript.partial", "transcript.final"):
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
