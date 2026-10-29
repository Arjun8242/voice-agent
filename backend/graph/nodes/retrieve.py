"""retrieve node: topic-aware dense search (retrieval v1)."""
 
import time
 
from langgraph.config import get_stream_writer
 
TOP_K = 4

def create_retrieve_node(retrieve_fn):
    async def retrieve_node(state:dict) -> dict:
        start = time.perf_counter()
        topic = state.get("topic")
        fallback = False

        try:
            rag = await retrieve_fn(state["query"], top_k=4, topic=topic)

            if rag.get("status") == "none_relevant" and topic:
                rag = await retrieve_fn(state["query"], top_k=TOP_K, topic=None)
                fallback = True
        except Exception as err:  # retrieval failed: do not pretend the KB has no answer
            return {
                "retrieved": {},
                "retrieval_status": "error",
                "errors": [*state.get("errors", []), f"retrieve: {err}"],
                "stage_ms": {**state.get("stage_ms", {}), "retrieve": None},
            }
        
        get_stream_writer()({
            "type": "retrieval",
            "status" : rag["status"],
            "sources": [c["metadata"].get("id") for c in rag.get("chunks", [])],
            "topic": topic,
            "topicFallback": fallback,
        })
        return {
            "retrieved": rag,
            "retrieval_status": rag["status"],
            "stage_ms": {**state.get("stage_ms", {}), "retrieve": round((time.perf_counter() - start) * 1000, 1)},
        }
 
    return retrieve_node
        