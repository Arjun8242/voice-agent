"""connection.py: Per-connection handler — wires barge-in, STT, and answer turns.
"""
import re
import asyncio
import json
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo
from fastapi import WebSocket
import httpx

from backend.observability.timings import append_turn_log
from backend.pipeline.turn_taking import TurnTaker

try:
    from pipeline.voice_turn import voice_turn
    from pipeline.barge_in import BargeIn
    from server.protocol import create_send, with_turn_id
    from server.session import (
        Conversation,
        cut_off,
        finish_turn,
        interrupt_turn,
        is_answering,
        new_conversation,
        record_report,
        start_turn,
        take_heard,
    )
    from providers.stt import create_stt


except (ImportError, ModuleNotFoundError):
    from backend.pipeline.voice_turn import voice_turn
    from backend.pipeline.barge_in import BargeIn
    from backend.server.protocol import create_send, with_turn_id
    from backend.server.session import (
        Conversation,
        cut_off,
        finish_turn,
        interrupt_turn,
        is_answering,
        new_conversation,
        record_report,
        start_turn,
        take_heard,
    )
    from backend.providers.stt import create_stt

DEFAULT_TIMEZONE = "Asia/Kolkata"
SESSION_ID_RE = re.compile(r"[0-9a-f]{32}")

def valid_timezone(name: object) -> str:
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return DEFAULT_TIMEZONE


