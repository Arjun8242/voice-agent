"""state.py: the per-session graph state (design doc section 4.1, S7 + S9 subset).

Persisted per session by the checkpointer (thread_id = session_id):
    messages, topic, visitor_timezone
Reset at the start of every turn by ingest_turn:
    retrieved, retrieval_status, final_text, errors, stage_ms,
    tool_steps, tool_calls, pending_tool_calls, cards, interrupted_reply

Only messages has a reducer: LangGraph's built-in add_messages. It appends
HumanMessage / AIMessage objects, gives each an id, and removes a message when a
node returns RemoveMessage(id=...). Every other field is replaced by what a node
returns, so ingest's empty values really reset it. With an add reducer, ingest's
[] would add nothing and the lists would keep growing across turns.
"""

from typing import TypedDict, Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class TurnState(TypedDict, total = False):
    query: str
    interrupted_reply: str         # input: heard part of the previous answer after a barge-in (S12)
    messages: Annotated[list[AnyMessage], add_messages]
    topic: str | None
    visitor_timezone: str          # input: IANA name from the browser; persisted, so later turns and booking can use it
    retrieved: dict
    retrieval_status: str
    final_text: str
    errors: list[str]
    stage_ms: dict
    tool_steps: int                # tool calls run this turn (cap MAX_TOOL_STEPS)
    tool_calls: list[dict]         # every call this turn with its result, in order
    pending_tool_calls: list[dict] # calls the agent asked for, not yet run
    cards: list[dict]
    offered_slots: list[dict]      # [{slot_id, label}] from the last checkAvailability; kept across turns
    ui_action: dict | None         # input: a click on a booking card, {action, payload}; the gate clears it
    booking_execute: dict | None   # {booking_id, kind: create | delete} when a click asked for a calendar call (S15 runs it)
