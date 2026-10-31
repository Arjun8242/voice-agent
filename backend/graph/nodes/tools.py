"""tools node: validate and execute tool calls from the agent, add cards.

Receives tool calls from state (set by the agent node), runs them through
the registry, and returns results for the next agent call plus any cards.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.tools.registry import ToolRegistry


def create_tools_node(registry: "ToolRegistry"):
    """Return a graph node that executes tool calls through the registry."""

    async def tools_node(state: dict) -> dict:
        start = time.perf_counter()
        pending = state.get("_pending_tool_calls", [])
        stage = dict(state.get("stage_ms", {}))
        new_calls: list[dict] = []
        new_cards: list[dict] = []
        tool_results: list[dict] = []

        # Execute all pending calls (read-only tools can run in parallel)
        tasks = []
        for call in pending:
            name = call.get("name", "")
            raw_args = call.get("args", {})
            tasks.append((name, raw_args, registry.execute(name, raw_args)))

        results = await asyncio.gather(
            *(t[2] for t in tasks), return_exceptions=True
        )

        for (name, raw_args, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                tool_results.append({
                    "name": name,
                    "result": {"error": "execution_error", "tool": name, "details": str(result)},
                })
                new_calls.append({"name": name, "args": raw_args, "error": str(result)})
            else:
                tool_results.append({
                    "name": result.tool,
                    "result": result.result,
                })
                new_calls.append({
                    "name": result.tool,
                    "args": raw_args,
                    "duration_ms": result.duration_ms,
                    "is_error": result.is_error,
                })
                for card in result.cards:
                    new_cards.append(card.model_dump())

        current_steps = state.get("tool_steps", 0)
        stage["tools_total"] = round((time.perf_counter() - start) * 1000, 1)

        return {
            "_tool_results": tool_results,
            "_pending_tool_calls": [],
            "tool_steps": current_steps + 1,
            "tool_calls_made": new_calls,
            "cards": new_cards,
            "stage_ms": stage,
        }

    return tools_node

