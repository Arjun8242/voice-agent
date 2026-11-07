"""runner.py: run one turn and expose its stream.
 
stream_turn() is what S11 will use to feed sentences to TTS.
run_turn() is what /internal/turn and the evals use.
The session id doubles as the checkpointer thread id, so history is per session.
"""

import time
from typing import AsyncIterator

try:
    from backend.observability.redact import tracing_callbacks
except (ImportError, ModuleNotFoundError):
    from observability.redact import tracing_callbacks

async def stream_turn(graph, session_id: str, text: str, interrupted_reply: str = "", visitor_timezone: str = "",
                      ui_action: dict | None = None) -> AsyncIterator[tuple[str, object]]:
    """Yield ("custom", event) as the graph emits them and ("values", state) after each step.

    interrupted_reply: what the visitor heard of the previous answer before cutting in.
    visitor_timezone: IANA name from the browser; saved in the checkpoint like the rest of the state.
    ui_action: a click on a booking card ({action, payload}); text is then "".
    """

    config = {"configurable": {"thread_id": session_id}}
    callbacks = tracing_callbacks()
    if callbacks:  # the masked tracer replaces LangChain's default one: no name or email reaches LangSmith
        config["callbacks"] = callbacks
    inputs = {"query": text, "ui_action": ui_action}  # always set, so a click never carries over into the next turn
    if visitor_timezone:
        inputs["visitor_timezone"] = visitor_timezone
    if interrupted_reply:
        inputs["interrupted_reply"] = interrupted_reply

    async for mode, chunk in graph.astream(inputs, config, stream_mode =["custom", "values"]):
        yield mode, chunk


async def run_turn(graph, session_id: str, text: str, ui_action: dict | None = None) -> dict:
    start = time.perf_counter()
    first_token_ms = None
    retrieval: dict ={}
    final: dict = {}

    async for mode, chunk in stream_turn(graph, session_id = session_id, text = text, ui_action = ui_action):

        if mode == "custom" and chunk.get("type") == "token" and first_token_ms is None:
            first_token_ms = round((time.perf_counter() - start)*1000, 1)

        elif mode == "custom" and chunk.get("type") == "retrieval":
            retrieval = chunk

        elif mode == "values":
            final = chunk

    return{
        "reply": final.get("final_text", ""),
        "retrieval_status" : final.get("retrieval_status"),
        "sources" : retrieval.get("sources", []),
        "topic": final.get("topic"),
        "topic_fallback": retrieval.get("topicFallback", False),
        "tool_calls": final.get("tool_calls", []),
        "cards": final.get("cards", []),
        "booking_execute": final.get("booking_execute"),
        "errors": final.get("errors", []),
        "stage_ms": final.get("stage_ms", {}),
        "first_token_ms": first_token_ms,
        "total_ms": round((time.perf_counter() - start) * 1000, 1),
    }

        

        