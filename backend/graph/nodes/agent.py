"""agent node: one Gemini call, streamed token by token (no tools yet; S9 adds them).
 
Tokens leave the node as custom stream events the moment the model yields them.
CancelledError is never caught here, so a barge-in stops the call immediately.
"""

import time
from functools import lru_cache
from pathlib import Path
 
from langgraph.config import get_stream_writer
 
ERROR_REPLY = "Sorry, I had trouble answering that. Could you ask again?"
HISTORY_ITEMS = 6
 
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "system.md"
 
 
@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()
 
 
def _excerpt(chunk: dict) -> str:
    meta = chunk.get("metadata", {})
    tag = f"{meta.get('section')} | status: {meta['status']}" if meta.get("status") else meta.get("section")
    return f"[{tag}]\n{chunk['text']}"

def build_prompt(state: dict) -> str:
    messages = state.get("messages", [])
    history = messages[:-1][-HISTORY_ITEMS:]  # the last message is the current query
    first_reply = not any(m["role"] == "assistant" for m in messages)
    status = state.get("retrieval_status", "skipped")
    chunks = (state.get("retrieved") or {}).get("chunks", [])
 
    conversations = []
    if history:
        lines = [f"{'Visitor' if m['role'] == 'user' else 'Agent'}: {m['text']}" for m in history]
        conversations.append("Conversation so far:\n" + "\n".join(lines))
    if first_reply:
        conversations.append("This is your first reply. Begin with one short sentence saying you are an AI assistant that speaks about Arjun.")
    conversations.append(f"Retrieval status: {status}")
    if status == "ok" and chunks:
        conversations.append("Excerpts (the only facts you may state about Arjun):\n\n" + "\n\n".join(_excerpt(c) for c in chunks))
    else:
        conversations.append("No excerpt matched this message. Do not state any fact about Arjun.")
    conversations.append(f"Visitor's latest message: {state['query']}")
    return "\n\n".join(conversations)
 
 
def create_agent_node(generate_fn):
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces."""
 
    async def agent_node(state: dict) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        errors = list(state.get("errors", []))
        stage = dict(state.get("stage_ms", {}))
        out, first_ms = "", None
 
        if state.get("retrieval_status") == "error":
            write({"type": "token", "text": ERROR_REPLY})
            return {"final_text": ERROR_REPLY, "errors": errors, "stage_ms": stage}
 
        try:
            async for token in generate_fn(build_prompt(state), load_system_prompt()):
                if first_ms is None:
                    first_ms = round((time.perf_counter() - start) * 1000, 1)
                out += token
                write({"type": "token", "text": token})
        except Exception as err:  # CancelledError is a BaseException and passes through
            errors.append(f"agent: {err}")
            if not out:
                out = ERROR_REPLY
                write({"type": "token", "text": out})
 
        stage["agent_first_token"] = first_ms
        stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
        return {"final_text": out, "errors": errors, "stage_ms": stage}
 
    return agent_node