"""tools node: run the calls the agent asked for, through the registry (S9).

Calls run in parallel. The only writes are startBooking and cancelBooking, and each is a
single atomic SQLite statement on this session's own row, so parallel calls cannot corrupt it. Only the calls that
fit under MAX_TOOL_STEPS run; any beyond it get a step_cap error result, so the
model is told instead of the call silently vanishing.

S10: each card is also sent as a custom stream event the moment the tools finish,
before the agent's next call, so the card shows while the answer is being spoken.
The same cards stay in state["cards"] for run_turn and /internal/turn.
"""

import asyncio
import time

from langgraph.config import get_config, get_stream_writer

MAX_TOOL_STEPS = 4  # tool calls per turn


def create_tools_node(registry):
    async def tools_node(state: dict) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        pending = state.get("pending_tool_calls", [])
        steps = state.get("tool_steps", 0)
        room = max(MAX_TOOL_STEPS - steps, 0)

        to_run, over_cap = pending[:room], pending[room:]
        # what the session knows and the model must not supply
        ctx = {"session_id": get_config()["configurable"]["thread_id"], "visitor_timezone": state.get("visitor_timezone") or "UTC"}
        records = list(await asyncio.gather(*(registry.execute(c["name"], c["args"], ctx) for c in to_run)))
        for c in over_cap:
            records.append({"name": c["name"], "args": c["args"], "cards": [], "ok": False, "ms": 0.0,
                            "result": {"error": "step_cap", "details": f"Only {MAX_TOOL_STEPS} tool calls are allowed per turn."}})

        new_cards = [card for r in records for card in r["cards"]]
        for card in new_cards:
            write({"type": "card", "card": card})

        offered = next((r["result"]["slots"] for r in records if r["name"] == "checkAvailability" and r["ok"] and r["result"]["slots"]), None)

        stage = dict(state.get("stage_ms", {}))
        stage["tools"] = round(stage.get("tools", 0) + (time.perf_counter() - start) * 1000, 1)
        return {
            "pending_tool_calls": [],
            "tool_steps": steps + len(to_run),
            "tool_calls": [*state.get("tool_calls", []), *({k: v for k, v in r.items() if k != "cards"} for r in records)],
            "cards": [*state.get("cards", []), *new_cards],
            **({"offered_slots": offered} if offered else {}),  # a search with no match keeps the earlier offer
            "stage_ms": stage,
        }

    return tools_node
