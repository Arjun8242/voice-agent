"""The WebSocket endpoint serves at most MAX_SESSIONS visitors at once: one more is told the agent is busy and
closed with 1013 (try again later), and a slot frees when a visitor leaves, even if their connection failed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.server import main


class FakeWebSocket:
    def __init__(self, live_connections: int):
        self.app = SimpleNamespace(state=SimpleNamespace(live_connections=live_connections))
        self.sent: list[dict] = []
        self.closed_with: int | None = None

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def test_a_visitor_past_the_cap_is_told_busy_and_closed(monkeypatch):
    served = []
    monkeypatch.setattr(main, "serve", lambda ws: served.append(ws))
    ws = FakeWebSocket(live_connections=main.MAX_SESSIONS)

    asyncio.run(main.websocket_endpoint(ws))

    assert served == [] and ws.closed_with == 1013
    assert ws.sent == [{"type": "error", "message": main.BUSY_MESSAGE}]
    assert ws.app.state.live_connections == main.MAX_SESSIONS


def test_a_slot_is_freed_when_a_connection_ends_even_with_an_error(monkeypatch):
    seen = []

    async def failing_serve(ws):
        seen.append(ws.app.state.live_connections)
        raise RuntimeError("connection broke")

    monkeypatch.setattr(main, "serve", failing_serve)
    ws = FakeWebSocket(live_connections=0)

    with pytest.raises(RuntimeError):
        asyncio.run(main.websocket_endpoint(ws))

    assert seen == [1] and ws.app.state.live_connections == 0
