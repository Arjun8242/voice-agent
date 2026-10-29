"""runner.py: run one turn and expose its stream.
 
stream_turn() is what S11 will use to feed sentences to TTS.
run_turn() is what /internal/turn and the evals use.
The session id doubles as the checkpointer thread id, so history is per session.
"""

import time
from typing import AsyncIterator

async def stream_turn(graph, session_id: str, text: str) -> AsyncIterator[tuple[str, object]]:
    """Yield ("custom", event) as the graph emits them and ("values", state) after each step."""

    config = {"configurable": {"thread_id": session_id}}

    async for mode, chunk in graph.astream({"query": text}, config, stream_mode =["custom", "values"]):
        yield mode, chunk


async def run_turn(graph, session_id: str, text: str) -> dict:
    start = time.perf_counter()
    first_token_ms = None
    retrieval: dict ={}
    final: dict = {}

    async for mode, chunk in stream_turn(graph, session_id = session_id, text = text):

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
        "errors": final.get("errors", []),
        "stage_ms": final.get("stage_ms", {}),
        "first_token_ms": first_token_ms,
        "total_ms": round((time.perf_counter() - start) * 1000, 1),
    }

        

        