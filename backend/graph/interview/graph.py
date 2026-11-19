"""graph.py: wire the interview graph (docs/interviewer-mode-plan.md §6.3).

    START -> ingest -> steer --> interviewer -> advance --> response -> END
                          |---> move --------------------'          (code asks the next seed question; no LLM)
                          |---> repeat ------------------'          (replay the last question; no LLM)
                          |---> nudge -------------------'          (the candidate stayed silent; no LLM)
                          '---> close -------------------'          (end, time cap, past the last topic; no LLM)

    interviewer -> steer: the model labelled an answer hint_request; steer then handles it as a hint.

Separate from the recruiter graph (graph/graph.py): no retrieval, no tools, no booking. It shares only
the event contract (token events) and the input keys of graph/runner.py, so voice_turn runs either one.

One compiled graph serves every session: the topics are per-session state (state.py), not a graph argument.

Dependencies are passed in, so the graph can be tested with a scripted model and a fake clock:
    generate_fn(prompt, system_instruction) -> async iterator of text pieces
    clock: seconds, for the time cap
"""

from __future__ import annotations

import time
from collections.abc import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.config import INTERVIEW_MAX_SECONDS
from backend.graph.interview.flow import create_advance_node, create_close_node, create_move_node, create_steer_node
from backend.graph.interview.nodes import create_interviewer_node, ingest_node, nudge_node, repeat_node, response_node
from backend.graph.interview.state import InterviewState


def build_interview_graph(generate_fn: Callable, checkpointer=None,
                          clock: Callable[[], float] = time.time, max_seconds: float = INTERVIEW_MAX_SECONDS):
    graph = StateGraph(InterviewState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("steer", create_steer_node(clock, max_seconds))
    graph.add_node("move", create_move_node())
    graph.add_node("repeat", repeat_node)
    graph.add_node("nudge", nudge_node)
    graph.add_node("interviewer", create_interviewer_node(generate_fn))
    graph.add_node("advance", create_advance_node())
    graph.add_node("close", create_close_node())
    graph.add_node("response", response_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "steer")
    graph.add_conditional_edges("steer", lambda state: state["route"], ["interviewer", "move", "repeat", "close", "nudge"])
    graph.add_conditional_edges("interviewer", lambda state: "steer" if state.get("route") == "steer" else "advance",
                                ["steer", "advance"])
    graph.add_edge("advance", "response")
    graph.add_edge("move", "response")
    graph.add_edge("repeat", "response")
    graph.add_edge("nudge", "response")
    graph.add_edge("close", "response")
    graph.add_edge("response", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
