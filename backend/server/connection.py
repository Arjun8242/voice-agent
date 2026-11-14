"""connection.py: Per-connection handler — wires barge-in, STT, and answer turns.
"""
import re
import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo
from fastapi import WebSocket
import httpx

from backend.interview.personas import NEUTRAL, Persona, get_persona
from backend.observability.timings import append_turn_log
from backend.pipeline.turn_taking import INTERVIEW_POLICY, TurnTaker
from backend.providers.stt import stt_url

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
END_REQUEST = "Let's end the interview."  # what the End button means; interview/intents.py reads it as "end"
SESSION_ID_RE = re.compile(r"[0-9a-f]{32}")

def valid_timezone(name: object) -> str:
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return DEFAULT_TIMEZONE


async def handle_connection(ws: WebSocket, tts_client: httpx.AsyncClient, graph: Any, executor: Any = None,
                            interview_graph: Any = None, evaluator: Callable[[list], Awaitable[Any]] | None = None) -> None:
    """Handle one WebSocket connection from accept() to disconnect.

    graph is the compiled agent graph. The connection id is its thread id, so the
    checkpointer keeps the conversation history per connection.
    executor is the BookingExecutor (booking/execute.py), or None while booking is disabled.
    interview_graph is the mock-interview graph (graph/interview/); a start_interview message switches
    the connection to it for good. None disables interviews.
    evaluator(answers) -> Report | None writes the end-of-interview report (interview/evaluate.py).
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
    interviewing = False  # set once by start_interview; the connection never switches back
    interview_ended = False  # set by the End button: no more nudges
    nudge_turn = 0  # turn id of the last nudge: its audio ending must not restart the silence clock
    report_task: asyncio.Task | None = None  # the report, started once when the interview finishes
    persona: Persona = NEUTRAL  # the interviewer's rules and voice, while interviewing

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
    def launch_turn(text: str, ui_action: dict | None = None, nudge: int | None = None) -> None:
        nonlocal interrupt_event, turn_id, turn_timings
        interrupt_event = asyncio.Event()   # fresh per turn
        turn_id += 1
        timings = None  # a click or a nudge has no speech to time, and must not skew the latency report
        if ui_action is None and nudge is None:
            hold_ms = round((time.perf_counter() - last_final_at) * 1000, 1) if last_final_at else None
            timings = {"turn_id": turn_id, "mode": "interview" if interviewing else "recruiter",
                       "stt_ms": held_stt_ms, "hold_ms": hold_ms,
                       "turn_decision": turn_taker.last_decision, "segments_merged": turn_taker.last_segments}
        turn_timings = timings

        task = asyncio.create_task(_run_turn(text, conv, with_turn_id(send, turn_id), interrupt_event, timings, ui_action, nudge))
        start_turn(conv, task)

    async def _run_turn(
        text: str,
        conv: Conversation,
        send,
        ev: asyncio.Event,
        timings: dict | None,
        ui_action: dict | None,
        nudge: int | None,
    ) -> None:
        try:
            waited = time.perf_counter()
            heard = await take_heard(conv)  # what the visitor heard of a cut-off answer, if the last turn was one
            if timings is not None:
                timings["wait_ms"] = round((time.perf_counter() - waited) * 1000, 1)
            await voice_turn(text, conv, send, ev, tts_client, interview_graph if interviewing else graph, session_id, heard,
                             timings, visitor_timezone=visitor_timezone, ui_action=ui_action,
                             on_booking_execute=start_booking_execute,
                             persona=persona.name if interviewing else "", speaker=persona.voice if interviewing else "",
                             nudge=nudge)
            if interviewing:
                await start_report_if_finished()
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

    # -------------------------------------------------------------------------
    # The report — owned by the connection, like booking calls, so a barge-in cannot cancel it.
    # interview_report has no turnId: the browser never drops it as stale.
    # -------------------------------------------------------------------------
    async def start_report_if_finished() -> None:
        """After an interview turn: if the graph says the interview ended (End, time cap, last topic or a
        spoken "end"), write the report from its recorded answers. Only once per connection."""
        nonlocal report_task
        if report_task is not None or evaluator is None:
            return
        values = (await interview_graph.aget_state({"configurable": {"thread_id": session_id}})).values
        if not values.get("finished") or report_task is not None:  # re-checked: another turn may have started it
            return
        report_task = asyncio.get_running_loop().create_task(send_report(list(values.get("answers") or [])))

    async def send_report(answers: list) -> None:
        await send("interview_report", {"status": "pending"})
        try:
            report = await evaluator(answers)
        except Exception as err:  # a bug in the report must not end silently; CancelledError passes through
            print(f"[report] {type(err).__name__}: {err}")
            report = None
        if report is None:
            await send("interview_report", {"status": "failed"})
            return
        await send("interview_report", {"status": "ready", "report": report.model_dump()})

    def speak_nudge(index: int) -> None:
        """The candidate stayed silent after a question (TurnTaker's nudge clock): say the persona's line."""
        nonlocal nudge_turn
        if not interviewing or interview_ended or index >= len(persona.nudges):
            return  # strict has no nudges; after End there is nothing to nudge about
        launch_turn("", nudge=index)
        nudge_turn = turn_id

    turn_taker = TurnTaker(commit=commit_turn, is_answering=lambda: is_answering(conv), reopen_turn=reopen_turn,
                           on_state=send_turn_state, on_nudge=speak_nudge)

    # -------------------------------------------------------------------------
    # Interview mode
    # -------------------------------------------------------------------------
    def start_interview(requested_persona: object) -> None:
        """Switch to the interview graph, its hold times and STT silence, then ask the opening question.

        Sent by a click in the page, so the browser lets the interviewer's audio play. A repeat is ignored.
        """
        nonlocal interviewing, persona
        if interviewing or interview_graph is None:
            return
        interviewing = True
        persona = get_persona(requested_persona if isinstance(requested_persona, str) else None)
        turn_taker.policy = INTERVIEW_POLICY
        # shortcut: the STT socket reads its URL when it opens, so speech before Start keeps 500 ms; the page starts the mic after Start
        stt.url = stt_url("interview")
        turn_taker.drop_pending()
        if is_answering(conv):
            do_interrupt()
        launch_turn("")  # an empty turn asks the interview graph for its opening (or, on a resume, the last question)

    def end_interview() -> None:
        """The End button: the same turn as saying "let's end the interview", so the graph speaks the closing line."""
        nonlocal interview_ended
        if not interviewing:
            return
        interview_ended = True
        turn_taker.drop_pending()
        if is_answering(conv):
            do_interrupt()
        launch_turn(END_REQUEST)

    # -------------------------------------------------------------------------
    # Messages from the browser (text frames)
    # -------------------------------------------------------------------------
    def on_client_message(raw: str) -> None:
        """playback_progress: the sentence that was playing when the answer was cut off.
        playback_ended: the answer's audio finished, so speech from now on is not a barge-in.
        In an interview, the end of a question (not of a nudge) also starts the silence clock for nudges.
        session_start: the first message of a page load. Carries the id the browser kept (so a refresh
        continues the same graph thread) and the visitor's timezone.
        ui_action: a click on a booking card, {action, payload}. It runs as a turn of its own through the
        graph's booking_gate; the gate checks every field, so only the shape is checked here. Ignored in an
        interview: there are no cards, and an empty turn would ask the interviewer for its opening again.
        start_interview: {persona}, the Start click in the page. See start_interview above.
        end_interview: the End click. See end_interview above."""
        nonlocal session_id, visitor_timezone
        try:
            data = json.loads(raw)
        except ValueError:
            return  # not JSON: ignore it, do not drop the connection
        if isinstance(data, dict) and data.get("type") == "playback_progress":
            record_report(conv, data.get("turnId"), data.get("lastSentenceId"))
        elif isinstance(data, dict) and data.get("type") == "playback_ended" and data.get("turnId") == turn_id:
            conv.agent_speaking = False  # an older turn's ended message must not clear a newer turn's audio
            if interviewing and turn_id != nudge_turn and not interview_ended:
                turn_taker.on_question_finished()  # the question was heard in full: the silence clock starts
        elif isinstance(data, dict) and data.get("type") == "session_start":
            old = data.get("sessionId")
            if isinstance(old, str) and SESSION_ID_RE.fullmatch(old):  # only ids we could have made: it becomes a thread id
                session_id = old
            visitor_timezone = valid_timezone(data.get("timezone"))
            asyncio.get_running_loop().create_task(send("session", {"sessionId": session_id}))  # the browser stores this
        elif isinstance(data, dict) and data.get("type") == "start_interview":
            start_interview(data.get("persona"))
        elif isinstance(data, dict) and data.get("type") == "end_interview":
            end_interview()
        elif isinstance(data, dict) and data.get("type") == "ui_action" and not interviewing:
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
        if report_task is not None:
            report_task.cancel()  # nobody is left to read it: stop spending tokens on it
        stt.close()
        interrupt_turn(conv)
        print("[server] Client disconnected")
