"""How an interview moves along: code-spoken openers and bridges, per-topic question budgets, the
follow-up ladder, time allocation, struggle exits, the end, and which answers get recorded.
A scripted model and a fake clock, no network (v2 design, "Interview structure" and "Turn handling").
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from backend.graph.interview.graph import build_interview_graph
from backend.interview.evaluate import evaluate_interview
from backend.graph.interview.prompt import DIFFERENT_ASPECT
from backend.interview.personas import (BRIDGES, CLOSING, HINT_DECLINED, INTRO_QUESTION, NEUTRAL, OPENING, SKIP_ACK,
                                        THANKS)
from backend.interview.plan import intro_topic, make_topic
from backend.tests.helpers import ScriptedModel

DEEP = make_topic("deep_dive", "beacon", "Beacon", "Beacon's scheduler takes a Postgres advisory lock.",
                  "What does Beacon do?")
TECH = make_topic("technical", "postgres", "PostgreSQL", "Advisory locks are held per session.",
                  "How does a Postgres advisory lock work?", source="gap")
BEHAVIORAL = make_topic("behavioral", "conflict", "a disagreement", "", "Tell me about a disagreement in a team.")
ACHIEVEMENT = make_topic("achievement", "oss", "your open-source PR", "Merged a PR to FastAPI.",
                         "Tell me about your FastAPI pull request.")
PLAN = [intro_topic(), DEEP, TECH, BEHAVIORAL, ACHIEVEMENT]
OPENED = f"{OPENING} {INTRO_QUESTION}"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def reply(decision: str, text: str) -> list[str]:
    return [f"[[decision={decision}]]\n", text]


class PlanFollowingModel:
    """An interviewer model that obeys the decisions it is offered: it takes `prefer` when offered,
    otherwise a follow-up. Lets a whole interview run without scripting every reply."""

    def __init__(self, prefer: str) -> None:
        self.prefer, self.calls = prefer, []

    def __call__(self, prompt, system_instruction):
        self.calls.append({"prompt": prompt})
        offered = re.search(r"Decisions allowed this turn: (.*)\.", prompt).group(1).split(", ")
        choice = self.prefer if self.prefer in offered else "probe"
        pieces = reply(choice, "Thanks." if choice == "next" else "Why?")

        async def gen():
            for piece in pieces:
                yield piece
        return gen()


class Interview:
    """A graph with a model and a fake clock; say() runs one candidate turn."""

    def __init__(self, *replies: list[str], plan=PLAN, model=None, max_seconds: float = 900) -> None:
        self.model, self.clock, self.plan = model or ScriptedModel(*replies), FakeClock(), plan
        self.graph = build_interview_graph(self.model, clock=self.clock, max_seconds=max_seconds)

    def say(self, query: str, **inputs) -> tuple[str, dict]:
        async def run():
            spoken, state = [], {}
            config = {"configurable": {"thread_id": "s1"}}
            stream = self.graph.astream({"query": query, "topics": self.plan, **inputs}, config,
                                        stream_mode=["custom", "values"])
            async for mode, chunk in stream:
                if mode == "custom":
                    spoken.append(chunk["text"])
                elif mode == "values":
                    state = chunk
            return "".join(spoken), state
        return asyncio.run(run())

    def prompt(self, call: int = -1) -> str:
        return self.model.calls[call]["prompt"]


def at_deep_dive(*replies: list[str], **kwargs) -> Interview:
    """An interview past the intro, with Beacon's seed question asked."""
    interview = Interview(*replies, **kwargs)
    interview.say("")
    interview.say("I'm a backend developer.")
    return interview


def run_to_the_end(interview: Interview, seconds_per_answer: float = 0) -> dict:
    _, state = interview.say("")
    while not state.get("finished"):
        interview.clock.now += seconds_per_answer
        _, state = interview.say("A full answer.")
    return state


def questions_per_topic(state: dict) -> Counter:
    return Counter(answer["topic_id"] for answer in state["answers"])


# --- whole interviews: budgets per stage (the phase's "done when") ---------------------------------

def test_a_strong_candidate_gets_every_stages_maximum_and_eight_model_calls():
    interview = Interview(model=PlanFollowingModel(prefer="probe"))
    state = run_to_the_end(interview)
    assert [questions_per_topic(state)[t["topic_id"]] for t in PLAN] == [t["max_q"] for t in PLAN]  # 1, 4, 4, 2, 2
    assert len(interview.model.calls) == 8  # only follow-ups call the model: 13 questions, 5 asked by code


