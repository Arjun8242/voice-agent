"""llm.py: Gemini-backed answer generation for Harbor & Pine.

Corresponds to src/services/rag/llm.ts.
"""

from typing import AsyncIterator, TypedDict

from google import genai
from google.genai import types

try:
    from config import GEMINI_API_KEY, GEMINI_MODEL
except (ImportError, ModuleNotFoundError):
    from backend.config import GEMINI_API_KEY, GEMINI_MODEL


FALLBACK_ANSWER = (
    "I don't have that information about Arjun. "
    "I can only share what's in his verified knowledge base."
)


class Turn(TypedDict):
    role: str
    text: str


class AnswerGenerationResult(TypedDict):
    answer: str
    query: str
    retrievedChunks: list[dict]


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client

    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client

async def warm_llm() -> None:
    try:
        await _get_client().aio.models.generate_content(
            model=GEMINI_MODEL,
            contents="Hi",
            config=types.GenerateContentConfig(max_output_tokens=5),
        )
    except Exception as err:
        print(f"[llm] warm-up failed: {err}")


def build_system_instruction() -> str:
    return (
        "You are the phone support assistant for Harbor & Pine Living.\n\n"
        "Answer ONLY from the provided context. Never use outside knowledge or "
        "invent policies, prices, times, specifications, guarantees, or exceptions. "
        'Keep any limits the context states (estimates, "not guaranteed", '
        '"subject to review").\n'
        f'If the context does not cover the question, reply with exactly: "{FALLBACK_ANSWER}"\n'
        "If the context says a human must handle something, say you cannot do it "
        "yourself but can start a request. Never say a refund, cancellation, change, "
        "or exception has been completed or promised.\n"
        "Speak naturally in 1 to 3 short sentences of plain text, direct answer first. "
        "No lists, headings, or Markdown. Do not mention the context, sources, "
        "or how you work."
    )


def format_retrieved_context(rag: dict) -> str:
    chunks = rag.get("chunks") or []

    if not chunks:
        return "No relevant Harbor & Pine information was found for this query."

    parts = []

    for chunk in chunks:
        metadata = chunk["metadata"]
        chunk_id = metadata.get("id") or "Unknown"
        title = metadata.get("section") or "Untitled"

        parts.append(f"[{chunk_id}] {title}\n{chunk['text']}")

    return "\n\n".join(parts)


def _format_history(history: list[Turn]) -> str:
    if not history:
        return ""

    lines = [
        f"{'Customer' if turn['role'] == 'user' else 'Assistant'}: {turn['text']}"
        for turn in history
    ]

    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


def _build_prompt(
    query: str,
    rag: dict,
    history: list[Turn],
) -> str:
    context = format_retrieved_context(rag)
    history_text = _format_history(history)

    return (
        f"{history_text}Retrieved Harbor & Pine information:\n"
        f"{context}\n\n"
        f"Customer question: {query}\n\n"
        "Generate the customer-facing answer."
    )


def _get_retrieved_chunks(rag: dict) -> list[dict]:
    return [
        {
            "id": chunk["metadata"].get("id") or "Unknown",
            "score": chunk["score"],
        }
        for chunk in (rag.get("chunks") or [])
    ]

#this is for rag (mic -> STT -> answer_turn() -> retrieve() -> stream_answer() -> TTS -> speaker)
async def stream_answer(
    query: str,
    rag: dict,
    history: list[Turn] | None = None,
) -> AsyncIterator[str]:
    """Yield answer text incrementally from Gemini."""

    history = history or []

    # Match non-streaming behavior when retrieval finds no chunks.
    if not rag.get("chunks"):
        yield FALLBACK_ANSWER
        return

    stream = await _get_client().aio.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=_build_prompt(query, rag, history),
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(),
            temperature=0.3,
            max_output_tokens=150,
        ),
    )

    async for chunk in stream:
        token = chunk.text or ""

        if token:
            yield token


async def generate_answer(
    query: str,
    rag: dict,
    history: list[Turn] | None = None,
) -> AnswerGenerationResult:
    """Generate a complete answer and its retrieval metadata."""

    history = history or []
    retrieved_chunks = _get_retrieved_chunks(rag)

    if not retrieved_chunks:
        return {
            "answer": FALLBACK_ANSWER,
            "query": query,
            "retrievedChunks": [],
        }

    try:
        response = await _get_client().aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=_build_prompt(query, rag, history),
            config=types.GenerateContentConfig(
                system_instruction=build_system_instruction(),
                temperature=0.3,
                max_output_tokens=150,
            ),
        )

        answer = (response.text or "").strip()

        return {
            "answer": answer or FALLBACK_ANSWER,
            "query": query,
            "retrievedChunks": retrieved_chunks,
        }

    except Exception as e:
        print(f"[llm] generation failed: {e}")

        return {
            "answer": FALLBACK_ANSWER,
            "query": query,
            "retrievedChunks": retrieved_chunks,
        }


async def stream_text(prompt: str, system_instruction: str) -> AsyncIterator[str]:
    """Yield text pieces from Gemini as they arrive. Used by the graph's agent node."""
    stream = await _get_client().aio.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=150,
        ),
    )
    async for chunk in stream:
        token = chunk.text or ""
        if token:
            yield token
