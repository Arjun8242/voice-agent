"""S12: the helpers that work out what the visitor heard of a cut-off answer, and the graph input that
puts it into the history. No server, no model."""

import asyncio

from backend.graph.graph import build_graph
from backend.graph.runner import stream_turn
from backend.server.session import (
    CUT_OFF_NOTE,
    cut_off,
    heard_reply,
    new_conversation,
    record_report,
    take_heard,
)
from backend.tests.test_tool_graph import ScriptedModel, no_retrieval

SENTENCES = [(4, "First."), (5, "Second."), (6, "Third.")]


def queued(*sentences):
    c = new_conversation()
    c.sentences = list(sentences)
    return c


# --- heard_reply ------------------------------------------------------------

def test_heard_reply_keeps_sentences_up_to_and_including_the_playing_one():
    assert heard_reply(SENTENCES, 5) == f"First. Second. {CUT_OFF_NOTE}"
    assert heard_reply(SENTENCES, 4) == f"First. {CUT_OFF_NOTE}"


def test_heard_reply_is_empty_when_nothing_started_playing():
    assert heard_reply(SENTENCES, None) == ""
    assert heard_reply(SENTENCES, 3) == ""  # an id before this turn's first sentence
    assert heard_reply(SENTENCES, "5") == ""  # not an int: ignore
    assert heard_reply([], 5) == ""


# --- cut_off / record_report / take_heard -----------------------------------

def test_report_for_the_cut_off_turn_is_taken_once():
    c = queued(*SENTENCES)
    cut_off(c, turn_id=3)
    record_report(c, 3, 4)
    assert asyncio.run(take_heard(c)) == f"First. {CUT_OFF_NOTE}"
    assert asyncio.run(take_heard(c)) == ""  # one-shot


def test_report_for_another_turn_is_ignored():
    c = queued(*SENTENCES)
    cut_off(c, turn_id=3)
    record_report(c, 2, 6)
    assert c.waiting_for_report == 3 and c.heard == ""


def test_nothing_queued_means_nothing_to_wait_for():
    c = queued()
    cut_off(c, turn_id=1)
    assert c.waiting_for_report is None
    assert asyncio.run(take_heard(c, timeout=5)) == ""  # returns at once, no 5 s wait


def test_late_report_is_ignored_after_the_wait_runs_out():
    c = queued(*SENTENCES)
    cut_off(c, turn_id=1)
    assert asyncio.run(take_heard(c, timeout=0.05)) == ""
    record_report(c, 1, 5)  # arrives too late
    assert asyncio.run(take_heard(c, timeout=0.05)) == ""


def test_a_second_cut_off_forgets_the_first():
    c = queued(*SENTENCES)
    cut_off(c, turn_id=1)
    record_report(c, 1, 4)
    c.sentences = [(7, "Other.")]  # next turn, interrupted before the first one was taken
    cut_off(c, turn_id=2)
    assert c.heard == "" and c.cut_off_sentences == [(7, "Other.")]


# --- the graph input --------------------------------------------------------

def test_interrupted_reply_replaces_the_saved_full_answer_once():
    model = ScriptedModel(["One."], ["Two."], ["Three."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=None)
    config = {"configurable": {"thread_id": "s"}}

    async def turn(text, heard=""):
        async for _ in stream_turn(graph, "s", text, heard):
            pass
        return [(m.type, m.content) for m in (await graph.aget_state(config)).values["messages"]]

    async def go():
        await turn("q1")
        second = await turn("q2", f"Half. {CUT_OFF_NOTE}")
        third = await turn("q3")  # no interrupted_reply this time
        return second, third

    second, third = asyncio.run(go())
    # q1's full answer "One." was saved, but the visitor heard only half of it: the heard text replaces it
    assert second == [("human", "q1"), ("ai", f"Half. {CUT_OFF_NOTE}"), ("human", "q2"), ("ai", "Two.")]
    assert sum(1 for _, text in third if text.startswith("Half.")) == 1  # not added again
