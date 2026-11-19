"""nodes.py: the interview graph's nodes. Only the interviewer node calls the LLM.

ingest       correct mis-heard terms, record the turn, classify its intent, reset per-turn fields (no LLM)
repeat       "can you repeat that": replay the last question word for word (no LLM)
nudge        the candidate stayed silent: say the persona's fixed nudge line (no LLM)
interviewer  one streamed model call; the control tag is stripped before anything is spoken.
             A tag saying hint_request on an answer stops the reply and sends the turn back to steer.
response     save what the interviewer said to the history
steer, move, advance and close (no LLM) are in flow.py.

Text leaves the graph as {"type": "token"} custom events, as in the recruiter graph, so
pipeline/voice_turn.py speaks it without knowing which graph ran.
CancelledError is never caught here, so a barge-in stops the model call at once.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import aclosing

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer

from backend.graph.interview.prompt import build_turn_message, load_interviewer_prompt
from backend.graph.interview.tag import HINT_REQUEST, TagBuffer
from backend.graph.nodes.ingest import heard_history
from backend.interview.glossary import normalize_terms
from backend.interview.intents import classify_intent
from backend.interview.personas import get_persona
from backend.interview.plan import Topic
from backend.observability.usage import LlmUsage, usage_event

ERROR_LINE = "Sorry, I lost my train of thought. Could you say that again?"


async def ingest_node(state: dict) -> dict:
    """An empty query is the request for the opening question, or a nudge: neither adds a candidate message."""
    query, corrections = normalize_terms((state.get("query") or "").strip(), state.get("glossary") or [])
    nudge = state.get("nudge")
    messages = heard_history(state.get("messages") or [], state.get("interrupted_reply") or "")
    if query:
        messages.append(HumanMessage(query))
    return {
        "query": query,
        "messages": messages,
        "interrupted_reply": "",  # one-shot input: must not be added again next turn
        "nudge": None,  # one-shot input too: later turns do not send the key, so it would linger
        "nudge_index": nudge,
        "intent": "nudge" if nudge is not None else classify_intent(query) if query else "start",
        "mode": "",
        "route": "",
        "decisions": [],
        "corrections": corrections,
        "pending_answer": None,
        "final_text": "",
        "decision": "",
        "tag_ok": False,
        "errors": [],
    }


async def nudge_node(state: dict) -> dict:
    """The persona's nudge line. Nothing after the interview ended or for a persona without nudges.
    last_question is kept, so "repeat that" after a nudge replays the real question."""
    lines = get_persona(state.get("persona")).nudges
    index = state.get("nudge_index") or 0
    if state.get("finished") or index >= len(lines):
        return {}
    get_stream_writer()({"type": "token", "text": lines[index]})
    return {"final_text": lines[index]}


async def repeat_node(state: dict) -> dict:
    question = state["last_question"]
    get_stream_writer()({"type": "token", "text": question})
    return {"final_text": question}


def create_interviewer_node(generate_fn: Callable):
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces (rag/llm.py stream_text).
    steer routes here only when the session has topics, so state["topics"] is never empty."""

    async def interviewer_node(state: dict) -> dict:
        write = get_stream_writer()
        topics: list[Topic] = state["topics"]
        topic = topics[min(state.get("topic_index", 0), len(topics) - 1)]
        message = build_turn_message(state, topic, get_persona(state.get("persona")))
        tags, spoken, errors = TagBuffer(), "", list(state.get("errors", []))
        watch_for_hint = state.get("mode") == "answer"  # in hint mode the model is meant to help
        try:
            async with aclosing(generate_fn(message, load_interviewer_prompt())) as stream:
                async for piece in stream:
                    if isinstance(piece, LlmUsage):
                        write(usage_event(piece))
                        continue
                    text = tags.feed(piece)
                    if watch_for_hint and tags.decision == HINT_REQUEST:
                        return asked_for_hint(errors)  # the tag comes first, so nothing of this reply was spoken
                    spoken += speak(write, text)
        except Exception as err:  # CancelledError is a BaseException and passes through
            errors.append(f"interviewer: {err}")
        spoken += speak(write, tags.finish())
        if not spoken.strip():
            spoken = speak(write, ERROR_LINE)
            errors.append("interviewer: nothing to say")
        said = f"{state.get('final_text', '')} {spoken.strip()}".strip()  # after any fixed line steer spoke
        update = {"final_text": said, "decision": tags.decision, "tag_ok": tags.tag_ok, "errors": errors}
        if not errors:
            update["last_question"] = spoken.strip()  # a failed turn keeps the real question for "repeat"
        return update

    return interviewer_node


def asked_for_hint(errors: list[str]) -> dict:
    """The model labelled the turn a request for help. Back to steer as a hint turn: code then gives
    the hint (neutral) or declines it and moves on (strict), exactly as for "can I get a hint"."""
    return {"intent": "hint", "route": "steer", "decision": HINT_REQUEST, "tag_ok": True, "errors": errors}


def speak(write: Callable[[dict], None], text: str) -> str:
    """Send text to the browser and TTS as a token event; return it for the running total."""
    if text:
        write({"type": "token", "text": text})
    return text


async def response_node(state: dict) -> dict:
    text = state.get("final_text", "")
    return {"messages": [AIMessage(text)]} if text else {}
