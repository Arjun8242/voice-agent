"""tts.py: Stream text-to-speech audio from Sarvam AI.

Corresponds to src/providers/tts.ts.
"""

from asyncio import timeout
import asyncio
from collections.abc import Awaitable, Callable
import httpx

try:
    from config import (
        SARVAM_TTS_URL,
        SARVAM_API_KEY,
        TTS_LANGUAGE,
        TTS_MODEL,
        TTS_SPEAKER,
        TTS_OUTPUT_FORMAT,
    )
except (ImportError, ModuleNotFoundError):
    from backend.config import (
        SARVAM_TTS_URL,
        SARVAM_API_KEY,
        TTS_LANGUAGE,
        TTS_MODEL,
        TTS_SPEAKER,
        TTS_OUTPUT_FORMAT,
    )


def create_tts_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5),
        limits=httpx.Limits(keepalive_expiry=60)
    )


async def warm_tts(client: httpx.AsyncClient):
    """Warm the TTS client with a test request."""
    async def _discard(_: bytes) -> None:
        pass

    try:
        await stream_tts("Hi.", asyncio.Event(), _discard, client)
    except Exception as err:
        print(f"[TTS] warm-up failed: {err}")

async def stream_tts(
    text: str,
    interrupt_event: asyncio.Event,
    on_chunk: Callable[[bytes], Awaitable[None]],
    client: httpx.AsyncClient,
) -> None:
    """Generate speech and pass each audio chunk to an async callback."""

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
    }

    payload = {
        "text": text,
        "language_code": TTS_LANGUAGE,
        "model": TTS_MODEL,
        "speaker": TTS_SPEAKER,
        "output_audio_codec": TTS_OUTPUT_FORMAT,
    }

    async with client.stream(
        "POST",
        SARVAM_TTS_URL,
        headers=headers,
        json=payload,
    ) as response:

        if not response.is_success:
            body = (await response.aread()).decode(
                "utf-8", errors="replace"
            )
            raise RuntimeError(
                f"TTS failed: {response.status_code}: {body[:100]}"
            )

        async for chunk in response.aiter_bytes():
            if interrupt_event.is_set():
                print("TTS stream interrupted")
                return

            if chunk:
                await on_chunk(chunk)
