"""heard_history: after a barge-in, the history keeps only what the visitor heard of the cut-off answer.

The voice timelines in test_voice_conversation.py cover this through the whole connection; these
check the function the recruiter and interview graphs share.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from backend.graph.nodes.ingest import heard_history


def test_nothing_cut_off_changes_nothing():
    history = [HumanMessage("q1", id="h1"), AIMessage("Full answer.", id="a1")]
    assert heard_history(history, "") == []
    assert heard_history(history, "   ") == []


def test_a_saved_full_answer_is_replaced_by_the_heard_part():
    history = [HumanMessage("q1", id="h1"), AIMessage("First. Second.", id="a1")]
    removed, heard = heard_history(history, "First. (the visitor interrupted here)")
    assert isinstance(removed, RemoveMessage) and removed.id == "a1"
    assert isinstance(heard, AIMessage) and heard.content == "First. (the visitor interrupted here)"


def test_an_answer_cut_before_it_was_saved_is_only_added():
    history = [HumanMessage("q1", id="h1")]  # the turn was cancelled before the response node ran
    (heard,) = heard_history(history, "First. (the visitor interrupted here)")
    assert isinstance(heard, AIMessage)


def test_a_first_turn_with_no_history_is_only_added():
    (heard,) = heard_history([], " First. ")
    assert heard.content == "First."