def test_a_candidate_whose_answers_suffice_gets_every_stages_minimum():
    state = run_to_the_end(Interview(model=PlanFollowingModel(prefer="next")))
    assert [questions_per_topic(state)[t["topic_id"]] for t in PLAN] == [t["min_q"] for t in PLAN]  # 1, 2, 2, 1, 2


def test_time_allocation_keeps_every_later_stage_at_its_minimum():
    # 75 s per answer in 15 minutes: a strong candidate cannot reach every maximum, so early stages stop early
    state = run_to_the_end(Interview(model=PlanFollowingModel(prefer="probe")), seconds_per_answer=75)
    asked = questions_per_topic(state)
    assert all(t["min_q"] <= asked[t["topic_id"]] <= t["max_q"] for t in PLAN), asked
    assert sum(asked.values()) < sum(t["max_q"] for t in PLAN)


# --- code speaks the first question of every topic ----------------------------------------------

def test_the_opening_and_the_intro_question_are_spoken_by_code():
    interview = Interview()
    spoken, state = interview.say("")
    assert spoken == OPENED and state["last_question"] == INTRO_QUESTION
    assert interview.model.calls == []


def test_after_the_intro_answer_code_bridges_to_the_next_stage_without_the_model():
    interview = Interview()
    interview.say("")
    spoken, state = interview.say("I'm a backend developer.")
    assert spoken == f"{THANKS} {BRIDGES['deep_dive']} {DEEP['seed_question']}"
    assert interview.model.calls == []
    assert state["last_question"] == DEEP["seed_question"]  # "repeat" replays the question, not the bridge
    assert state["answers"] == [{"topic_id": "intro:background", "question": INTRO_QUESTION,
                                 "text": "I'm a backend developer."}]


def test_when_the_model_chooses_next_it_acknowledges_and_code_asks_the_next_seed():
    interview = at_deep_dive(reply("probe", "Why a lock?"), reply("next", "Got it."))
    interview.say("It schedules checks.")
    spoken, state = interview.say("So two workers never run the same check.")
    assert spoken == f"Got it. {BRIDGES['technical']} {TECH['seed_question']}"
    assert (state["topic_index"], state["followups_used"], state["level"]) == (2, 0, 1)


def test_a_reconnect_replays_the_last_question_without_the_model():
    interview = at_deep_dive()
    spoken, _ = interview.say("")  # the page reconnected and pressed Start again
    assert spoken == DEEP["seed_question"] and interview.model.calls == []


# --- budgets and the ladder inside a topic ------------------------------------------------------

def test_below_the_minimum_next_is_not_offered_and_the_model_asks_another_aspect():
    interview = at_deep_dive(reply("probe", "Why a lock?"))
    _, state = interview.say("It schedules checks.")
    assert "Decisions allowed this turn: probe, example, clarify_back, hint_request." in interview.prompt()
    assert DIFFERENT_ASPECT in interview.prompt()
    assert (state["topic_index"], state["followups_used"], state["level"]) == (1, 1, 2)


def test_a_follow_up_climbs_the_ladder_and_records_the_answer():
    interview = at_deep_dive(reply("probe", "Why a lock?"), reply("probe", "What breaks?"))
    interview.say("It schedules checks.")
    _, state = interview.say("To stop double runs.")
    assert state["level"] == 3 and "Follow-up level 2: ask about their method" in interview.prompt()
    assert state["answers"][-1] == {"topic_id": "deep_dive:beacon", "question": "Why a lock?",
                                    "text": "To stop double runs."}


def test_the_ladder_stops_at_the_topics_max_level():
    interview = Interview(reply("probe", "What was your part?"), plan=[ACHIEVEMENT])
    interview.say("")
    _, state = interview.say("I fixed a bug.")
    assert state["level"] == ACHIEVEMENT["max_level"] == 2
    _, state = interview.say("A race in the router.")  # 2 questions is the achievement maximum: code moves on
    assert state["finished"] and len(interview.model.calls) == 1


def test_a_reply_without_a_valid_next_is_judged_by_whether_it_asks_a_question():
    interview = at_deep_dive(["What made you pick Postgres?"], ["Thanks for that."])  # no control tags
    _, state = interview.say("It schedules checks.")
    assert (state["topic_index"], state["followups_used"]) == (1, 1)  # it asked: a follow-up
    _, state = interview.say("It was there already.")
    assert (state["topic_index"], state["last_question"]) == (2, TECH["seed_question"])  # it did not: move on


