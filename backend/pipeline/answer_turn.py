"""answer_turn.py: Orchestrates RAG retrieval → LLM streaming → TTS per turn.

Corresponds to src/pipeline/answerTurn.ts.
"""

import asyncio
import struct
import time
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from rag.llm import FALLBACK_ANSWER, stream_answer
    from rag.retriever import retrieve
    from pipeline.sentence import extract_next_sentence
    from providers.tts import stream_tts
except (ImportError, ModuleNotFoundError):
    from backend.rag.llm import FALLBACK_ANSWER, stream_answer
    from backend.rag.retriever import retrieve
    from backend.pipeline.sentence import extract_next_sentence
    from backend.providers.tts import stream_tts

Send = Callable[..., Awaitable[None]]


async def speak_sentence(
    send: Send,
    sentence_id: int,
    text: str,
    interrupt_event: asyncio.Event,
    first_audio: dict,
    elapsed: Callable[[], int],
    on_audio: Callable[[], None],
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

        await stream_tts(text, interrupt_event, on_chunk)

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


async def answer_turn(
    query: str,
    state: Any,
    send: Send,
    interrupt_event: asyncio.Event,
) -> None:
    """RAG → LLM stream → TTS. Cancellable via task cancellation or interrupt_event."""

    t0 = time.perf_counter()
    elapsed = lambda: round((time.perf_counter() - t0) * 1000)

    first_audio: dict = {"sent_ms": None}
    sentence_buffer = ""
    answer = ""
    first_token = False
    cancelled = False

    def speak(tg: asyncio.TaskGroup, sentence: str) -> None:
        sid = state.sentence_counter
        state.sentence_counter += 1
        tg.create_task(speak_sentence(
            send, sid, sentence, interrupt_event,
            first_audio, elapsed,
            lambda: setattr(state, "agent_speaking", True),
        ))

    try:
        async with asyncio.TaskGroup() as tg:
            try:
                rag = await retrieve(query, top_k=3)

                await send("metric", {
                    "stage": "rag_complete",
                    "ragLatencyMs": rag["latencyMs"],
                })

                async for token in stream_answer(query, rag, state.history):
                    if not token:
                        continue

                    if not first_token:
                        first_token = True
                        await send("metric", {
                            "stage": "gemini_first_token",
                            "ttftMs": elapsed(),
                        })

                    answer += token
                    await send("assistant_text", {"text": token})

                    sentence_buffer += token
                    nxt = extract_next_sentence(sentence_buffer)
                    while nxt:
                        speak(tg, nxt["sentence"])
                        sentence_buffer = nxt["remaining"]
                        nxt = extract_next_sentence(sentence_buffer)

                if sentence_buffer.strip():
                    speak(tg, sentence_buffer.strip())

            finally:
                if answer.strip():
                    state.history.append({"role": "user", "text": query})
                    state.history.append({"role": "assistant", "text": answer.strip()})
                    if len(state.history) > 6:
                        state.history = state.history[-6:]

    except asyncio.CancelledError:
        cancelled = True
        raise

    except Exception as err:
        print(f"[answerTurn] {err}")
        # If nothing was spoken yet, deliver the fallback sentence
        if first_audio["sent_ms"] is None and not answer:
            try:
                async with asyncio.TaskGroup() as tg:
                    speak(tg, FALLBACK_ANSWER)
            except Exception:
                pass

    if not cancelled:
        state.agent_speaking = False
        await send("done", {"totalMs": elapsed()})
