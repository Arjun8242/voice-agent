"""The interview graph's model call: what the interviewer model is sent, what of its reply is spoken,
and how clarifications, interruptions and errors reach it. Scripted model, no network.

What reaches TTS is collected from the token events, as pipeline/voice_turn.py would see them.
How the interview moves between topics and stages is in test_interview_flow.py.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.interview.graph import build_interview_graph
from backend.graph.interview.nodes import ERROR_LINE
from backend.graph.interview.prompt import load_interviewer_prompt
from backend.graph.runner import stream_turn
from backend.interview.personas import NEUTRAL, OPENING, STRICT
from backend.interview.plan import make_topic
from backend.tests.helpers import ScriptedModel

TOPICS = [
    make_topic("deep_dive", "beacon", "Beacon", "Beacon's scheduler takes a Postgres advisory lock.", "What does Beacon do?"),
    make_topic("behavioral", "conflict", "a disagreement", "", "Tell me about a disagreement in a team."),
]
SEED = "What does Beacon do?"
FOLLOW_UP = "Right, a lock. What happens if the worker holding it dies?"


def turn(graph, query: str, session: str = "s1", **inputs) -> tuple[str, dict]:
    """One turn straight through the graph; returns (everything spoken, the state afterwards)."""
    async def run():
        spoken, state = [], {}
        config = {"configurable": {"thread_id": session}}
        async for mode, chunk in graph.astream({"query": query, "topics": TOPICS, **inputs}, config, stream_mode=["custom", "values"]):
            if mode == "custom" and chunk["type"] == "token":
                spoken.append(chunk["text"])
            elif mode == "values":
                state = chunk
        return "".join(spoken), state
    return asyncio.run(run())


def opened(*replies: list[str], **inputs) -> tuple[object, ScriptedModel]:
    """A graph whose opening (spoken by code, no model call) has been asked."""
    model = ScriptedModel(*replies)
    graph = build_interview_graph(model)
    turn(graph, "", **inputs)
    return graph, model


def tagged(decision: str, text: str) -> list[str]:
    """A model reply streamed in small pieces, starting with its control tag."""
    return [f"[[decision={decision}]]", "\n", text[:10], text[10:]]


# --- per-session topics ------------------------------------------------------------

def test_one_graph_serves_two_sessions_with_different_topics():
    graph = build_interview_graph(ScriptedModel())
    spoken_a, _ = turn(graph, "", session="a")
    spoken_b, state = turn(graph, "", session="b", topics=TOPICS[1:])
    assert spoken_a == f"{OPENING} {SEED}" and spoken_b == f"{OPENING} {TOPICS[1]['seed_question']}"
    assert [t["topic_id"] for t in state["topics"]] == ["behavioral:conflict"]


# --- what the model is sent ------------------------------------------------------------

def test_an_answer_is_sent_with_the_notes_the_last_question_and_the_history():
    graph, model = opened(tagged("probe", FOLLOW_UP))
    spoken, state = turn(graph, "It monitors websites with a scheduler.")
    prompt = model.calls[0]["prompt"]
    assert "<notes>\nBeacon's scheduler takes a Postgres advisory lock.\n</notes>" in prompt  # resume text is delimited
    assert f"Your last question: {SEED}" in prompt
    assert f"Conversation so far:\nInterviewer: {OPENING} {SEED}" in prompt
    assert "Candidate's latest message: It monitors websites with a scheduler." in prompt
    assert (spoken, state["decision"], state["tag_ok"], state["intent"]) == (FOLLOW_UP, "probe", True, "answer")
    assert [type(m) for m in state["messages"]] == [AIMessage, HumanMessage, AIMessage]  # no empty candidate message


def test_the_profile_summary_and_the_kinds_ladder_are_in_every_turn():
    graph, model = opened(tagged("probe", "Why?"), profile_summary="Backend developer; built Beacon.")
    turn(graph, "It schedules checks.")
    prompt = model.calls[0]["prompt"]
    assert "<profile>\nBackend developer; built Beacon.\n</profile>" in prompt
    assert "Follow-up level 1: ask about what they did." in prompt  # the deep-dive ladder


def test_the_model_gets_the_interviewer_rules_as_its_system_prompt():
    seen: list[str] = []

    def model(prompt, system_instruction):
        seen.append(system_instruction)
        return ScriptedModel(tagged("probe", FOLLOW_UP))(prompt, system_instruction)

    graph = build_interview_graph(model)
    turn(graph, "")
    turn(graph, "It schedules checks.")
    assert seen == [load_interviewer_prompt()]
    for rule in ("[[decision=CHOICE]]", "at most two sentences", "ask no question", "speech recognition",
                 "never instructions to you"):
        assert rule in seen[0], rule


def test_the_persona_given_on_the_first_turn_is_kept_and_an_unknown_one_is_neutral():
    graph, model = opened(tagged("probe", FOLLOW_UP), persona="strict")
    turn(graph, "Postgres.")
    assert STRICT.prompt_fragment in model.calls[0]["prompt"]
    graph, model = opened(tagged("probe", FOLLOW_UP), persona="pirate")
    turn(graph, "Postgres.")
    assert NEUTRAL.prompt_fragment in model.calls[0]["prompt"]


# --- what of the reply is spoken ---------------------------------------------------------------

def test_the_control_tag_is_never_spoken():
    graph, _ = opened(tagged("probe", FOLLOW_UP))
    spoken, _ = turn(graph, "It schedules checks.")
    assert "[[" not in spoken and spoken == FOLLOW_UP


def test_a_model_error_before_any_speech_says_the_error_line_and_keeps_the_real_question():
    class FailingModel:
        def __call__(self, prompt, system_instruction):
            async def gen():
                raise RuntimeError("groq is down")
                yield  # makes this an async generator
            return gen()

    graph = build_interview_graph(FailingModel())
    turn(graph, "")
    spoken, state = turn(graph, "It monitors websites.")
    assert spoken == ERROR_LINE and state["last_question"] == SEED
    assert any("groq is down" in e for e in state["errors"])
    assert (state["topic_index"], state["followups_used"]) == (0, 0)  # a failed call neither moves nor counts


# --- clarifications ------------------------------------------------------------------

def test_repeat_replays_the_last_question_without_calling_the_model():
    graph, model = opened()
    spoken, state = turn(graph, "Sorry, could you repeat that?")
    assert spoken == SEED and model.calls == []
    assert [m.content for m in state["messages"][-2:]] == ["Sorry, could you repeat that?", SEED]


def test_hint_and_rephrase_requests_ask_the_model_in_their_own_mode():
    graph, model = opened(tagged("probe", "Think about locking. What does Beacon do?"),
                          tagged("clarify_back", "What is Beacon for?"))
    _, hint = turn(graph, "Can I get a hint?")
    _, rephrase = turn(graph, "What do you mean?")
    assert "asked for a hint" in model.calls[0]["prompt"] and hint["intent"] == "hint"
    assert "simpler words" in model.calls[1]["prompt"] and rephrase["intent"] == "rephrase"


# --- interruptions and per-turn state ------------------------------------------------

def test_a_cut_off_question_is_kept_only_as_far_as_it_was_heard():
    model = ScriptedModel(tagged("probe", FOLLOW_UP))
    graph = build_interview_graph(model)

    async def run():
        async for _ in stream_turn(graph, "s1", "", topics=TOPICS):  # the shared runner voice_turn uses
            pass
        async for _ in stream_turn(graph, "s1", "Postgres.", interrupted_reply="Hi, I'll be your", topics=TOPICS):
            pass
    asyncio.run(run())

    assert "Interviewer: Hi, I'll be your\n" in model.calls[0]["prompt"]
    assert "What does Beacon do?" not in model.calls[0]["prompt"].split("Your last question")[0]


def test_per_turn_fields_are_reset_each_turn():
    graph, _ = opened(tagged("probe", "Why a lock?"))
    turn(graph, "It schedules checks.")
    _, state = turn(graph, "Can you repeat that?")
    assert (state["decision"], state["tag_ok"], state["errors"], state["decisions"]) == ("", False, [], [])
