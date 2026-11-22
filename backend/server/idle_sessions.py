"""idle_sessions.py: forgets the conversations of visitors who left and did not come back.

Graph history lives in server memory, one checkpointer thread per session id, in both the recruiter and the
interview graph. A disconnect does not delete it at once: a reload reconnects with the same id (session_start)
and continues. So a disconnect only marks the session idle, a reconnect clears the mark, and a sweep every
SWEEP_INTERVAL_S deletes the threads of sessions idle for SESSION_IDLE_TTL_S. Without it every visitor's
history would stay in memory until the server restarts.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any

from backend.config import SESSION_IDLE_TTL_S

SWEEP_INTERVAL_S = 300


def expired_sessions(idle_since: dict[str, float], now: float, ttl: float) -> list[str]:
    """Session ids idle for at least ttl seconds at now."""
    return [session_id for session_id, since in idle_since.items() if now - since >= ttl]


async def forget_expired(idle_since: dict[str, float], graphs: Sequence[Any], now: float,
                         ttl: float = SESSION_IDLE_TTL_S) -> list[str]:
    """Delete expired sessions' threads from every graph and drop their marks. Returns the ids forgotten.
    Marks go first, so a visitor who reconnects during the deletes simply starts a fresh conversation."""
    expired = expired_sessions(idle_since, now, ttl)
    for session_id in expired:
        del idle_since[session_id]
    for session_id in expired:
        for graph in graphs:
            await graph.checkpointer.adelete_thread(session_id)
    return expired


async def sweep_forever(idle_since: dict[str, float], graphs: Sequence[Any],
                        clock: Callable[[], float] = time.monotonic) -> None:
    """Run for the server's lifetime (main.py cancels it on shutdown)."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_S)
        await forget_expired(idle_since, graphs, clock())
