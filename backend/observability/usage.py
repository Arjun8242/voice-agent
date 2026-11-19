"""usage.py: the tokens one LLM call used, as Groq reports them, and their total for a turn.

rag/llm.py yields an LlmUsage as the last piece of each streamed call. The graph nodes that call
the model turn it into a {"type": "usage"} event; voice_turn adds the totals to the turn log and
run_turn returns them, so /internal/turn shows real token counts instead of estimates.

A call cancelled by a barge-in never reaches its final chunk, so its tokens are not counted here,
though Groq may still bill them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int
    output_tokens: int  # includes reasoning tokens
    cached_tokens: int  # input tokens Groq served from its prompt cache
    reasoning_tokens: int  # gpt-oss thinking before it answers; billed as output, never spoken


def empty_totals() -> dict[str, int]:
    return {"llm_calls": 0, **{field: 0 for field in LlmUsage.__dataclass_fields__}}


def add_usage(totals: dict[str, int], event: dict) -> None:
    """Add one usage event (an LlmUsage as a dict, plus "type") to a turn's totals, in place."""
    totals["llm_calls"] += 1
    for field in LlmUsage.__dataclass_fields__:
        totals[field] += event.get(field, 0)


def usage_event(usage: LlmUsage) -> dict:
    return {"type": "usage", **asdict(usage)}
