"""How an interview moves along (B7): follow-up caps, the difficulty ladder, topic moves, skip, end,
the time cap, and which answers get recorded. Scripted model, fake clock, no network.

Plan scenarios: T21 (follow-ups never exceed the cap; the interview ends at plan end or time cap).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.graph.interview.flow import choose_route, create_advance_node
from backend.graph.interview.graph import build_interview_graph
from backend.graph.interview.prompt import CAP_REACHED
from backend.interview.personas import CLOSING, HINT_DECLINED
from backend.interview.plan import Topic
from backend.tests.helpers import ScriptedModel

TOPICS = [
    Topic(topic_id="beacon", title="Beacon", text="Beacon's scheduler takes a Postgres advisory lock."),
    Topic(topic_id="fitai", title="FitAI", text="FitAI plans workouts with an LLM."),
]
OPENING = "What does Beacon do?"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def reply(decision: str, text: str) -> list[str]:
    return [f"[[decision={decision}]]\n", text]


class Interview:
    """A graph with a scripted model and a fake clock; say() runs one candidate turn."""

    def __init__(self, *replies: list[str], max_seconds: float = 600) -> None:
        self.model, self.clock = ScriptedModel(*replies), FakeClock()
        self.graph = build_interview_graph(self.model, TOPICS, clock=self.clock, max_seconds=max_seconds)

    def say(self, query: str, **inputs) -> tuple[str, dict]:
        async def run():
            spoken, state = [], {}
            config = {"configurable": {"thread_id": "s1"}}
            async for mode, chunk in self.graph.astream({"query": query, **inputs}, config, stream_mode=["custom", "values"]):
                if mode == "custom":
                    spoken.append(chunk["text"])
                elif mode == "values":
                    state = chunk
            return "".join(spoken), state
        return asyncio.run(run())

    def prompt(self, call: int = -1) -> str:
        return self.model.calls[call]["prompt"]


def opened(*replies: list[str], **kwargs) -> Interview:
    """An interview whose opening question has been asked."""
    interview = Interview(reply("next", OPENING), *replies, **kwargs)
    interview.say("")
    return interview


# --- follow-ups and the ladder ------------------------------------------------------------

def test_a_follow_up_counts_climbs_the_ladder_and_records_the_answer():
    interview = opened(reply("probe", "Why a lock?"))
    _, state = interview.say("It schedules checks.")
    assert (state["topic_index"], state["followups_used"], state["level"]) == (0, 1, 2)
    assert state["answers"] == [{"topic_id": "beacon", "question": OPENING, "text": "It schedules checks."}]
    assert state["last_question"] == "Why a lock?"


def test_two_follow_ups_reach_level_three_and_the_next_question_says_so():
    interview = opened(reply("probe", "Why?"), reply("probe", "And then?"), reply("next", "Thanks. What does FitAI do?"))
    interview.say("a")
    _, state = interview.say("b")
    assert state["level"] == 3
    interview.say("c")
    assert "Difficulty: level 3, stress" in interview.prompt()


def test_the_ladder_stops_at_level_three():
    advance = create_advance_node(["beacon", "fitai"])
    state = {"mode": "answer", "decision": "probe", "level": 3, "followups_used": 0, "topic_index": 0}
    assert asyncio.run(advance(state))["level"] == 3


def test_after_the_cap_only_next_is_offered_and_the_topic_moves():  # T21
    interview = opened(reply("probe", "Why?"), reply("example", "Example?"), reply("next", "Thanks. What does FitAI do?"))
    interview.say("a")
    interview.say("b")  # neutral allows two follow-ups
    _, state = interview.say("c")
    prompt = interview.prompt()
    assert "Decisions allowed this turn: next." in prompt and CAP_REACHED in prompt
    assert "ask them to explain what FitAI does" in prompt
    assert (state["topic_index"], state["followups_used"], state["level"]) == (1, 0, 1)
    assert [a["topic_id"] for a in state["answers"]] == ["beacon", "beacon", "beacon"]


def test_a_follow_up_the_model_was_not_offered_counts_as_next():  # T21: the cap can never be passed
    interview = opened(reply("challenge", "Why not Redis?"))  # neutral may not challenge at level 1
    _, state = interview.say("It uses Postgres.")
    assert (state["topic_index"], state["followups_used"]) == (1, 0)


def test_the_strict_persona_may_challenge_at_level_one():
    interview = Interview(reply("next", OPENING), reply("challenge", "Why not Redis?"))
    interview.say("", persona="strict")
    _, state = interview.say("It uses Postgres.")
    assert (state["topic_index"], state["followups_used"]) == (0, 1)


def test_a_missing_tag_moves_on_instead_of_counting_a_follow_up():
    interview = opened(["Thanks. What does FitAI do?"])
    _, state = interview.say("It uses Postgres.")
    assert (state["topic_index"], state["tag_ok"]) == (1, False)


# --- the end of the plan ---------------------------------------------------------------------

def test_next_on_the_last_topic_thanks_then_closes():  # T21
    interview = opened(reply("next", "Thanks. What does FitAI do?"), reply("next", "Thanks for walking me through it."))
    interview.say("Postgres.")
    assert "ask them to explain what FitAI does" in interview.prompt()
    spoken, state = interview.say("It plans workouts.")
    assert "the interview ends after this" in interview.prompt()
    assert spoken == f"Thanks for walking me through it.{CLOSING}"
    assert state["finished"] is True and state["final_text"] == f"Thanks for walking me through it. {CLOSING}"
    assert len(state["answers"]) == 2


def test_every_turn_after_the_end_gets_the_closing_line_without_the_model():
    interview = opened(reply("next", "Next. What does FitAI do?"), reply("next", "Thanks."))
    interview.say("a")
    interview.say("b")
    calls = len(interview.model.calls)
    spoken, state = interview.say("Wait, one more thing.")
    assert spoken == CLOSING and len(interview.model.calls) == calls
    assert len(state["answers"]) == 2  # nothing is graded after the end


# --- skip, end and hints ------------------------------------------------------------------------

def test_skip_moves_to_the_next_topic_and_records_nothing():
    interview = opened(reply("next", "That's fine. What does FitAI do?"))
    _, state = interview.say("Can we skip this one?")
    prompt = interview.prompt()
    assert "FitAI plans workouts" in prompt and "chose to skip" in prompt and "Beacon's scheduler" not in prompt
    assert (state["topic_index"], state["followups_used"], state["level"]) == (1, 0, 1)
    assert state.get("answers", []) == []


def test_skip_on_the_last_topic_closes_without_the_model():
    interview = opened(reply("next", "Fine. What does FitAI do?"))
    interview.say("skip")
    calls = len(interview.model.calls)
    spoken, state = interview.say("I don't know.")
    assert spoken == CLOSING and state["finished"] and len(interview.model.calls) == calls


def test_ending_the_interview_closes_without_the_model():
    interview = opened()
    spoken, state = interview.say("Let's end the interview.")
    assert spoken == CLOSING and state["finished"] and len(interview.model.calls) == 1


def test_a_strict_interviewer_declines_a_hint_and_moves_on():
    interview = Interview(reply("next", OPENING), reply("next", "What does FitAI do?"))
    interview.say("", persona="strict")
    spoken, state = interview.say("Can I get a hint?")
    assert spoken == f"{HINT_DECLINED} What does FitAI do?"
    assert "Move to a new topic" in interview.prompt() and state["topic_index"] == 1
    assert state["final_text"] == f"{HINT_DECLINED} What does FitAI do?"
    assert state["last_question"] == "What does FitAI do?"  # "repeat" replays the question, not the refusal


def test_a_neutral_hint_or_rephrase_stays_on_the_topic_and_counts_nothing():
    interview = opened(reply("probe", "Think about locks. What does it do?"), reply("clarify_back", "What is it for?"))
    interview.say("Can I get a hint?")
    _, state = interview.say("What do you mean?")
    assert (state["topic_index"], state["followups_used"], state["level"]) == (0, 0, 1)
    assert state.get("answers", []) == []


# --- time cap -------------------------------------------------------------------------------------

def test_an_answer_after_the_time_cap_is_recorded_and_closes_the_interview():  # T21
    interview = opened(max_seconds=600)
    interview.clock.now += 600
    spoken, state = interview.say("It uses Postgres.")
    assert spoken == CLOSING and state["finished"] and len(interview.model.calls) == 1
    assert state["answers"] == [{"topic_id": "beacon", "question": OPENING, "text": "It uses Postgres."}]


def test_a_request_after_the_time_cap_is_still_answered():
    interview = opened(reply("clarify_back", "What is it for?"), max_seconds=600)
    interview.clock.now += 601
    _, state = interview.say("What do you mean?")  # the cap waits for the candidate's next answer
    assert state.get("finished") is not True and len(interview.model.calls) == 2


# --- a cut-off turn ---------------------------------------------------------------------------------

def test_an_answer_whose_turn_was_cut_off_is_not_recorded():
    stall = asyncio.Event()
    model = ScriptedModel(reply("next", OPENING))
    graph = build_interview_graph(lambda p, s: hang(stall) if model.calls else model(p, s), TOPICS)

    async def run():
        config = {"configurable": {"thread_id": "s1"}}
        async for _ in graph.astream({"query": ""}, config, stream_mode="values"):
            pass
        cut = asyncio.create_task(drain(graph.astream({"query": "first try"}, config, stream_mode="values")))
        await asyncio.sleep(0.1)
        cut.cancel()  # a barge-in cancels the turn while the model is answering
        await asyncio.gather(cut, return_exceptions=True)
        stall.set()
        model.script.append(reply("probe", "Why?"))
        return await drain(graph.astream({"query": "first try, and more"}, config, stream_mode="values"))

    async def hang(event):
        await event.wait()
        for piece in model.script.pop(0) if model.script else reply("probe", "Why?"):
            yield piece

    async def drain(stream):
        state = {}
        async for chunk in stream:
            state = chunk
        return state

    state = asyncio.run(run())
    assert [a["text"] for a in state["answers"]] == ["first try, and more"]


# --- choose_route, directly ---------------------------------------------------------------------------

@pytest.mark.parametrize("state, route, mode", [
    ({"intent": "repeat"}, "interviewer", "answer"),  # nothing asked yet: the model handles it
    ({"intent": "repeat", "last_question": "Q?"}, "repeat", None),
    ({"intent": "start"}, "interviewer", "start"),
    ({"intent": "rephrase", "last_question": "Q?"}, "interviewer", "rephrase"),
    ({"intent": "answer", "finished": True}, "close", None),
])
def test_choose_route(state, route, mode):
    update = choose_route({"query": "x", **state}, ["beacon", "fitai"], elapsed_s=0, max_seconds=600)
    assert update["route"] == route and update.get("mode") == mode


def test_an_answer_with_no_question_asked_yet_is_not_recorded():
    update = choose_route({"intent": "answer", "query": "hi"}, ["beacon"], elapsed_s=0, max_seconds=600)
    assert update["pending_answer"] is None