def test_a_challenge_is_offered_only_from_the_personas_level():
    neutral = at_deep_dive(reply("probe", "Why?"))
    neutral.say("It schedules checks.")
    strict = Interview(reply("challenge", "Why not Redis?"))
    strict.say("", persona="strict")
    strict.say("I'm a backend developer.")
    strict.say("It schedules checks.")
    assert "challenge" not in neutral.prompt() and "challenge" in strict.prompt()


# --- struggle ends a topic early -----------------------------------------------------------------

def test_i_dont_know_moves_to_the_next_stage_and_records_nothing():
    interview = at_deep_dive()
    spoken, state = interview.say("I don't know.")
    assert spoken == f"{SKIP_ACK} {BRIDGES['technical']} {TECH['seed_question']}"
    assert interview.model.calls == [] and "deep_dive:beacon" not in questions_per_topic(state)


def test_a_strict_interviewer_declines_a_hint_and_moves_on():
    interview = Interview()
    interview.say("", persona="strict")
    interview.say("I'm a backend developer.")
    spoken, state = interview.say("Can I get a hint?")
    assert spoken == f"{HINT_DECLINED} {BRIDGES['technical']} {TECH['seed_question']}"
    assert state["last_question"] == TECH["seed_question"] and interview.model.calls == []


def test_a_neutral_hint_or_rephrase_stays_on_the_topic_and_counts_nothing():
    interview = at_deep_dive(reply("probe", "Think about locks. What does it do?"), reply("clarify_back", "What is it for?"))
    interview.say("Can I get a hint?")
    _, state = interview.say("What do you mean?")
    assert (state["topic_index"], state["followups_used"], state["level"]) == (1, 0, 1)
    assert "deep_dive:beacon" not in questions_per_topic(state)


def test_skip_on_the_last_topic_closes_without_the_model():
    interview = Interview(plan=[DEEP])
    interview.say("")
    spoken, state = interview.say("skip")
    assert spoken == f"{SKIP_ACK} {CLOSING}" and state["finished"] and interview.model.calls == []


# --- the end and the time cap ---------------------------------------------------------------------

def test_ending_the_interview_closes_and_every_later_turn_gets_the_closing_line():
    interview = at_deep_dive()
    spoken, state = interview.say("Let's end the interview.")
    assert spoken == CLOSING and state["finished"]
    spoken, state = interview.say("Wait, one more thing.")
    assert spoken == CLOSING and len(state["answers"]) == 1 and interview.model.calls == []  # only the intro


def test_an_answer_after_the_time_cap_is_recorded_and_closes_the_interview():
    interview = at_deep_dive()
    interview.clock.now += 900
    spoken, state = interview.say("It uses Postgres.")
    assert spoken == CLOSING and state["finished"] and interview.model.calls == []
    assert state["answers"][-1]["text"] == "It uses Postgres."


def test_a_request_after_the_time_cap_is_still_answered():
    interview = at_deep_dive(reply("clarify_back", "What is it for?"))
    interview.clock.now += 901
    _, state = interview.say("What do you mean?")  # the cap waits for the candidate's next answer
    assert state.get("finished") is not True and len(interview.model.calls) == 1


def test_a_session_without_topics_closes_instead_of_asking():
    spoken, state = Interview(plan=[]).say("")
    assert spoken == CLOSING and state["finished"]


# --- a cut-off turn ---------------------------------------------------------------------------------

def test_an_answer_whose_turn_was_cut_off_is_not_recorded():
    stall = asyncio.Event()
    model = ScriptedModel()
    graph = build_interview_graph(lambda p, s: hang(stall) if not model.calls else model(p, s))

    async def run():
        config = {"configurable": {"thread_id": "s1"}}
        await drain(graph.astream({"query": "", "topics": [DEEP]}, config, stream_mode="values"))
        cut = asyncio.create_task(drain(graph.astream({"query": "first try"}, config, stream_mode="values")))
        await asyncio.sleep(0.1)
        cut.cancel()  # a barge-in cancels the turn while the model is answering
        await asyncio.gather(cut, return_exceptions=True)
        model.calls.append("the stalled call")
        model.script.append(reply("probe", "Why?"))
        return await drain(graph.astream({"query": "first try, and more"}, config, stream_mode="values"))

    async def hang(event):
        await event.wait()
        yield ""

    async def drain(stream):
        state = {}
        async for chunk in stream:
            state = chunk
        return state

    state = asyncio.run(run())
    assert [a["text"] for a in state["answers"]] == ["first try, and more"]


# --- nudges ---------------------------------------------------------------------------------------

