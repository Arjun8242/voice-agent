"""barge_in.py: interrupts the agent when the user speaks over it.

Corresponds to src/pipeline/bargeIn.ts.
"""
import asyncio
from typing import Callable


class BargeIn:
    def __init__(
        self,
        is_answering: Callable[[], bool],
        is_speaking: Callable[[], bool],
        interrupt: Callable[[], None],
        confirm_ms: float = 300,
    ) -> None:
        self._is_answering = is_answering
        self._is_speaking = is_speaking
        self._interrupt = interrupt
        self._confirm_s = confirm_ms / 1000
        self._timer: asyncio.TimerHandle | None = None

    def _clear_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def on_speech_start(self) -> None:
        if not self._is_answering():
            return  # pipeline idle, nothing to interrupt
        if not self._is_speaking():
            self._interrupt()  # no audio playing yet, interrupt immediately
            return
        # Audio is playing: wait before interrupting to avoid mic bleed-through
        self._clear_timer()
        self._timer = asyncio.get_running_loop().call_later(self._confirm_s, self._fire)

    def _fire(self) -> None:
        self._timer = None
        if self._is_answering():  # re-check: turn may have finished naturally
            self._interrupt()

    def on_speech_end(self) -> None:
        self._clear_timer()

    def dispose(self) -> None:
        self._clear_timer()
