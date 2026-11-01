"""protocol.py: WebSocket send helper, bound to one connection.

Corresponds to src/server/protocol.ts.
"""
import json
from typing import Any
from fastapi.websockets import WebSocketState


def create_send(ws: Any):
    """
    Returns an async send() function bound to ws.
    """
    async def send(message_type: str | bytes, payload: dict | None = None) -> None:
        if ws.client_state != WebSocketState.CONNECTED:
            return

        try:
            if isinstance(message_type, (bytes, bytearray)):
                # Binary frame: 4-byte sentence-ID prefix + MP3 chunk
                await ws.send_bytes(message_type)
            else:
                # JSON frame: { "type": ..., ...payload }
                msg = {"type": message_type, **(payload or {})}
                await ws.send_text(json.dumps(msg))

        except Exception:
            pass

    return send


def with_turn_id(send, turn_id: int):
    """Wrap send() so every JSON message carries turnId; binary audio frames pass through.

    The client drops messages from turns it has been told were interrupted, so a card or
    text from a cancelled turn can never show up late.
    """
    async def send_for_turn(message_type: str | bytes, payload: dict | None = None) -> None:
        if isinstance(message_type, (bytes, bytearray)):
            await send(message_type)
        else:
            await send(message_type, {**(payload or {}), "turnId": turn_id})

    return send_for_turn