def test_a_nudge_says_the_personas_line_without_the_model_and_keeps_the_question():
    interview = at_deep_dive()
    spoken, state = interview.say("", nudge=0)
    assert spoken == NEUTRAL.nudges[0] and interview.model.calls == []
    assert state["last_question"] == DEEP["seed_question"] and state["messages"][-1].content == NEUTRAL.nudges[0]
    spoken, _ = interview.say("Can you repeat that?")
    assert spoken == DEEP["seed_question"]  # repeat replays the question, not the nudge


def test_the_turn_after_a_nudge_is_an_ordinary_turn():
    interview = at_deep_dive(reply("probe", "Why a lock?"))
    interview.say("", nudge=1)
    spoken, state = interview.say("It schedules checks.")
    assert (spoken, state["intent"], state["nudge_index"]) == ("Why a lock?", "answer", None)


def test_no_nudge_for_a_strict_persona_or_after_the_end():
    strict = Interview()
    strict.say("", persona="strict")
    assert strict.say("", nudge=0)[0] == ""
    ended = at_deep_dive()
    ended.say("Let's end the interview.")
    assert ended.say("", nudge=0)[0] == ""


# --- a hint request the phrase rules miss: the model labels it, code decides ---------------

REWORDED_HINT = "I want you to give some level of hint now"  # live test 1.8: no fixed phrase matches it
LEAKED_HINT = "Think about the advisory lock."  # what a model might write after the label anyway


def test_a_reworded_hint_request_to_the_strict_interviewer_is_declined_by_code_not_the_model():
    leak_in_the_tag_piece = [f"[[decision=hint_request]]\n{LEAKED_HINT}"]  # the label and a hint in one streamed piece
    interview = Interview(leak_in_the_tag_piece)
    interview.say("", persona="strict")
    interview.say("I'm a backend developer.")
    spoken, state = interview.say(REWORDED_HINT)
    assert spoken == f"{HINT_DECLINED} {BRIDGES['technical']} {TECH['seed_question']}"  # the leak is never spoken
    assert state["intent"] == "hint" and "deep_dive:beacon" not in questions_per_topic(state)


def test_a_reworded_hint_request_to_the_neutral_interviewer_gets_a_hint_on_the_same_topic():
    interview = at_deep_dive(reply("hint_request", LEAKED_HINT), reply("probe", "Think about locks. What does Beacon do?"))
    spoken, state = interview.say(REWORDED_HINT)
    assert spoken == "Think about locks. What does Beacon do?" and "asked for a hint" in interview.prompt()
    assert (state["topic_index"], state["followups_used"]) == (1, 0)
    assert "deep_dive:beacon" not in questions_per_topic(state)


def test_in_hint_mode_the_label_is_ignored_so_the_turn_cannot_loop():
    interview = at_deep_dive(reply("hint_request", "Think about locks. What does Beacon do?"))
    spoken, _ = interview.say("Can I get a hint?")
    assert spoken == "Think about locks. What does Beacon do?" and len(interview.model.calls) == 1


# --- mis-heard terms ------------------------------------------------------------------------------

def test_a_mis_heard_term_is_corrected_before_the_model_and_kept_with_the_answer():
    interview = Interview(reply("probe", "Why a lock?"))
    interview.say("", glossary=["PostgreSQL"])
    interview.say("I'm a backend developer.")
    _, state = interview.say("It takes a lock in post gress.")
    assert "Candidate's latest message: It takes a lock in PostgreSQL." in interview.prompt()
    assert state["answers"][-1]["text"] == "It takes a lock in PostgreSQL."
    assert state["answers"][-1]["corrections"] == {"post gress": "PostgreSQL"}


# --- the report (phase 4's "done when") ----------------------------------------------------------

def test_the_report_reviews_every_graded_answer_and_never_a_hint_repeat_or_skip():
    interview = at_deep_dive(reply("probe", "Think about locks. What does Beacon do?"), reply("probe", "Why a lock?"))
    interview.say("Can I get a hint?")
    interview.say("Can you repeat that?")
    interview.say("It schedules checks.")
    interview.say("skip")
    _, state = interview.say("Let's end the interview.")
    evaluator = ScriptedModel(['{"answers": [{"index": 1, "band": "ok", "improvement": "Say why."}]}'])
    report = asyncio.run(evaluate_interview(state["answers"], PLAN, evaluator))
    assert [r.answer for r in report.reviews] == ["It schedules checks."]  # not the intro, hint, repeat, skip or end
    assert "Can I get a hint?" not in evaluator.calls[0]["prompt"]
