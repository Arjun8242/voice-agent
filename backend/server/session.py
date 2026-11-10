"""session.py: Conversation state and turn lifecycle helpers.

Corresponds to src/server/session.ts.
"""
import asyncio
from typing import Any

REPORT_WAIT_S = 1.0  # how long a new turn waits for the client's playback report
CUT_OFF_NOTE = "(the visitor interrupted here)"


class Conversation:
    def __init__(self):
        self.sentence_counter: int = 0
        self.agent_speaking: bool = False  # audio was sent and the browser has not said it finished playing
        self.speech_ended_at: float | None = None  # when STT last heard the visitor stop (for stt_ms)
        self.current: asyncio.Task | None = None
        # Barge-in bookkeeping: what the visitor really heard of a cut-off answer.
        self.sentences: list[tuple[int, str]] = []  # (sentence id, text) queued for speech this turn
        self.cut_off_sentences: list[tuple[int, str]] = []  # copy of the above, taken at the interrupt
        self.waiting_for_report: int | None = None  # turn id whose playback report has not arrived
        self.report_arrived = asyncio.Event()
        self.heard: str = ""  # heard text of the cut-off turn, taken by the next turn


def new_conversation() -> Conversation:
    return Conversation()


def start_turn(c: Conversation, task: asyncio.Task) -> asyncio.Task:
    """Cancel any in-flight turn, store the new task, reset agent_speaking."""
    if c.current is not None:
        c.current.cancel()
    c.current = task
    c.agent_speaking = False
    c.sentences = []
    return task


def interrupt_turn(c: Conversation) -> None:
    """Cancel and clear the current turn (barge-in or connection close)."""
    if c.current is not None:
        c.current.cancel()
    c.current = None
    c.agent_speaking = False


def finish_turn(c: Conversation, task: asyncio.Task) -> None:
    """Clear current only if this task is still the active one."""
    if c.current is task:
        c.current = None


def is_answering(c: Conversation) -> bool:
    """A turn is running, or its audio is still playing in the browser (agent_speaking stays
    True after the turn ends, until the browser sends playback_ended or the next turn starts)."""
    return c.current is not None or c.agent_speaking


def heard_reply(sentences: list[tuple[int, str]], last_heard_id) -> str:
    """The answer text up to and including sentence last_heard_id, with a note that the visitor cut in.

    last_heard_id is the sentence that was playing when the visitor interrupted (it is kept in
    full). Returns "" when nothing had started playing.
    """
    if not isinstance(last_heard_id, int):
        return ""
    heard = [text for sid, text in sentences if sid <= last_heard_id]
    return " ".join(heard) + " " + CUT_OFF_NOTE if heard else ""


def cut_off(c: Conversation, turn_id: int) -> None:
    """Barge-in: remember what the turn had queued, then wait for the client to say how much was heard."""
    if not c.sentences:
        # Nothing of this turn was spoken (e.g. it was still waiting for an earlier report).
        # Keep any earlier cut-off's pending report instead of wiping it.
        return
    c.waiting_for_report = turn_id
    c.cut_off_sentences = list(c.sentences)
    c.heard = ""
    c.report_arrived = asyncio.Event()


def record_report(c: Conversation, turn_id, last_heard_id) -> None:
    """The client's playback_progress. Ignored unless it is for the turn we are waiting on."""
    if c.waiting_for_report is None or turn_id != c.waiting_for_report:
        return
    c.heard = heard_reply(c.cut_off_sentences, last_heard_id)
    c.waiting_for_report = None
    c.report_arrived.set()


async def take_heard(c: Conversation, timeout: float = REPORT_WAIT_S) -> str:
    """Heard text of the last cut-off answer, for the next turn's history. Waits briefly for a late report."""
    if c.waiting_for_report is not None:
        try:
            await asyncio.wait_for(c.report_arrived.wait(), timeout)
        except asyncio.TimeoutError:
            c.waiting_for_report = None  # a report that comes after this is ignored
    heard, c.heard = c.heard, ""
    return heard
