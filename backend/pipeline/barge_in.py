"""barge_in.py: interrupts the agent when the user speaks over it.

Rules a reader would not guess:
- Before any agent audio plays, speech interrupts at once: nothing was heard, so nothing is lost.
- While audio plays, only words interrupt: a partial transcript that is not an acknowledgement
  ("okay", "mm"). A spoken "okay" lasts as long as the start of a real interruption, so the length
  of the sound cannot tell them apart (live test 2.2). A cough gives no words, so it never interrupts.
- If no partial ever comes, the final transcript still replaces the answer when the turn taker commits it.
- interrupt() clears is_answering(), so later partials of the same speech do not interrupt twice.
"""

from __future__ import annotations

from collections.abc import Callable

from backend.pipeline.turn_taking import is_backchannel


class BargeIn:
    def __init__(
        self,
        is_answering: Callable[[], bool],
        is_speaking: Callable[[], bool],
        interrupt: Callable[[], None],
    ) -> None:
        self._is_answering = is_answering
        self._is_speaking = is_speaking
        self._interrupt = interrupt

    def on_speech_start(self) -> None:
        if self._is_answering() and not self._is_speaking():
            self._interrupt()  # no audio playing yet: interrupt immediately

    def on_partial(self, text: str) -> None:
        if self._is_answering() and self._is_speaking() and text.strip() and not is_backchannel(text):
            self._interrupt()
