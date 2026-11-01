"""tools node: run the calls the agent asked for, through the registry (S9).

Calls run in parallel (all registered tools are read-only). Only the calls that
fit under MAX_TOOL_STEPS run; any beyond it get a step_cap error result, so the
model is told instead of the call silently vanishing.
"""

import asyncio
import time

MAX_TOOL_STEPS = 4  # tool calls per turn (design doc 4.1)


def create_tools_node(registry):
    async def tools_node(state: dict) -> dict:
        start = time.perf_counter()
        pending = state.get("pending_tool_calls", [])
        steps = state.get("tool_steps", 0)
        room = max(MAX_TOOL_STEPS - steps, 0)

        to_run, over_cap = pending[:room], pending[room:]
        records = list(await asyncio.gather(*(registry.execute(c["name"], c["args"]) for c in to_run)))
        for c in over_cap:
            records.append({"name": c["name"], "args": c["args"], "cards": [], "ok": False, "ms": 0.0,
                            "result": {"error": "step_cap", "details": f"Only {MAX_TOOL_STEPS} tool calls are allowed per turn."}})

        stage = dict(state.get("stage_ms", {}))
        stage["tools"] = round(stage.get("tools", 0) + (time.perf_counter() - start) * 1000, 1)
        return {
            "pending_tool_calls": [],
            "tool_steps": steps + len(to_run),
            "tool_calls": [*state.get("tool_calls", []), *({k: v for k, v in r.items() if k != "cards"} for r in records)],
            "cards": [*state.get("cards", []), *(card for r in records for card in r["cards"])],
            "stage_ms": stage,
        }

    return tools_node
