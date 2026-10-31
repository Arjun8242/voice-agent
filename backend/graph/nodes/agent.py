"""agent node: one Gemini call per invocation, streamed token by token.

S9 additions:
- Tool declarations are passed to the model.
- If the model returns function calls, they are placed in state for the tools node.
- If the model returns text, it streams as before.
- The tool loop cap is enforced by the conditional edge, not here.
"""

import asyncio
import json
import time
from functools import lru_cache
from pathlib import Path

from langgraph.config import get_stream_writer

ERROR_REPLY = "Sorry, I had trouble answering that. Could you ask again?"
HISTORY_ITEMS = 6
MAX_TOOL_STEPS = 4

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "system.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _excerpt(chunk: dict) -> str:
    meta = chunk.get("metadata", {})
    tag = f"{meta.get('section')} | status: {meta['status']}" if meta.get("status") else meta.get("section")
    return f"[{tag}]\n{chunk['text']}"


def _format_tool_result(tr: dict) -> str:
    """Format a tool result dict for the prompt."""
    name = tr.get("name", "unknown")
    result = tr.get("result", {})
    return f"[Tool result: {name}]\n{json.dumps(result, indent=2, default=str)}"


def build_prompt(state: dict) -> str:
    messages = state.get("messages", [])
    history = messages[:-1][-HISTORY_ITEMS:]  # the last message is the current query
    first_reply = not any(m["role"] == "assistant" for m in messages)
    status = state.get("retrieval_status", "skipped")
    chunks = (state.get("retrieved") or {}).get("chunks", [])
    tool_results = state.get("_tool_results", [])

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
        conversations.append("No excerpt matched this message. Do not state any fact about Arjun unless a tool result below provides it.")

    # Add tool results from previous tool call
    if tool_results:
        conversations.append(
            "Tool results from your previous call:\n\n" + "\n\n".join(_format_tool_result(tr) for tr in tool_results)
        )
        conversations.append("Use the tool results above as facts. Facts from tool results count the same as excerpt facts.")

    conversations.append(f"Visitor's latest message: {state['query']}")
    return "\n\n".join(conversations)


def create_agent_node(generate_fn, tool_defs: list[dict] | None = None):
    """generate_fn(prompt, system_instruction, tools=None) -> async iterator, dict, or coroutine."""

    async def agent_node(state: dict) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        errors = list(state.get("errors", []))
        stage = dict(state.get("stage_ms", {}))
        out, first_ms = "", None

        if state.get("retrieval_status") == "error":
            write({"type": "token", "text": ERROR_REPLY})
            return {"final_text": ERROR_REPLY, "errors": errors, "stage_ms": stage}

        # Check if we've hit the tool step cap — if so, generate without tools
        tool_steps = state.get("tool_steps", 0)
        use_tools = tool_defs is not None and tool_steps < MAX_TOOL_STEPS

        prompt = build_prompt(state)

        try:
            result = generate_fn(
                prompt,
                load_system_prompt(),
                tools=tool_defs if use_tools else None,
            )

            # If result is a coroutine, await it
            if asyncio.iscoroutine(result):
                result = await result

            # If result is an async iterator (streaming tokens)
            if hasattr(result, "__aiter__"):
                async for token in result:
                    if first_ms is None:
                        first_ms = round((time.perf_counter() - start) * 1000, 1)
                    out += token
                    write({"type": "token", "text": token})

                stage["agent_first_token"] = first_ms
                stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
                return {
                    "final_text": out,
                    "errors": errors,
                    "stage_ms": stage,
                    "_pending_tool_calls": [],
                }
            elif isinstance(result, dict):
                if result.get("function_calls"):
                    calls = result["function_calls"]
                    stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
                    return {
                        "_pending_tool_calls": calls,
                        "errors": errors,
                        "stage_ms": stage,
                    }
                else:
                    text = result.get("text", "")
                    if text:
                        write({"type": "token", "text": text})
                    stage["agent_first_token"] = round((time.perf_counter() - start) * 1000, 1)
                    stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
                    return {
                        "final_text": text,
                        "errors": errors,
                        "stage_ms": stage,
                        "_pending_tool_calls": [],
                    }
            elif isinstance(result, str):
                if result:
                    write({"type": "token", "text": result})
                stage["agent_first_token"] = round((time.perf_counter() - start) * 1000, 1)
                stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
                return {
                    "final_text": result,
                    "errors": errors,
                    "stage_ms": stage,
                    "_pending_tool_calls": [],
                }

        except Exception as err:  # CancelledError is a BaseException and passes through
            errors.append(f"agent: {err}")
            if not out:
                out = ERROR_REPLY
                write({"type": "token", "text": out})

        stage["agent_first_token"] = first_ms
        stage["agent_total"] = round((time.perf_counter() - start) * 1000, 1)
        return {"final_text": out, "errors": errors, "stage_ms": stage, "_pending_tool_calls": []}

    return agent_node
