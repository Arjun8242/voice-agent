"""flow.py: the code that moves an interview along. No LLM (docs/Interviewer Mode v2 — Resume + JD
Interview Design.md, "Turn handling and pacing rules").

steer    before the model call: end, repeat, nudge, move on (code speaks), or ask the model
move     code moves to the next topic: acknowledgement, a bridge on a new stage, the seed question
advance  after the model call: count the follow-up and climb the ladder, or move on; record the answer
close    the closing line, with no model call

Rules a reader would not guess:
- Code asks every first question: the opening, each topic's seed question and the bridge between
  stages. The model only writes follow-ups, so a turn that moves on makes no model call unless the
  model itself chose "next" (then it said a short acknowledgement and code asks the seed question).
- The question budget is enforced before the call (pacing.py): a question already spoken cannot be
  taken back. After the call, "next" moves on only when it was offered and the tag was valid;
  otherwise what was spoken decides: a reply with a question stays on the topic, one without moves on.
- An answer is recorded only by move, advance or close, at the end of its turn: a turn cut off by a
  barge-in never reaches them, so a merged, re-asked answer is never graded twice.
- The ladder climbs one level per follow-up up to the topic's max_level and restarts at 1 on a new
  topic. Struggle signals (skip, "I don't know", a declined hint) move on instead of climbing.
- The hard time cap is checked when a candidate answers, so a question is never cut short.
- steer can run twice in one turn: when the model labels an answer as a request for help
  (hint_request), the interviewer node sends the turn back here as a hint.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.config import get_stream_writer

from backend.graph.interview.pacing import decisions_for_turn
from backend.graph.interview.state import Answer
from backend.interview.personas import BRIDGES, CLOSING, HINT_DECLINED, OPENING, SKIP_ACK, THANKS, get_persona


def new_topic(index: int) -> dict:
    return {"topic_index": index, "followups_used": 0, "level": 1}


def create_steer_node(clock: Callable[[], float], max_seconds: float):
    async def steer_node(state: dict) -> dict:
        first_turn = not state.get("started_at")
        started_at = clock() if first_turn else state["started_at"]
        defaults = {"started_at": started_at, **(new_topic(0) if first_turn else {})}
        seconds_left = max_seconds - (clock() - started_at)
        update = {**defaults, **choose_route({**state, **defaults}, seconds_left)}
        if update.get("final_text"):  # a fixed line said before the next question
            get_stream_writer()({"type": "token", "text": update["final_text"]})
        return update

    return steer_node


def choose_route(state: dict, seconds_left: float) -> dict:
    """What this turn does, decided from the state alone."""
    if not state.get("topics"):
        return {"route": "close"}  # no plan for this session: nothing to ask, so close rather than crash
    intent = state.get("intent", "answer")
    if intent == "nudge":
        return {"route": "nudge"}  # before the finished check: a nudge after the end says nothing, not the closing
    if state.get("finished") or intent == "end":
        return {"route": "close"}
    if not state.get("last_question"):
        return {"route": "move", "final_text": OPENING}  # nothing asked yet: code opens with the first topic
    pending = pending_answer(state)
    if intent == "answer" and seconds_left <= 0:
        return {"route": "close", "pending_answer": pending}
    if intent in ("repeat", "start"):
        return {"route": "repeat"}  # "start" after a question was asked is a reconnect: ask it again
    # a request for help is never graded; None also clears an answer set before the model labelled it a hint
    if intent == "skip":
        return {"route": "move", "final_text": SKIP_ACK, "pending_answer": None}
    if intent == "hint" and not get_persona(state.get("persona")).gives_hints:
        return {"route": "move", "final_text": HINT_DECLINED, "pending_answer": None}
    if intent in ("hint", "rephrase"):
        return {"route": "interviewer", "mode": intent, "pending_answer": None}
    decisions = decisions_for_turn(state, get_persona(state.get("persona")), seconds_left)
    if not decisions:
        return {"route": "move", "final_text": THANKS, "pending_answer": pending}
    return {"route": "interviewer", "mode": "answer", "decisions": decisions, "pending_answer": pending}


def pending_answer(state: dict) -> Answer | None:
    """The answer this turn will record if it completes. Only real answers to a real question count."""
    if state.get("intent") != "answer" or not state.get("last_question"):
        return None
    topic = state["topics"][min(state.get("topic_index", 0), len(state["topics"]) - 1)]
    answer = Answer(topic_id=topic["topic_id"], question=state["last_question"], text=state["query"])
    if state.get("corrections"):
        answer["corrections"] = state["corrections"]
    return answer


def say(state: dict, line: str) -> str:
    """Speak a fixed line after whatever this turn already said; return everything said so far."""
    said = state.get("final_text", "")
    get_stream_writer()({"type": "token", "text": f" {line}" if said else line})
    return f"{said} {line}".strip()


def move_on(state: dict, index: int) -> dict:
    """Ask topic index's seed question, with a bridge when it starts a new stage; past the end, close."""
    topics = state["topics"]
    if index >= len(topics):
        return finish(state)
    topic = topics[index]
    new_stage = index > 0 and topics[index - 1]["kind"] != topic["kind"]
    line = f"{BRIDGES[topic['kind']]} {topic['seed_question']}" if new_stage and topic["kind"] in BRIDGES \
        else topic["seed_question"]
    return {**new_topic(index), "last_question": topic["seed_question"], "final_text": say(state, line)}


def create_move_node():
    async def move_node(state: dict) -> dict:
        index = state.get("topic_index", 0) + 1 if state.get("last_question") else 0
        return {**record(state), **move_on(state, index)}

    return move_node


def create_advance_node():
    async def advance_node(state: dict) -> dict:
        update = record(state)
        if state.get("mode") != "answer" or state.get("errors"):
            return update  # a hint, a rephrase, or a failed call: the counters stay as they are
        if moves_on(state):
            return {**update, **move_on(state, state.get("topic_index", 0) + 1)}
        topic = state["topics"][state.get("topic_index", 0)]
        level = min(state.get("level", 1) + 1, max(topic["max_level"], 1))
        return {**update, "followups_used": state.get("followups_used", 0) + 1, "level": level}

    return advance_node


def moves_on(state: dict) -> bool:
    """A valid "next" that was offered moves on; otherwise a spoken question keeps the topic going."""
    if state.get("tag_ok") and state.get("decision") == "next" and "next" in state.get("decisions", []):
        return True
    return "?" not in state.get("final_text", "")


def create_close_node():
    async def close_node(state: dict) -> dict:
        return {**record(state), **finish(state)}

    return close_node


def finish(state: dict) -> dict:
    return {"finished": True, "final_text": say(state, CLOSING)}


def record(state: dict) -> dict:
    """Move this turn's answer into answers, now that the turn has completed."""
    pending = state.get("pending_answer")
    return {"answers": [*state.get("answers", []), pending]} if pending else {}
