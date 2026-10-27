"""Embedding-based retrieval for the LangGraph voice-agent branch.

Loads precomputed document vectors from data/kb_index.json.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from pathlib import Path

from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = (
    "Represent this sentence for searching relevant passages: "
)
MODEL_DIM = 384
CACHE_MAX = 200

DEFAULT_MIN_SCORE = 0.5
_env_min = float(os.environ.get("RAG_MIN_SCORE", "0"))
MIN_SCORE = (
    _env_min if 0 < _env_min < 1 else DEFAULT_MIN_SCORE
)

_model: SentenceTransformer | None = None
_items: list[dict] = []
_query_cache: dict[str, list[float]] = {}


def _normalize(text: str) -> str:
    """Normalize queries for embedding-cache lookup."""
    return re.sub(
        r"[?.!,]+$",
        "",
        re.sub(r"\s+", " ", text.strip().lower()),
    )


def _validate_vector(vector: object, index: int) -> list[float]:
    """Reject invalid vectors before they enter similarity search."""
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"KB index vector {index} contains non-numeric values"
        ) from exc

    if len(values) != MODEL_DIM:
        raise ValueError(
            f"KB index vector {index} has dimension {len(values)}; "
            f"expected {MODEL_DIM}"
        )

    if not all(math.isfinite(value) for value in values):
        raise ValueError(
            f"KB index vector {index} contains NaN or infinity"
        )

    norm = math.sqrt(math.fsum(value * value for value in values))

    if not math.isfinite(norm) or abs(norm - 1.0) > 1e-3:
        raise ValueError(
            f"KB index vector {index} is not normalized "
            f"(L2 norm={norm:.6f})"
        )

    return values


def _embed_sync(text: str) -> list[float]:
    """Embed one text using the loaded model."""
    if _model is None:
        raise RuntimeError("Retriever model is not initialized")

    vector = _model.encode(text, normalize_embeddings=True)
    return _validate_vector(vector.tolist(), -1)


def _embed_query_sync(query: str) -> list[float]:
    """Embed a query, reusing recent normalized-query results."""
    key = _normalize(query)

    if key not in _query_cache:
        _query_cache[key] = _embed_sync(QUERY_PREFIX + query)

        if len(_query_cache) > CACHE_MAX:
            _query_cache.pop(next(iter(_query_cache)))

    return _query_cache[key]


def _find_chunks_file() -> Path:
    """Find the knowledge base index file."""
    repo_root = Path(__file__).resolve().parents[2]

    candidates = [
        repo_root / "data" / "kb_index.json",
        Path("data") / "kb_index.json",
        Path("../data") / "kb_index.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return the canonical path so a missing-file error is meaningful.
    return candidates[0]


def _validate_records(raw: object) -> list[dict]:
    """Validate the common JSON-list schema before loading the model."""
    if not isinstance(raw, list):
        raise ValueError("KB index must be a JSON list of chunk records")

    for index, chunk in enumerate(raw):
        if not isinstance(chunk, dict):
            raise ValueError(
                f"KB index record {index} is not a JSON object"
            )

        for field in ("id", "title", "content"):
            if not isinstance(chunk.get(field), str):
                raise ValueError(
                    f"KB index chunk {index} is missing "
                    f"a string '{field}' field"
                )

    has_vectors = ["vec" in chunk for chunk in raw]

    if any(has_vectors) and not all(has_vectors):
        raise ValueError(
            "KB index mixes records with and without stored vectors"
        )

    return raw


async def init_retriever(
    json_path: str | None = None,
) -> None:
    """Load the query model and index; reuse stored document vectors."""
    global _model, _items

    path = Path(json_path) if json_path is not None else _find_chunks_file()
    started = time.perf_counter()

    # Read the index before loading the embedding model.
    raw = json.loads(path.read_text(encoding="utf-8"))
    chunks = _validate_records(raw)

    uses_stored_vectors = bool(chunks) and all(
        "vec" in chunk for chunk in chunks
    )

    # A stored-vector index must identify the model and dimensions.
    if uses_stored_vectors:
        models = {chunk.get("embedding_model") for chunk in chunks}
        dimensions = {chunk.get("dim") for chunk in chunks}
        versions = {chunk.get("kb_version") for chunk in chunks}

        if models != {MODEL}:
            raise ValueError(
                f"Index model {models!r} does not match runtime model {MODEL!r}"
            )

        if dimensions != {MODEL_DIM}:
            raise ValueError(
                f"Index dimensions {dimensions!r} do not match {MODEL_DIM}"
            )

        if (
            len(versions) != 1
            or None in versions
            or "" in versions
        ):
            raise ValueError(
                "KB index has missing or inconsistent kb_version values"
            )

    _model = await asyncio.to_thread(SentenceTransformer, MODEL)

    if uses_stored_vectors:
        vectors = [
            _validate_vector(chunk["vec"], index)
            for index, chunk in enumerate(chunks)
        ]
        vector_source = "stored"
    else:
        # Backward compatibility with legacy text-only chunk lists.
        texts = [
            f"{chunk['title']}\n{chunk['content']}"
            for chunk in chunks
        ]

        if texts:
            matrix = await asyncio.to_thread(
                _model.encode,
                texts,
                normalize_embeddings=True,
            )
            vectors = [
                _validate_vector(row.tolist(), index)
                for index, row in enumerate(matrix)
            ]
        else:
            vectors = []

        vector_source = "computed (legacy index)"

    _items = [
        {
            "id": chunk["id"],
            "title": chunk["title"],
            "text": chunk["content"],
            "source": chunk.get("source"),
            "vec": vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    # Avoid retaining cached query vectors across reinitialization.
    _query_cache.clear()
    await asyncio.to_thread(_embed_query_sync, "warm up")

    elapsed_ms = round((time.perf_counter() - started) * 1000)

    print(
        f"[retriever] ready: {len(_items)} chunks, "
        f"{elapsed_ms} ms (document vectors: {vector_source})"
    )


async def retrieve(
    query: str,
    top_k: int = 3,
    topic: str | None = None,
) -> dict:
    """Return the highest-scoring chunks for a query."""
    if _model is None:
        raise RuntimeError(
            "Call init_retriever() before retrieve()"
        )

    if top_k < 0:
        raise ValueError("top_k must be non-negative")

    search_query = f"[{topic}] {query}" if topic else query

    started = time.perf_counter()
    query_vector = await asyncio.to_thread(
        _embed_query_sync,
        search_query,
    )
    embedded_at = time.perf_counter()

    # Normalized vectors allow dot product to represent cosine similarity.
    scored = []

    for item in _items:
        score = sum(
            a * b for a, b in zip(query_vector, item["vec"])
        )
        scored.append((item, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)

    scored = [
        (item, score)
        for item, score in scored
        if score >= MIN_SCORE
    ][:top_k]

    searched_at = time.perf_counter()

    result_chunks = []
    combined_context = ""

    for item, score in scored:
        result_chunks.append(
            {
                "text": item["text"],
                "score": score,
                "metadata": {
                    "source": item["source"],
                    "section": item["title"],
                    "id": item["id"],
                },
            }
        )

        combined_context += (
            f"[Source: {item['title']}]\n"
            f"{item['text']}\n\n"
        )

    to_ms = lambda seconds: round(seconds * 1000, 2)

    return {
        "query": query,
        "chunks": result_chunks,
        "combinedContext": combined_context.strip(),
        "latencyMs": to_ms(searched_at - started),
        "embedLatencyMs": to_ms(embedded_at - started),
        "searchLatencyMs": to_ms(searched_at - embedded_at),
    }