import json
from typing import Any

from fastapi import WebSocketDisconnect
from fastapi.websockets import WebSocketState

# this is function factory: create_send(ws) returns a send() function that sends messages to the given WebSocket.
def create_send(ws: Any, turn_id: int | None = None):
    """With a turn_id, every JSON message carries turnId; binary audio frames don't.

    The client drops messages whose turn has been interrupted, so a card or
    text from a cancelled turn can never show up late(helps BargeIn).
    """
    async def send(message_type: str | bytes, payload: dict | None = None) -> None:
        if ws.client_state != WebSocketState.CONNECTED:
            return

        try:
            if isinstance(message_type, (bytes, bytearray)):
                await ws.send_bytes(message_type)
            else:
                # JSON frame: { "type": ..., ...payload }
                msg = {"type": message_type, **(payload or {})}

                if turn_id is not None:
                    msg["turnId"] = turn_id
                await ws.send_text(json.dumps(msg))

        except (WebSocketDisconnect, RuntimeError, OSError):
            return  # the visitor left mid-message; a bug in the message (TypeError) is not hidden

    return send
