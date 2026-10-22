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
    from config import SARVAM_API_KEY, SARVAM_STT_URL, STT_QUEUE_MAX
except (ImportError, ModuleNotFoundError):
    from backend.config import SARVAM_API_KEY, SARVAM_STT_URL, STT_QUEUE_MAX


class SttHandlers(Protocol):
    def on_speech_start(self) -> None: ...
    def on_speech_end(self) -> None: ...
    async def on_partial(self, text: str) -> None: ...
    async def on_final(self, text: str) -> None: ...
    async def on_error(self, message: str) -> None: ...


class SttClient:
    """Lazy-open STT WebSocket client. send_audio() is sync; close() is sync."""

    def __init__(self, handlers: SttHandlers) -> None:
        self._handlers = handlers
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
                SARVAM_STT_URL,
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


def create_stt(handlers: SttHandlers) -> SttClient:
    """Return a ready-to-use SttClient bound to the given handlers."""
    return SttClient(handlers)
