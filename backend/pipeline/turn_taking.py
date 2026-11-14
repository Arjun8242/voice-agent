"""turn_taking.py: decides when the speaker has finished their turn.

Sarvam's VAD says "you stopped making sound"; this decides "you stopped making your point"
(docs/interviewer-mode-plan.md §6.1). After each final transcript it waits a hold time, longer
when the words sound unfinished or the speaker asked for time, and any new speech cancels the
wait. Finals are merged into one turn until the hold expires.

Rules a reader would not guess:
- A short acknowledgement ("okay", "mm") while the agent is answering is dropped, never a turn.
  If a barge-in had fired, the agent would no longer be answering, so no extra flag is needed.
- Speech that starts within reopen_ms of a commit, before any agent audio has played, re-opens
  the turn: the connection cancels the launched turn and the old text is merged with the new.
- Every timer is cancelled before a new one is set and when speech starts, so a stale callback
  never runs (a cancelled asyncio handle is skipped even if it was already due).

Timers go through a clock object (LoopClock by default: the running loop's call_later), so tests
can pass their own and move time by hand. Handles are cancelled in dispose(), as in barge_in.py.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

BACKCHANNELS = {
    "okay", "ok", "mm", "hmm", "mhm", "mm hmm", "uh huh", "yeah", "yes", "right", "sure", "got it",
    "okay okay", "yeah yeah", "right right", "haan", "acha", "achha",
}
UNFINISHED_ENDINGS = {
    "and", "so", "because", "but", "or", "um", "uh", "like", "basically", "which", "then", "the", "a",
    "matlab", "toh",
}
THINK_PHRASES = (
    "let me think", "give me a moment", "give me a minute", "give me a second", "give me a sec",
    "one moment", "one second", "one sec", "hold on", "let me see",
)
# A request for time counts only at the end of a final ("..., let me think for a second."), so
# "hold on to the lock" is an answer. Longest phrases first, or "one sec" would win over "one second".
THINK_REQUEST = re.compile(
    r"[\s,.!?…-]*\b(?:" + "|".join(sorted(map(re.escape, THINK_PHRASES), key=len, reverse=True)) + r")"
    r"(?:\s+(?:about (?:it|that)|for (?:a|one) (?:second|sec|moment|minute)))?(?:,?\s+please)?[\s.!?…]*$",
    re.IGNORECASE,
)
DONE_PHRASES = ("that's it", "that is it", "i'm done", "i am done", "that's all", "that is all", "that's my answer")


@dataclass(frozen=True)
class TurnPolicy:
    """Hold times per mode. Starting hypotheses from the plan (§6.1), to be tuned after measuring."""

    base_hold_ms: float  # after a final that looks complete
    long_hold_ms: float  # after a final ending in a filler or conjunction
    think_hold_ms: float  # after "let me think"
    reopen_ms: float  # speech this soon after a commit re-opens the turn
    nudge_ms: tuple[float, ...] = ()  # silence after the agent's question before each nudge


RECRUITER_POLICY = TurnPolicy(base_hold_ms=300, long_hold_ms=800, think_hold_ms=800, reopen_ms=800)
INTERVIEW_POLICY = TurnPolicy(base_hold_ms=1200, long_hold_ms=2500, think_hold_ms=20000, reopen_ms=1500,
                              nudge_ms=(15000, 45000))


def normalize(text: str) -> str:
    """Lowercase words with punctuation removed, apostrophes kept: "Okay." -> "okay"."""
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split())


def is_backchannel(text: str) -> bool:
    words = normalize(text)
    return len(words.split()) <= 2 and words in BACKCHANNELS


def classify_ending(text: str) -> str:
    """'think', 'done', 'unfinished' or 'complete' for the latest final of a turn."""
    if THINK_REQUEST.search(text):
        return "think"
    words = normalize(text)
    if words.endswith(DONE_PHRASES):
        return "done"
    last = words.rsplit(" ", 1)[-1] if words else ""
    if last in UNFINISHED_ENDINGS or text.rstrip().endswith((",", "...", "…")):
        return "unfinished"
    return "complete"


def remove_think_request(text: str) -> str:
    """A final without its trailing "let me think": the request is not part of the answer."""
    return THINK_REQUEST.sub("", text).strip()


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class Clock(Protocol):
    """Where TurnTaker gets time from. Seconds, like the event loop."""

    def now(self) -> float: ...
    def call_later(self, delay_s: float, callback: Callable[..., None], *args: Any) -> TimerHandle: ...


class LoopClock:
    """The running event loop's time and timers."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    def call_later(self, delay_s: float, callback: Callable[..., None], *args: Any) -> TimerHandle:
        return asyncio.get_running_loop().call_later(delay_s, callback, *args)


