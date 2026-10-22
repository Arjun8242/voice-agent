"""connection.py: Per-connection handler — wires barge-in, STT, and answer turns.

Corresponds to src/server/connection.ts.
"""

import asyncio
from fastapi import WebSocket

try:
    from pipeline.answer_turn import answer_turn
    from pipeline.barge_in import BargeIn
    from server.protocol import create_send
    from server.session import (
        Conversation,
        finish_turn,
        interrupt_turn,
        is_answering,
        new_conversation,
        start_turn,
    )
    from providers.stt import create_stt
except (ImportError, ModuleNotFoundError):
    from backend.pipeline.answer_turn import answer_turn
    from backend.pipeline.barge_in import BargeIn
    from backend.server.protocol import create_send
    from backend.server.session import (
        Conversation,
        finish_turn,
        interrupt_turn,
        is_answering,
        new_conversation,
        start_turn,
    )
    from backend.providers.stt import create_stt


async def handle_connection(ws: WebSocket) -> None:
    """Handle one WebSocket connection from accept() to disconnect."""
    await ws.accept()
    print("[server] Client connected")

    conv: Conversation = new_conversation()
    send = create_send(ws)

    # A new event is created for each turn so a stale event from a cancelled turn
    # cannot abort a newer one.
    interrupt_event: asyncio.Event = asyncio.Event()

    # -------------------------------------------------------------------------
    # Barge-in
    # -------------------------------------------------------------------------
    def do_interrupt() -> None:
        interrupt_event.set()
        interrupt_turn(conv)
        asyncio.get_running_loop().create_task(send("interrupted"))

    barge_in = BargeIn(
        is_answering=lambda: is_answering(conv),
        is_speaking=lambda: conv.agent_speaking,
        interrupt=do_interrupt,
    )

    # -------------------------------------------------------------------------
    # Turn launcher — creates a fresh interrupt_event for each turn.
    # -------------------------------------------------------------------------
    def launch_turn(text: str) -> None:
        nonlocal interrupt_event
        interrupt_event = asyncio.Event()   # fresh per turn

        task = asyncio.create_task(_run_turn(text, conv, send, interrupt_event))
        start_turn(conv, task)

    async def _run_turn(
        text: str,
        conv: Conversation,
        send,
        ev: asyncio.Event,
    ) -> None:
        try:
            await answer_turn(text, conv, send, ev)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            print(f"[answerTurn] {err}")
        finally:
            finish_turn(conv, asyncio.current_task())

    # -------------------------------------------------------------------------
    # STT client
    # -------------------------------------------------------------------------
    class _Handlers:
        def on_speech_start(self) -> None:
            barge_in.on_speech_start()

        def on_speech_end(self) -> None:
            barge_in.on_speech_end()

        async def on_partial(self, text: str) -> None:
            await send("transcript_partial", {"text": text})

        async def on_final(self, text: str) -> None:
            await send("transcript_final", {"text": text})
            launch_turn(text)

        async def on_error(self, message: str) -> None:
            await send("error", {"message": f"STT error: {message}"})

    stt = create_stt(_Handlers())

    # -------------------------------------------------------------------------
    # Receive loop — handles raw PCM audio from AudioWorklet
    # -------------------------------------------------------------------------
    try:
        while True:
            msg = await ws.receive()

            if "bytes" in msg and msg["bytes"]:
                # Raw PCM from AudioWorklet → STT handles base64-encoding + queuing
                stt.send_audio(msg["bytes"])

    except Exception:
        pass  # client disconnected or WS error

    finally:
        barge_in.dispose()
        stt.close()
        interrupt_turn(conv)
        print("[server] Client disconnected")