async def handle_connection(ws: WebSocket, tts_client: httpx.AsyncClient, graph: Any, executor: Any = None) -> None:
    """Handle one WebSocket connection from accept() to disconnect.

    graph is the compiled agent graph. The connection id is its thread id, so the
    checkpointer keeps the conversation history per connection.
    executor is the BookingExecutor (booking/execute.py), or None while booking is disabled.
    """
    await ws.accept()
    print("[server] Client connected")

    conv: Conversation = new_conversation()
    send = create_send(ws)
    session_id = uuid.uuid4().hex
    visitor_timezone = DEFAULT_TIMEZONE
    turn_id = 0  # counts turns on this connection; every message of a turn carries it
    held_stt_ms: float | None = None  # speech end -> final transcript, for the turn being held
    last_final_at: float | None = None  # when that final arrived; the hold is measured from it
    speech_started_at: float | None = None  # when STT last heard the visitor start, for barge_in_ms
    turn_timings: dict | None = None  # the running spoken turn's log line (None for a click)

    # A new event is created for each turn so a stale event from a cancelled turn
    # cannot abort a newer one.
    interrupt_event: asyncio.Event = asyncio.Event()

    # -------------------------------------------------------------------------
    # Barge-in
    # -------------------------------------------------------------------------
    def do_interrupt() -> None:
        interrupt_event.set()
        cut_off(conv, turn_id)  # remember what was queued; the client's playback report says how much was heard
        interrupt_turn(conv)
        asyncio.get_running_loop().create_task(send("interrupted", {"turnId": turn_id}))

    def on_barge_in() -> None:
        if turn_timings is not None and speech_started_at is not None:
            # speech start -> interrupt, server side. Lost if the turn already wrote its log line (audio still playing).
            turn_timings["barge_in_ms"] = round((time.perf_counter() - speech_started_at) * 1000, 1)
        do_interrupt()

    barge_in = BargeIn(
        is_answering=lambda: is_answering(conv),
        is_speaking=lambda: conv.agent_speaking,
        interrupt=on_barge_in,
    )

    # -------------------------------------------------------------------------
    # Booking calls — owned by the connection, not the turn, so a cut-in cannot stop one halfway
    # or hide its result. booking_update has no turnId, so the browser never drops it as stale.
    # -------------------------------------------------------------------------
    booking_tasks: set[asyncio.Task] = set()  # keeps a reference so a running call is not garbage-collected

    def start_booking_execute(event: dict) -> None:
        async def run() -> None:
            try:
                update = await executor.run(event["booking_id"], event["kind"])
                if update:
                    await send("booking_update", update)
            except Exception as err:  # the visitor may have left; the booking itself is already decided
                print(f"[booking] {err}")

        if executor is not None:
            task = asyncio.get_running_loop().create_task(run())
            booking_tasks.add(task)
            task.add_done_callback(booking_tasks.discard)

    # -------------------------------------------------------------------------
    # Turn launcher — creates a fresh interrupt_event for each turn.
    # -------------------------------------------------------------------------
    def launch_turn(text: str, ui_action: dict | None = None) -> None:
        nonlocal interrupt_event, turn_id, turn_timings
        interrupt_event = asyncio.Event()   # fresh per turn
        turn_id += 1
        timings = None  # a click has no speech to time, and must not skew the latency report
        if ui_action is None:
            hold_ms = round((time.perf_counter() - last_final_at) * 1000, 1) if last_final_at else None
            timings = {"turn_id": turn_id, "stt_ms": held_stt_ms, "hold_ms": hold_ms,
                       "turn_decision": turn_taker.last_decision, "segments_merged": turn_taker.last_segments}
        turn_timings = timings

        task = asyncio.create_task(_run_turn(text, conv, with_turn_id(send, turn_id), interrupt_event, timings, ui_action))
        start_turn(conv, task)

    async def _run_turn(
        text: str,
        conv: Conversation,
        send,
        ev: asyncio.Event,
        timings: dict | None,
        ui_action: dict | None,
    ) -> None:
        try:
            waited = time.perf_counter()
            heard = await take_heard(conv)  # what the visitor heard of a cut-off answer, if the last turn was one
            if timings is not None:
                timings["wait_ms"] = round((time.perf_counter() - waited) * 1000, 1)
            await voice_turn(text, conv, send, ev, tts_client, graph, session_id, heard, timings,
                             visitor_timezone=visitor_timezone, ui_action=ui_action, on_booking_execute=start_booking_execute)
        except Exception as err:  # CancelledError is not an Exception: a barge-in ends the task as cancelled
            print(f"[voiceTurn] {err}")
        finally:
            finish_turn(conv, asyncio.current_task())

    # -------------------------------------------------------------------------
    # Turn-taking: finals are held and merged until the speaker is done (pipeline/turn_taking.py)
    # -------------------------------------------------------------------------
    def commit_turn(text: str) -> None:
        loop = asyncio.get_running_loop()
        loop.create_task(send("transcript_final", {"text": text}))
        if is_answering(conv):
            do_interrupt()  # words too short for barge-in still replace the answer, keeping only what was heard
        launch_turn(text)

    def reopen_turn() -> bool:
        """Speech resumed right after a commit: cancel that turn if none of its audio has played."""
        if not is_answering(conv) or conv.agent_speaking:
            return False
        do_interrupt()
        return True

    def send_turn_state(state: str) -> None:
        """speaking / holding / thinking / idle. No turnId: it is about the visitor, not an agent turn."""
        asyncio.get_running_loop().create_task(send("turn_state", {"state": state}))

    turn_taker = TurnTaker(commit=commit_turn, is_answering=lambda: is_answering(conv), reopen_turn=reopen_turn,
                           on_state=send_turn_state)

    # -------------------------------------------------------------------------
    # Messages from the browser (text frames)
    # -------------------------------------------------------------------------
    def on_client_message(raw: str) -> None:
        """playback_progress: the sentence that was playing when the answer was cut off.
        playback_ended: the answer's audio finished, so speech from now on is not a barge-in.
        session_start: the first message of a page load. Carries the id the browser kept (so a refresh
        continues the same graph thread) and the visitor's timezone.
        ui_action: a click on a booking card, {action, payload}. It runs as a turn of its own through the
        graph's booking_gate; the gate checks every field, so only the shape is checked here."""
        nonlocal session_id, visitor_timezone
        try:
            data = json.loads(raw)
        except ValueError:
            return  # not JSON: ignore it, do not drop the connection
        if isinstance(data, dict) and data.get("type") == "playback_progress":
            record_report(conv, data.get("turnId"), data.get("lastSentenceId"))
        elif isinstance(data, dict) and data.get("type") == "playback_ended" and data.get("turnId") == turn_id:
            conv.agent_speaking = False  # an older turn's ended message must not clear a newer turn's audio
        elif isinstance(data, dict) and data.get("type") == "session_start":
            old = data.get("sessionId")
            if isinstance(old, str) and SESSION_ID_RE.fullmatch(old):  # only ids we could have made: it becomes a thread id
                session_id = old
            visitor_timezone = valid_timezone(data.get("timezone"))
            asyncio.get_running_loop().create_task(send("session", {"sessionId": session_id}))  # the browser stores this
        elif isinstance(data, dict) and data.get("type") == "ui_action":
            action, payload = data.get("action"), data.get("payload") or {}
            if isinstance(action, str) and isinstance(payload, dict):
                turn_taker.drop_pending()  # words still being held must not start a turn after the click
                if is_answering(conv):
                    do_interrupt()  # a click while the agent talks replaces the answer, as speech would
                launch_turn("", {"action": action, "payload": payload})

    # -------------------------------------------------------------------------
    # STT client
    # -------------------------------------------------------------------------
    class _Handlers:
        def on_speech_start(self) -> None:
            nonlocal speech_started_at
            speech_started_at = time.perf_counter()
            conv.speech_ended_at = None  # a new utterance: the old end time no longer applies
            turn_taker.on_speech_start()  # first: a re-open cancels the turn, so barge-in has nothing to do
            barge_in.on_speech_start()

        def on_speech_end(self) -> None:
            conv.speech_ended_at = time.perf_counter()
            barge_in.on_speech_end()
            turn_taker.on_speech_end()

        async def on_partial(self, text: str) -> None:
            turn_taker.on_partial(text)
            await send("transcript_partial", {"text": text})

        async def on_final(self, text: str) -> None:
            nonlocal held_stt_ms, last_final_at
            last_final_at = time.perf_counter()
            ended = conv.speech_ended_at  # None if STT sent the final before its speech-end event
            conv.speech_ended_at = None
            held_stt_ms = round((time.perf_counter() - ended) * 1000, 1) if ended else None
            turn_taker.on_final(text)  # commit_turn runs once the speaker is done; an "okay" over the answer is dropped

        async def on_error(self, message: str) -> None:
            await send("error", {"message": f"STT error: {message}"})

        def on_session_end(self, audio_seconds: float | None) -> None:
            # its own line, not a turn: the billed seconds belong to the whole STT socket
            append_turn_log({"type": "stt_session", "session_id": session_id, "stt_audio_s": audio_seconds,
                             "created_at": time.time()})

    stt = create_stt(_Handlers())

    # -------------------------------------------------------------------------
    # Receive loop — raw PCM audio from AudioWorklet, and JSON text from the page
    # -------------------------------------------------------------------------
    try:
        while True:
            msg = await ws.receive()

            if "bytes" in msg and msg["bytes"]:
                # Raw PCM from AudioWorklet → STT handles base64-encoding + queuing
                stt.send_audio(msg["bytes"])
            elif msg.get("text"):
                on_client_message(msg["text"])

    except Exception:
        pass  # client disconnected or WS error

    finally:
        barge_in.dispose()
        turn_taker.dispose()
        stt.close()
        interrupt_turn(conv)
        print("[server] Client disconnected")
