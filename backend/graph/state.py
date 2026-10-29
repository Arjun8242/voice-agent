"""state.py: the per-session graph state (design doc section 4.1, S7 subset).
 
Persisted per session by the checkpointer (thread_id = session_id):
    messages, topic
Reset at the start of every turn by ingest_turn:
    retrieved, retrieval_status, final_text, errors, stage_ms
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
    errors: Annotated[list[str], operator.add]
    stage_ms: dict