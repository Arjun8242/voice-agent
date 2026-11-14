"""voice_turn.py: one spoken turn = run the agent graph, stream its output to the browser and TTS.

Replaces answer_turn (retrieve -> stream_answer -> TTS). Retrieval, the model, the tool loop
and the conversation history now live in the graph (backend/graph); this file only turns the
graph's stream events into WebSocket messages and speech:

    token      -> assistant_text message, and the sentence splitter feeds TTS
    card       -> ui_card message (the tools node emits it as soon as the tools finish)
    retrieval  -> metric message (rag_complete)
    usage      -> added to the turn's token totals in the turn log (observability/usage.py)
    booking_execute -> on_booking_execute(event): the calendar call after a confirm, run outside the turn

The graph runs inside this coroutine with the async API and nothing is detached, so
cancelling the turn task (barge-in) also stops the graph. Never swallow CancelledError here.
"""

import asyncio
import httpx
import struct
import time
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from graph.nodes.agent import ERROR_REPLY
    from graph.runner import stream_turn
    from observability.timings import append_turn_log
    from pipeline.sentence import extract_next_sentence
    from providers.tts import stream_tts
except (ImportError, ModuleNotFoundError):
    from backend.graph.nodes.agent import ERROR_REPLY
    from backend.graph.runner import stream_turn
    from backend.observability.timings import append_turn_log
    from backend.pipeline.sentence import extract_next_sentence
    from backend.providers.tts import stream_tts

from backend.observability.usage import add_usage, empty_totals

Send = Callable[..., Awaitable[None]]


async def speak_sentence(
    send: Send,
    sentence_id: int,
    text: str,
    interrupt_event: asyncio.Event,
    first_audio: dict,
    elapsed: Callable[[], int],
    on_audio: Callable[[], None],
    tts_client: httpx.AsyncClient,
) -> None:
    """TTS one sentence. Always fires tts_end in finally."""
    id_buf = struct.pack("<I", sentence_id)
    produced_first = False

    try:
        async def on_chunk(mp3: bytes) -> None:
            nonlocal produced_first
            await send(id_buf + mp3)
            if first_audio["sent_ms"] is None:
                first_audio["sent_ms"] = elapsed()
                produced_first = True
                on_audio()

        await stream_tts(text, interrupt_event, on_chunk, tts_client)

    except asyncio.CancelledError:
        raise
    except Exception as err:
        print(f"[TTS] sentence {sentence_id}: {err}")

    finally:
        await send("tts_end", {
            "sentenceId": sentence_id,
            "isFirst": produced_first,
            "firstAudioLatencyMs": first_audio["sent_ms"] if produced_first else None,
        })


async def voice_turn(
    query: str,
    state: Any,
    send: Send,
    interrupt_event: asyncio.Event,
    tts_client: httpx.AsyncClient,
    graph: Any,
    session_id: str,
    interrupted_reply: str = "",
    timings: dict | None = None,
    visitor_timezone: str = "",
    ui_action: dict | None = None,
    on_booking_execute: Callable[[dict], None] | None = None,
) -> None:
    """Run one turn through the graph. Cancellable via task cancellation or interrupt_event.

    state is the connection's Conversation (sentence counter, agent_speaking flag, queued sentences).
    session_id is the graph's thread id, so the checkpointer keeps the history per connection.
    interrupted_reply is the part of the previous answer the visitor heard before cutting in ("" if none);
    the graph adds it to the history ahead of this question.
    timings: stages measured before this turn started (turn_id, stt_ms, wait_ms). When given, the
    turn's stage times are added and one line is written to the turn log (observability/timings.py).
    """

    t0 = time.perf_counter()
    elapsed = lambda: round((time.perf_counter() - t0) * 1000)

    first_audio: dict = {"sent_ms": None}
    sentence_buffer = ""
    first_token = False
    cancelled = False
    marks: dict = {"rag_ms": None, "first_token_ms": None, "first_sentence_ms": None}
    tools_used: list[str] = []
    tokens = empty_totals()

    def log_turn(interrupted: bool) -> None:
        """One line in the turn log. A cut-off turn keeps the times it reached; its total_ms is empty
        because it is not a real total, and cut_off_ms says when the visitor cut in."""
        if timings is None:
            return
        record = {**timings, **marks, **tokens, "session_id": session_id, "first_audio_ms": first_audio["sent_ms"],
                  "total_ms": None if interrupted else elapsed(), "interrupted": interrupted,
                  "cut_off_ms": elapsed() if interrupted else None, "tools": tools_used, "created_at": time.time()}
        parts = (record.get("stt_ms"), record.get("hold_ms", 0), record.get("wait_ms"), record["first_audio_ms"])
        record["speech_end_to_first_audio_ms"] = round(sum(parts), 1) if None not in parts else None
        append_turn_log(record)

    def speak(tg: asyncio.TaskGroup, sentence: str) -> None:
        if marks["first_sentence_ms"] is None:
            marks["first_sentence_ms"] = elapsed()
        sid = state.sentence_counter
        state.sentence_counter += 1
        state.sentences.append((sid, sentence))  # kept so a barge-in can tell which sentences were heard
        tg.create_task(speak_sentence(
            send, sid, sentence, interrupt_event,
            first_audio, elapsed,
            lambda: setattr(state, "agent_speaking", True),
            tts_client,
        ))

    try:
        async with asyncio.TaskGroup() as tg:
            async for mode, event in stream_turn(graph, session_id, query, interrupted_reply, visitor_timezone, ui_action):
                if mode == "values":  # state after each step: only the tool calls are needed here
                    tools_used = [c["name"] for c in event.get("tool_calls", [])]
                    continue

                kind = event.get("type")

                if kind == "token":
                    token = event["text"]
                    if not token:
                        continue

                    if not first_token:
                        first_token = True
                        marks["first_token_ms"] = elapsed()
                        await send("metric", {"stage": "llm_first_token", "ttftMs": elapsed()})

                    await send("assistant_text", {"text": token})

                    sentence_buffer += token
                    nxt = extract_next_sentence(sentence_buffer)
                    while nxt:
                        speak(tg, nxt["sentence"])
                        sentence_buffer = nxt["remaining"]
                        nxt = extract_next_sentence(sentence_buffer)

                elif kind == "card":
                    await send("ui_card", {"card": event["card"]})

                elif kind == "booking_execute" and on_booking_execute is not None:
                    on_booking_execute(event)  # the connection runs it as its own task: it must outlive this turn

                elif kind == "usage":
                    add_usage(tokens, event)

                elif kind == "retrieval":
                    marks["rag_ms"] = event["ms"]
                    await send("metric", {"stage": "rag_complete", "ragLatencyMs": event["ms"]})

            if sentence_buffer.strip():
                speak(tg, sentence_buffer.strip())

    except asyncio.CancelledError:
        cancelled = True
        log_turn(interrupted=True)  # plain file write, no await: safe while the task is being cancelled
        raise

    except Exception as err:
        print(f"[voiceTurn] {err}")
        # If nothing was spoken yet, say the error reply
        if first_audio["sent_ms"] is None and not first_token:
            try:
                async with asyncio.TaskGroup() as tg:
                    speak(tg, ERROR_REPLY)
            except Exception:
                pass

    if not cancelled:
        # agent_speaking stays True: the browser is usually still playing the audio, so the visitor
        # can still cut in. It is cleared by the browser's playback_ended or by the next turn.
        await send("done", {"totalMs": elapsed()})
        log_turn(interrupted=False)
