"""state.py: the per-session graph state (design doc section 4.1, S7 + S9 subset).

Persisted per session by the checkpointer (thread_id = session_id):
    messages, topic
Reset at the start of every turn by ingest_turn:
    retrieved, retrieval_status, final_text, errors, stage_ms,
    tool_steps, tool_calls, pending_tool_calls, cards

Only messages has a reducer (each turn appends to the history). Every other
field is replaced by what a node returns, so ingest's empty values really reset
it. With an add reducer, ingest's [] would add nothing and the lists would keep
growing across turns.
"""

import operator
from typing import TypedDict, Annotated

class TurnState(TypedDict, total = False):
    query: str
    messages: Annotated[list[dict], operator.add]
    topic: str | None
    retrieved: dict
    retrieval_status: str
    final_text: str
    errors: list[str]
    stage_ms: dict
    tool_steps: int                # tool calls run this turn (cap MAX_TOOL_STEPS)
    tool_calls: list[dict]         # every call this turn with its result, in order
    pending_tool_calls: list[dict] # calls the agent asked for, not yet run
    cards: list[dict]              # cards for the UI from this turn's tool calls