class TurnTaker:
    """One per connection. The connection forwards STT events; commit(text) is called once per turn.

    is_answering: the agent has a turn running or its audio is still playing.
    reopen_turn: cancel the just-launched turn if no agent audio played yet; True if it did.
    on_state: 'speaking', 'holding', 'thinking' or 'idle' when the state changes (for the browser indicator).
    on_nudge: called with 0, 1, ... when the speaker stays silent after the agent's question.
    """

    def __init__(
        self,
        commit: Callable[[str], None],
        is_answering: Callable[[], bool],
        reopen_turn: Callable[[], bool],
        policy: TurnPolicy = RECRUITER_POLICY,
        on_state: Callable[[str], None] | None = None,
        on_nudge: Callable[[int], None] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or LoopClock()
        self._commit = commit
        self._is_answering = is_answering
        self._reopen_turn = reopen_turn
        self.policy = policy
        self._on_state = on_state or (lambda state: None)
        self._on_nudge = on_nudge or (lambda index: None)
        self.state = "idle"
        self.pending_text = ""
        self._timer: TimerHandle | None = None
        self._nudge_timers: list[TimerHandle] = []
        self._last_final = ""  # the latest final of the pending turn: its ending picks the hold
        self._last_commit: tuple[str, float, int] | None = None  # text, loop time, finals merged
        self.last_decision = ""  # why the last hold was chosen, for the turn log
        self.last_segments = 0  # how many finals the last committed turn merged, for the turn log
        self._segments = 0
        self._reopened = False

    # --- STT events ---------------------------------------------------------

    def on_speech_start(self) -> None:
        self._cancel_timer()
        self._cancel_nudges()
        if not self.pending_text and self._recently_committed() and self._reopen_turn():
            self.pending_text, self._segments = self._last_commit[0], self._last_commit[2]
            self._last_final = self.pending_text
            self._reopened = True
        self._set_state("speaking")

    def on_partial(self, text: str) -> None:
        """Still talking: push a running hold back, never cancel it (a late partial must not strand the turn)."""
        if text.strip() and self._timer is not None:
            self._schedule(self._hold_for(self._last_final))

    def on_speech_end(self) -> None:
        """A cough or noise cancelled the hold and no final followed: restart it so the turn still commits."""
        if self._last_final and self.state == "speaking":  # a turn is open, even if it is only "let me think"
            self._schedule(self._hold_for(self._last_final))

    def on_final(self, text: str) -> bool:
        """Add a final transcript to the turn. False if it was dropped as an acknowledgement."""
        if not self.pending_text and self._is_answering() and is_backchannel(text):
            self.last_decision = "backchannel_dropped"
            return False
        self._cancel_nudges()
        self.pending_text = f"{self.pending_text} {remove_think_request(text)}".strip()
        self._segments += 1
        self._last_final = text
        if classify_ending(text) == "done":
            self.last_decision = "done_phrase"
            self._commit_now()
            return True
        self._schedule(self._hold_for(text))
        return True

    # --- agent events ---------------------------------------------------------

    def on_question_finished(self) -> None:
        """The agent's audio finished playing: start the silence clock for nudges."""
        self._cancel_nudges()
        for index, delay_ms in enumerate(self.policy.nudge_ms):
            handle = self._clock.call_later(delay_ms / 1000, self._fire_nudge, index)
            self._nudge_timers.append(handle)

    def drop_pending(self) -> None:
        """A card click replaces whatever was being said: forget the held words so they never start a turn."""
        self._cancel_timer()
        self.pending_text = self._last_final = ""
        self._segments = 0
        self._set_state("idle")

    def dispose(self) -> None:
        self._cancel_timer()
        self._cancel_nudges()

    # --- internals ------------------------------------------------------------

    def _hold_for(self, text: str) -> float:
        kind = classify_ending(text)
        self.last_decision = {"think": "think", "unfinished": "long_hold"}.get(kind, "base_hold")
        if kind == "think":
            return self.policy.think_hold_ms
        return self.policy.long_hold_ms if kind == "unfinished" else self.policy.base_hold_ms

    def _schedule(self, hold_ms: float) -> None:
        self._cancel_timer()
        self._timer = self._clock.call_later(hold_ms / 1000, self._commit_now)
        self._set_state("thinking" if self.last_decision == "think" else "holding")

    def _commit_now(self) -> None:
        self._cancel_timer()
        text = self.pending_text
        self.pending_text = self._last_final = ""
        self.last_segments, self._segments = self._segments, 0
        if self._reopened:  # the log should say this turn was re-opened, not which hold ended it
            self.last_decision, self._reopened = "reopened", False
        self._set_state("idle")
        if not text:
            self._on_nudge(0)  # only "let me think" and then silence: nothing to answer, so check in gently
            return
        self._last_commit = (text, self._clock.now(), self.last_segments)
        self._commit(text)

    def _recently_committed(self) -> bool:
        if self._last_commit is None:
            return False
        age_ms = (self._clock.now() - self._last_commit[1]) * 1000
        return age_ms < self.policy.reopen_ms

    def _fire_nudge(self, index: int) -> None:
        if self.state == "idle" and not self._is_answering():
            self._on_nudge(index)

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._on_state(state)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _cancel_nudges(self) -> None:
        for handle in self._nudge_timers:
            handle.cancel()
        self._nudge_timers = []
