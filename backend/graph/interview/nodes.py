"""nodes.py: the interview graph's nodes. Only the interviewer node calls the LLM.

ingest       record the turn, classify its intent, reset per-turn fields (no LLM)
repeat       "can you repeat that": replay the last question word for word (no LLM)
interviewer  one streamed model call; the control tag is stripped before anything is spoken
response     save what the interviewer said to the history
steer, advance and close (no LLM) are in flow.py.

Text leaves the graph as {"type": "token"} custom events, as in the recruiter graph, so
pipeline/voice_turn.py speaks it without knowing which graph ran.
CancelledError is never caught here, so a barge-in stops the model call at once.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer

from backend.graph.interview.prompt import build_turn_message, load_interviewer_prompt
from backend.graph.interview.tag import TagBuffer
from backend.graph.nodes.ingest import heard_history
from backend.interview.intents import classify_intent
from backend.interview.personas import get_persona
from backend.interview.plan import Topic
from backend.observability.usage import LlmUsage, usage_event

ERROR_LINE = "Sorry, I lost my train of thought. Could you say that again?"


async def ingest_node(state: dict) -> dict:
    """An empty query is the request for the opening question: it adds no candidate message."""
    query = (state.get("query") or "").strip()
    messages = heard_history(state.get("messages") or [], state.get("interrupted_reply") or "")
    if query:
        messages.append(HumanMessage(query))
    return {
        "query": query,
        "messages": messages,
        "interrupted_reply": "",  # one-shot input: must not be added again next turn
        "intent": classify_intent(query) if query else "start",
        "mode": "",
        "route": "",
        "pending_answer": None,
        "final_text": "",
        "decision": "",
        "tag_ok": False,
        "errors": [],
    }


async def repeat_node(state: dict) -> dict:
    question = state["last_question"]
    get_stream_writer()({"type": "token", "text": question})
    return {"final_text": question}


def create_interviewer_node(generate_fn: Callable, topics: list[Topic]):
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces (rag/llm.py stream_text)."""

    async def interviewer_node(state: dict) -> dict:
        write = get_stream_writer()
        index = min(state.get("topic_index", 0), len(topics) - 1)
        next_title = topics[index + 1]["title"] if index + 1 < len(topics) else None
        message = build_turn_message(state, topics[index], get_persona(state.get("persona")), next_title)
        tags, spoken, errors = TagBuffer(), "", list(state.get("errors", []))
        try:
            async for piece in generate_fn(message, load_interviewer_prompt()):
                if isinstance(piece, LlmUsage):
                    write(usage_event(piece))
                    continue
                spoken += speak(write, tags.feed(piece))
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


def speak(write: Callable[[dict], None], text: str) -> str:
    """Send text to the browser and TTS as a token event; return it for the running total."""
    if text:
        write({"type": "token", "text": text})
    return text


async def response_node(state: dict) -> dict:
    text = state.get("final_text", "")
    return {"messages": [AIMessage(text)]} if text else {}
