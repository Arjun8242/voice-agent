"""flow.py: the code that moves an interview along. No LLM (docs/interviewer-mode-plan.md §6.3, B7).

steer    before the model call: end, repeat, move to the next topic, or ask the model
advance  after the model call: count the follow-up and climb the ladder, or move on; record the answer
close    the closing line, with no model call

Rules a reader would not guess:
- The follow-up cap is enforced before the call (the model is offered only "next"), because a
  question already spoken cannot be taken back. A decision outside what was offered counts as "next".
- An answer is recorded only by advance or close, at the end of its turn: a turn cut off by a
  barge-in never reaches them, so a merged, re-asked answer is never graded twice.
- The ladder climbs one level per follow-up (1 explain, 2 justify, 3 stress) and restarts at 1 on a
  new topic. Struggle signals (skip, "I don't know", a declined hint) move on instead of climbing.
- The time cap is checked when a candidate answers, so a question is never cut short.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.config import get_stream_writer

from backend.graph.interview.prompt import decisions_for_turn
from backend.graph.interview.state import Answer
from backend.interview.personas import CLOSING, HINT_DECLINED, get_persona

MAX_LEVEL = 3


def new_topic(index: int) -> dict:
    return {"topic_index": index, "followups_used": 0, "level": 1}


def create_steer_node(topic_ids: list[str], clock: Callable[[], float], max_seconds: float):
    async def steer_node(state: dict) -> dict:
        first_turn = not state.get("started_at")
        started_at = clock() if first_turn else state["started_at"]
        defaults = {"started_at": started_at, **(new_topic(0) if first_turn else {})}
        update = {**defaults, **choose_route(state, topic_ids, clock() - started_at, max_seconds)}
        if update.get("final_text"):  # a fixed line said before the model's question
            get_stream_writer()({"type": "token", "text": update["final_text"] + " "})
        return update

    return steer_node


def choose_route(state: dict, topic_ids: list[str], elapsed_s: float, max_seconds: float) -> dict:
    """What this turn does, decided from the state alone."""
    intent = state.get("intent", "answer")
    persona = get_persona(state.get("persona"))
    pending = pending_answer(state, topic_ids)
    if state.get("finished") or intent == "end":
        return {"route": "close"}
    if intent == "answer" and elapsed_s >= max_seconds:
        return {"route": "close", "pending_answer": pending}
    if intent == "repeat" and state.get("last_question"):
        return {"route": "repeat"}
    declined_hint = intent == "hint" and not persona.gives_hints
    if intent == "skip" or declined_hint:
        index = state.get("topic_index", 0) + 1
        if index >= len(topic_ids):
            return {"route": "close"}
        fixed = {"final_text": HINT_DECLINED} if declined_hint else {}
        return {"route": "interviewer", "mode": "new_topic" if declined_hint else "skip", **new_topic(index), **fixed}
    mode = intent if intent in ("start", "hint", "rephrase") else "answer"  # "repeat" with nothing asked yet: answer it
    return {"route": "interviewer", "mode": mode, "pending_answer": pending}


def pending_answer(state: dict, topic_ids: list[str]) -> Answer | None:
    """The answer this turn will record if it completes. Only real answers to a real question count."""
    if state.get("intent") != "answer" or not state.get("last_question"):
        return None
    topic_id = topic_ids[min(state.get("topic_index", 0), len(topic_ids) - 1)]
    return Answer(topic_id=topic_id, question=state["last_question"], text=state["query"])


def create_advance_node(topic_ids: list[str]):
    async def advance_node(state: dict) -> dict:
        update = record(state)
        if state.get("mode") != "answer":
            return update  # opening, hint, rephrase or a topic move: the counters are already right
        decision = state.get("decision", "next")
        if decision not in decisions_for_turn(state, get_persona(state.get("persona"))):
            decision = "next"
        if decision != "next":
            level = min(state.get("level", 1) + 1, MAX_LEVEL)
            return {**update, "followups_used": state.get("followups_used", 0) + 1, "level": level}
        index = state.get("topic_index", 0) + 1
        if index < len(topic_ids):
            return {**update, **new_topic(index)}
        return {**update, **finish(state)}  # the model said its thanks; the closing line follows

    return advance_node


def create_close_node():
    async def close_node(state: dict) -> dict:
        return {**record(state), **finish(state)}

    return close_node


def finish(state: dict) -> dict:
    get_stream_writer()({"type": "token", "text": CLOSING})
    spoken = f"{state.get('final_text', '')} {CLOSING}".strip()
    return {"finished": True, "final_text": spoken}


def record(state: dict) -> dict:
    """Move this turn's answer into answers, now that the turn has completed."""
    pending = state.get("pending_answer")
    return {"answers": [*state.get("answers", []), pending]} if pending else {}
