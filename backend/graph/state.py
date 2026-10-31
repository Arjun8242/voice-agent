"""state.py: the per-session graph state (design doc section 4.1, S7 + S9).
 
Persisted per session by the checkpointer (thread_id = session_id):
    messages, topic
Reset at the start of every turn by ingest_turn:
    retrieved, retrieval_status, final_text, errors, stage_ms,
    tool_steps, tool_calls_made, cards, _pending_tool_calls, _tool_results
"""

import operator
from typing import TypedDict, Annotated

class TurnState(TypedDict, total=False):
    query: str
    messages: Annotated[list[dict], operator.add]
    topic: str | None
    retrieved: dict
    retrieval_status: str
    final_text: str
    errors: Annotated[list[str], operator.add]
    stage_ms: dict
    # S9: tool calling
    tool_steps: int                                       # count of tool rounds this turn (cap 4)
    tool_calls_made: Annotated[list[dict], operator.add]  # log of each call for the response
    cards: Annotated[list[dict], operator.add]             # card payloads for the UI
    _pending_tool_calls: list[dict]                       # function calls requested by agent
    _tool_results: list[dict]                             # results returned by tools node
