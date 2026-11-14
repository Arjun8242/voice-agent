"""TurnTaker: when a speaker's turn is complete (docs/interviewer-mode-plan.md §6.1, scenarios T1-T13).

Time is a FakeClock the test moves by hand, so every boundary is exact ("not at 299 ms, yes at 300 ms")
and nothing depends on how fast the machine is. No asyncio, no sleeps.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.pipeline.turn_taking import (
    TurnPolicy,
    TurnTaker,
    classify_ending,
    is_backchannel,
    remove_think_request,
)

POLICY = TurnPolicy(base_hold_ms=300, long_hold_ms=800, think_hold_ms=5000, reopen_ms=800, nudge_ms=(15000, 45000))


class FakeHandle:
    cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeClock:
    """call_later timers that fire only when the test advances time, in due order."""

    def __init__(self) -> None:
        self.now_ms = 0
        self._timers: list[tuple[int, int, Callable[..., None], tuple, FakeHandle]] = []

    def now(self) -> float:
        return self.now_ms / 1000

    def call_later(self, delay_s: float, callback: Callable[..., None], *args: object) -> FakeHandle:
        handle = FakeHandle()
        self._timers.append((self.now_ms + round(delay_s * 1000), len(self._timers), callback, args, handle))
        return handle

    def advance(self, ms: int) -> None:
        target = self.now_ms + ms
        while True:
            due = sorted(t for t in self._timers if t[0] <= target and not t[4].cancelled)
            if not due:
                break
            timer = due[0]
            self._timers.remove(timer)
            self.now_ms = timer[0]
            timer[2](*timer[3])
        self.now_ms = target


class Scene:
    """A TurnTaker with a fake clock and a stand-in for the connection: it records what the taker asks for."""

    def __init__(self, answering: bool = False, audio_played: bool = False, policy: TurnPolicy = POLICY) -> None:
        self.clock = FakeClock()
        self.commits: list[str] = []
        self.nudges: list[int] = []
        self.states: list[str] = []
        self.answering, self.audio_played, self.reopened = answering, audio_played, 0
        self.taker = TurnTaker(self._commit, lambda: self.answering, self._reopen, policy,
                               self.states.append, self.nudges.append, clock=self.clock)

    def _commit(self, text: str) -> None:
        self.commits.append(text)
        self.answering = True  # the connection launches a turn

    def _reopen(self) -> bool:
        if not self.answering or self.audio_played:
            return False
        self.reopened += 1
        self.answering = False  # the connection cancelled the launched turn
        return True

    def say(self, text: str) -> bool:
        """One spoken segment: speech start, then its final transcript."""
        self.taker.on_speech_start()
        return self.taker.on_final(text)


# --- text cues -----------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "okay", "Okay.", "OK", "mm", "Mm-hmm.", "uh-huh", "yeah", "Yes!", "right", "Right, right.", "got it", "sure", "haan",
])
def test_short_acknowledgements_are_backchannels(text):
    assert is_backchannel(text)


@pytest.mark.parametrize("text", [
    "okay so", "okay got it then", "yes because redis", "right now", "it uses a lock", "no", "what", "sure thing", "",
])
def test_answers_and_questions_are_not_backchannels(text):
    assert not is_backchannel(text)


@pytest.mark.parametrize("text, kind", [
    ("It uses Postgres.", "complete"),
    ("I used the band saw", "complete"),  # "band" contains "and" but does not end the sentence
    ("it scales on demand", "complete"),
    ("hold on to the lock until the job ends", "complete"),  # "hold on" inside an answer is not a request for time
    ("let me think it uses a lock", "complete"),  # the answer follows in the same breath
    ("The scheduler uses a lock and", "unfinished"),
    ("the reason is because", "unfinished"),
    ("so the reason is, um", "unfinished"),
    ("it retries three times,", "unfinished"),
    ("well...", "unfinished"),
    ("to phir queue matlab", "unfinished"),
    ("that's it for the queue and", "unfinished"),  # a done phrase only counts at the very end
    ("Hmm, let me think for a second.", "think"),
    ("give me a moment", "think"),
    ("Give me a minute, please.", "think"),
    ("the reason is, let me think", "think"),
    ("one second", "think"),
    ("It retries three times. That's it.", "done"),
    ("I think that's all", "done"),
    ("I'm done.", "done"),
])
def test_endings_are_classified_by_how_the_final_ends(text, kind):
    assert classify_ending(text) == kind


@pytest.mark.parametrize("text, kept", [
    ("Let me think.", ""),
    ("Hmm, let me think for a second.", "Hmm"),
    ("the reason is, let me think", "the reason is"),
    ("Give me a minute, please.", ""),
    ("one second", ""),
    ("hold on to the lock", "hold on to the lock"),  # not at the end: left alone
    ("let me think it uses a lock", "let me think it uses a lock"),
    ("It uses a lock.", "It uses a lock."),
])
def test_only_a_trailing_request_for_time_is_removed(text, kept):
    assert remove_think_request(text) == kept


# --- hold timers: exact boundaries ---------------------------------------------------

def test_complete_sentence_commits_exactly_when_the_base_hold_ends():  # T4
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(299)
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["It uses Postgres."]


def test_unfinished_ending_waits_the_long_hold_not_the_base_hold():  # T2, T7
    s = Scene()
    s.say("the queue holds jobs and")
    s.clock.advance(799)
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["the queue holds jobs and"]


def test_request_for_time_waits_the_think_hold_and_is_left_out():  # T5
    s = Scene()
    s.say("The reason is, let me think.")
    assert s.taker.state == "thinking"
    s.clock.advance(4999)
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["The reason is"]


def test_the_hold_is_measured_from_the_latest_final():  # T1, T6
    s = Scene()
    s.say("the scheduler")
    s.clock.advance(200)
    s.say("uses a lock")
    s.clock.advance(299)  # 499 ms after the first final: its own hold would have fired at 300
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["the scheduler uses a lock"]


def test_the_latest_final_decides_the_hold_not_the_earlier_ones():
    s = Scene()
    s.say("the queue holds jobs and")  # long hold
    s.clock.advance(100)
    s.say("workers pull them.")  # complete: base hold
    s.clock.advance(300)
    assert s.commits == ["the queue holds jobs and workers pull them."]


def test_answer_after_a_request_for_time_commits_without_the_request():  # T5
    s = Scene()
    s.say("Let me think.")
    s.clock.advance(3000)
    s.say("It is an advisory lock.")
    s.clock.advance(300)
    assert s.commits == ["It is an advisory lock."]


def test_done_phrase_commits_without_waiting():
    s = Scene()
    s.say("It retries. That's it.")
    assert s.commits == ["It retries. That's it."] and s.taker.state == "idle"


def test_speech_start_cancels_the_hold_until_the_next_final():
    s = Scene()
    s.say("the scheduler")
    s.clock.advance(100)
    s.taker.on_speech_start()
    s.clock.advance(60_000)  # still talking: however long it takes, nothing commits
    assert s.commits == []
    s.taker.on_final("uses a lock")
    s.clock.advance(300)
    assert s.commits == ["the scheduler uses a lock"]


def test_speech_start_one_millisecond_before_the_hold_ends_keeps_one_turn():  # T13, speech first
    s = Scene()
    s.say("the scheduler")
    s.clock.advance(299)
    s.taker.on_speech_start()
    s.clock.advance(10)  # the cancelled timer's moment passes
    assert s.commits == []
    s.taker.on_final("uses a lock")
    s.clock.advance(300)
    assert s.commits == ["the scheduler uses a lock"] and s.reopened == 0


# --- partials, noise and coughs ---------------------------------------------------------

def test_partial_during_a_hold_pushes_it_back():
    s = Scene()
    s.say("the scheduler")
    s.clock.advance(200)
    s.taker.on_partial("uses")
    s.clock.advance(299)
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["the scheduler"]  # the partial's words arrive with their own final, not here


def test_empty_partial_does_not_push_the_hold_back():
    s = Scene()
    s.say("the scheduler")
    s.clock.advance(200)
    s.taker.on_partial("   ")
    s.clock.advance(100)
    assert s.commits == ["the scheduler"]


def test_partial_with_nothing_held_starts_no_timer():
    s = Scene()
    s.taker.on_speech_start()
    s.taker.on_partial("the sched")
    s.clock.advance(60_000)
    assert s.commits == [] and s.taker.state == "speaking"


def test_noise_without_a_final_commits_nothing():  # T11
    s = Scene()
    s.taker.on_speech_start()
    s.taker.on_speech_end()
    s.clock.advance(60_000)
    assert s.commits == [] and s.nudges == []


def test_cough_during_the_hold_restarts_it_so_the_turn_still_commits():
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(100)
    s.taker.on_speech_start()  # a cough cancels the hold
    s.clock.advance(50)
    s.taker.on_speech_end()  # and no final follows
    s.clock.advance(299)
    assert s.commits == []
    s.clock.advance(1)
    assert s.commits == ["It uses Postgres."]


def test_cough_after_the_answer_uses_the_answers_hold_not_the_earlier_think_hold():
    s = Scene()
    s.say("Let me think.")
    s.say("It is a lock.")
    s.taker.on_speech_start()
    s.taker.on_speech_end()
    s.clock.advance(300)  # not 5000: the latest final was a complete sentence
    assert s.commits == ["It is a lock."]


# --- while the agent is answering ---------------------------------------------------------

def test_acknowledgement_while_the_agent_answers_is_dropped_silently():  # T12
    s = Scene(answering=True, audio_played=True)
    s.taker.on_speech_start()
    states_before = list(s.states)
    assert s.taker.on_final("Okay.") is False
    s.clock.advance(60_000)
    assert s.commits == [] and s.states == states_before and s.taker.last_decision == "backchannel_dropped"


def test_acknowledgement_when_the_agent_is_quiet_is_an_answer():
    s = Scene()
    assert s.say("yes") is True
    s.clock.advance(300)
    assert s.commits == ["yes"]


def test_real_words_while_the_agent_answers_are_a_turn():
    s = Scene(answering=True, audio_played=True)
    assert s.say("what about Beacon") is True
    s.clock.advance(300)
    assert s.commits == ["what about Beacon"]


def test_acknowledgement_after_held_words_belongs_to_the_turn():
    s = Scene(answering=True, audio_played=True)
    s.say("the scheduler")
    assert s.say("yeah") is True  # mid-sentence it is part of what they are saying, not a nod to the agent
    s.clock.advance(300)
    assert s.commits == ["the scheduler yeah"]


# --- re-open after an early commit -----------------------------------------------------------

def reopen_scene(gap_ms: int, audio_played: bool = False) -> Scene:
    """A turn is committed, then the speaker starts again gap_ms later."""
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(300)
    assert s.commits == ["It uses Postgres."]
    s.audio_played = audio_played
    s.clock.advance(gap_ms)
    s.say("because of transactions")
    s.clock.advance(300)
    return s


def test_speech_just_inside_the_window_reopens_and_merges_the_turn():  # T3, T13 (timer first)
    s = reopen_scene(gap_ms=799)
    assert s.reopened == 1
    assert s.commits == ["It uses Postgres.", "It uses Postgres. because of transactions"]
    assert (s.taker.last_decision, s.taker.last_segments) == ("reopened", 2)


def test_speech_at_the_end_of_the_window_is_a_new_turn():
    s = reopen_scene(gap_ms=800)
    assert s.reopened == 0 and s.commits[-1] == "because of transactions"
    assert (s.taker.last_decision, s.taker.last_segments) == ("base_hold", 1)


def test_speech_after_the_agents_audio_started_does_not_reopen():
    s = reopen_scene(gap_ms=100, audio_played=True)
    assert s.reopened == 0 and s.commits[-1] == "because of transactions"


def test_speech_after_the_agents_turn_ended_does_not_reopen():
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(300)
    s.answering = False  # the agent already finished and its audio is over
    s.say("and Redis")
    s.clock.advance(300)
    assert s.reopened == 0 and s.commits == ["It uses Postgres.", "and Redis"]


def test_a_turn_is_reopened_only_once_per_commit():
    s = reopen_scene(gap_ms=100)
    s.answering = False
    s.clock.advance(100)
    s.say("okay next")
    s.clock.advance(300)
    assert s.reopened == 1 and s.commits[-1] == "okay next"


# --- what the connection is told ------------------------------------------------------------

def test_states_follow_speaking_holding_idle():
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(300)
    assert s.states == ["speaking", "holding", "idle"]


def test_states_show_thinking_then_speaking_again():
    s = Scene()
    s.say("let me think")
    s.say("it is a lock")
    assert s.states == ["speaking", "thinking", "speaking", "holding"]


@pytest.mark.parametrize("finals, decision, segments", [
    (["It uses Postgres."], "base_hold", 1),
    (["the queue and"], "long_hold", 1),
    (["It retries.", "That's it."], "done_phrase", 2),
    (["let me think", "one", "two"], "base_hold", 3),
])
def test_the_log_gets_why_the_turn_was_taken_and_how_many_finals_it_merged(finals, decision, segments):
    s = Scene()
    for text in finals:
        s.say(text)
    s.clock.advance(5000)
    assert len(s.commits) == 1
    assert (s.taker.last_decision, s.taker.last_segments) == (decision, segments)


def test_dispose_cancels_the_pending_commit_and_the_nudges():  # T16
    s = Scene()
    s.taker.on_question_finished()
    s.say("It uses Postgres.")
    s.taker.on_question_finished()
    s.taker.dispose()
    s.clock.advance(60_000)
    assert s.commits == [] and s.nudges == []


# --- nudges ------------------------------------------------------------------------------------

def test_silence_after_the_question_gets_each_nudge_at_its_time():
    s = Scene()
    s.taker.on_question_finished()
    s.clock.advance(14_999)
    assert s.nudges == []
    s.clock.advance(1)
    assert s.nudges == [0]
    s.clock.advance(29_999)
    assert s.nudges == [0]
    s.clock.advance(1)
    assert s.nudges == [0, 1]
    s.clock.advance(600_000)
    assert s.nudges == [0, 1]  # never more than the policy lists


def test_speech_cancels_the_nudges():
    s = Scene()
    s.taker.on_question_finished()
    s.clock.advance(1000)
    s.taker.on_speech_start()
    s.clock.advance(60_000)
    assert s.nudges == []


def test_a_final_without_a_speech_start_also_cancels_the_nudges():
    s = Scene()
    s.taker.on_question_finished()
    s.taker.on_final("It uses Postgres.")  # STT may send the final with no speech-start before it
    s.answering = False
    s.clock.advance(60_000)
    assert s.nudges == []


def test_no_nudge_while_the_agent_is_talking():
    s = Scene()
    s.taker.on_question_finished()
    s.answering = True  # e.g. a card click started a turn
    s.clock.advance(60_000)
    assert s.nudges == []


def test_a_new_question_restarts_the_silence_clock():
    s = Scene()
    s.taker.on_question_finished()
    s.clock.advance(10_000)
    s.taker.on_question_finished()
    s.clock.advance(14_999)  # 24 999 ms after the first question: its nudge would have fired at 15 000
    assert s.nudges == []
    s.clock.advance(1)
    assert s.nudges == [0]


def test_request_for_time_then_silence_gets_one_gentle_nudge_and_no_turn():
    s = Scene()
    s.say("give me a moment")
    s.clock.advance(4999)
    assert s.nudges == []
    s.clock.advance(1)
    assert s.commits == [] and s.nudges == [0] and s.taker.state == "idle"


def test_partial_after_a_request_for_time_keeps_the_think_hold():
    s = Scene()
    s.say("give me a moment")
    s.clock.advance(1000)
    s.taker.on_partial("so")  # pushed back by the think hold, not the short base hold
    s.clock.advance(4999)
    assert s.nudges == []
    s.clock.advance(1)
    assert s.nudges == [0]


def test_cough_after_a_request_for_time_does_not_cancel_the_wait_for_good():
    s = Scene()
    s.say("give me a moment")
    s.clock.advance(1000)
    s.taker.on_speech_start()  # a cough cancels the think hold
    s.taker.on_speech_end()  # no final follows: the wait starts again
    assert s.taker.state == "thinking"
    s.clock.advance(5000)
    assert s.nudges == [0] and s.commits == []


def test_noise_after_a_finished_turn_commits_nothing_and_nudges_nobody():
    s = Scene()
    s.say("It uses Postgres.")
    s.clock.advance(300)
    s.answering = False  # the agent answered and its audio is over
    s.clock.advance(5000)
    s.taker.on_speech_start()
    s.taker.on_speech_end()  # noise: no final follows, and no turn is open
    s.clock.advance(60_000)
    assert s.commits == ["It uses Postgres."] and s.nudges == []


def test_dropping_held_words_cancels_their_turn_and_the_next_turn_starts_clean():
    s = Scene()
    s.say("the scheduler")
    s.taker.drop_pending()  # the visitor clicked a card instead
    s.clock.advance(60_000)
    assert s.commits == [] and s.taker.state == "idle"
    s.say("It uses Postgres.")
    s.clock.advance(300)
    assert s.commits == ["It uses Postgres."] and s.taker.last_segments == 1
