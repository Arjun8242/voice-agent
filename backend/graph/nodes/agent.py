"""agent node: one Gemini call with the tools bound, streamed piece by piece.

generate_fn yields str pieces (answer text) and dict pieces (a tool call:
{"name", "args"}). Text leaves the node as custom stream events the moment it
arrives. If the model asked for tools, the calls go to state and the graph edge
sends the turn to the tools node; the tools node sends it back here with the
results in the prompt. Once MAX_TOOL_STEPS calls have run, the model is called
without tools, so it has to answer.

CancelledError is never caught here, so a barge-in stops the call immediately.
"""

import json
import time
from functools import lru_cache
from pathlib import Path
from langgraph.config import get_stream_writer
from .tools import MAX_TOOL_STEPS

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


def _tool_call(call: dict) -> str:
    return f"{call['name']}({json.dumps(call['args'])}) returned:\n{json.dumps(call['result'], ensure_ascii=False)}"


def build_prompt(state: dict, tools_offered: bool = False) -> str:
    messages = state.get("messages", [])
    history = messages[:-1][-HISTORY_ITEMS:]  # the last message is the current query
    first_reply = not any(m["role"] == "assistant" for m in messages)
    status = state.get("retrieval_status", "skipped")
    chunks = (state.get("retrieved") or {}).get("chunks", [])
    calls = state.get("tool_calls", [])

    conversations = []
    if history:
        lines = [f"{'Visitor' if m['role'] == 'user' else 'Agent'}: {m['text']}" for m in history]
        conversations.append("Conversation so far:\n" + "\n".join(lines))
    if first_reply:
        conversations.append("This is your first reply. Begin with one short sentence saying you are an AI assistant that speaks about Arjun.")
    conversations.append(f"Retrieval status: {status}")
    if status == "ok" and chunks:
        conversations.append("Excerpts (facts you may state about Arjun):\n\n" + "\n\n".join(_excerpt(c) for c in chunks))
    else:
        conversations.append("No excerpt matched this message. Do not state any fact about Arjun unless a tool result below gives it.")
    if calls:
        conversations.append("Tool calls you made this turn and their results (facts you may state about Arjun):\n\n" + "\n\n".join(_tool_call(c) for c in calls))
        if not tools_offered:
            conversations.append("You have used all tool calls for this turn. Answer from the facts above.")
    conversations.append(f"Visitor's latest message: {state['query']}")
    return "\n\n".join(conversations)


def create_agent_node(generate_fn, tools: list[dict] | None = None):
    """generate_fn(prompt, system_instruction, tools) -> async iterator of str (text) and dict (tool call) pieces.
    tools: function declarations ({name, description, parameters}); None means the model gets no tools."""

    async def agent_node(state: dict) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        errors = list(state.get("errors", []))
        stage = dict(state.get("stage_ms", {}))
        out, first_ms, calls = "", None, []

        if state.get("retrieval_status") == "error":
            write({"type": "token", "text": ERROR_REPLY})
            return {"final_text": ERROR_REPLY, "errors": errors, "stage_ms": stage}

        offered = tools if tools and state.get("tool_steps", 0) < MAX_TOOL_STEPS else None
        try:
            async for piece in generate_fn(build_prompt(state, offered is not None), load_system_prompt(), tools=offered):
                if isinstance(piece, dict):
                    calls.append(piece)
                    continue
                if first_ms is None:
                    first_ms = round((time.perf_counter() - start) * 1000, 1)
                out += piece
                write({"type": "token", "text": piece})
        except Exception as err:  # CancelledError is a BaseException and passes through
            errors.append(f"agent: {err}")
            calls = []
            if not out:
                out = ERROR_REPLY
                write({"type": "token", "text": out})

        stage["agent_total"] = round(stage.get("agent_total", 0) + (time.perf_counter() - start) * 1000, 1)
        if calls:  # the answer comes from the next agent call, after the tools run
            return {"pending_tool_calls": calls, "final_text": "", "errors": errors, "stage_ms": stage}
        stage["agent_first_token"] = first_ms
        return {"final_text": out, "errors": errors, "stage_ms": stage}

    return agent_node
