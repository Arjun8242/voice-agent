"""llm.py: the Groq client, its warm-up, and the streaming call the graph's agent node uses.

The prompt and tool declarations are built in backend/graph; this file only talks to Groq.
"""

import json
from typing import AsyncIterator

from groq import AsyncGroq

from backend.observability.usage import LlmUsage

try:
    from config import GROQ_API_KEY, GROQ_MODEL
except (ImportError, ModuleNotFoundError):
    from backend.config import GROQ_API_KEY, GROQ_MODEL

MAX_OUTPUT_TOKENS = 512
REASONING_EFFORT = "low"

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client

    if _client is None:
        _client = AsyncGroq(api_key=GROQ_API_KEY)

    return _client

async def warm_llm() -> None:
    try:
        await _get_client().chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": "Hi"}],
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            reasoning_effort=REASONING_EFFORT,
        )
    except Exception as err:
        print(f"[llm] warm-up failed: {err}")


async def stream_text(
    prompt: str,
    system_instruction: str,
    tools: list[dict] | None = None,
    tool_calls: list[dict] | None = None,
) -> AsyncIterator[str | dict]:
    """Yield Groq output as it arrives. Used by the graph's agent node.

    Text is yielded as str; each tool call, once its arguments are complete, as {"name": ..., "args": {...}};
    last, an LlmUsage with the tokens Groq reports in its final chunk (none if it reports nothing).
    tools are declarations {name, description, parameters (JSON schema)}.
    tool_calls are the calls already run this turn, each {name, args, result}. They are sent as an assistant
    message plus one tool message per call: results pasted into the prompt as text did not count as done for
    the model, so it asked for the same call again until the step cap.
    """
    messages = [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}]
    if tool_calls:
        ids = [f"call_{i}" for i in range(len(tool_calls))]
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": i, "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for i, c in zip(ids, tool_calls)]})
        messages += [{"role": "tool", "tool_call_id": i, "content": json.dumps(c["result"], ensure_ascii=False)} for i, c in zip(ids, tool_calls)]
    extra = {}
    if tools:
        extra["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                          for t in tools]
    stream = await _get_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.3,
        max_completion_tokens=MAX_OUTPUT_TOKENS,
        reasoning_effort=REASONING_EFFORT,
        stream=True,
        **extra,
    )


    # delta is the chunks which are streamed from groq, each chunk can contain text and/or tool call fragments. We need to accumulate the tool call fragments until we have a complete tool call, then yield it as a dict.
    calls: dict[int, dict] = {}  # tool-call index -> {"name": str, "arguments": str}
    reported = None
    async for chunk in stream:
        reported = final_usage(chunk) or reported
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
        for fragment in delta.tool_calls or []:
            call = calls.setdefault(fragment.index, {"name": "", "arguments": ""})
            if fragment.function and fragment.function.name:
                call["name"] = fragment.function.name
            if fragment.function and fragment.function.arguments:
                call["arguments"] += fragment.function.arguments

    for call in calls.values():
        try:
            args = json.loads(call["arguments"] or "{}")
        except ValueError:  # shortcut: broken arguments become {}; the registry then reports any missing required one
            args = {}
        yield {"name": call["name"], "args": args if isinstance(args, dict) else {}}
    if reported is not None:
        yield to_llm_usage(reported)


def final_usage(chunk):
    """Groq sends the call's token counts once, in x_groq.usage of the final chunk (usage with stream_options)."""
    x_groq = getattr(chunk, "x_groq", None)
    return getattr(x_groq, "usage", None) or getattr(chunk, "usage", None)


def to_llm_usage(usage) -> LlmUsage:
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return LlmUsage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        cached_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
    )
