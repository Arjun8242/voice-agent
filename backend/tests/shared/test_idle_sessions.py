"""Idle sessions are forgotten: graph history of a visitor who left and did not come back is deleted after the
TTL, from every graph, while a recent leaver keeps theirs for a reload. No network."""

from __future__ import annotations

import asyncio

from backend.server.idle_sessions import forget_expired


class RecordingCheckpointer:
    def __init__(self):
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class FakeGraph:
    def __init__(self):
        self.checkpointer = RecordingCheckpointer()


def test_sessions_idle_past_the_ttl_are_deleted_from_every_graph_and_recent_ones_kept():
    recruiter, interview = FakeGraph(), FakeGraph()
    idle_since = {"old": 0.0, "recent": 950.0}

    forgotten = asyncio.run(forget_expired(idle_since, [recruiter, interview], now=1000.0, ttl=100.0))

    assert forgotten == ["old"]
    assert recruiter.checkpointer.deleted == ["old"] and interview.checkpointer.deleted == ["old"]
    assert idle_since == {"recent": 950.0}
