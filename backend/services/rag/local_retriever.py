"""local_retriever.py: Local embedding-based retrieval using sentence-transformers.

Corresponds to src/services/rag/local_retriever.ts.
"""
import json
import os
import time
from pathlib import Path

from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_CHAR_CAP = 3000
CACHE_MAX = 200

DEFAULT_MIN_SCORE = 0.5
_env_min = float(os.environ.get("RAG_MIN_SCORE", "0"))
MIN_SCORE = _env_min if 0 < _env_min < 1 else DEFAULT_MIN_SCORE

_model: SentenceTransformer | None = None
_items: list[dict] = []   # each: {id, title, text, source, vec}
_query_cache: dict[str, list[float]] = {}   # normalized query -> embedding


def _normalize(t: str) -> str:
    import re
    return re.sub(r"[?.!,]+$", "", re.sub(r"\s+", " ", t.strip().lower()))


def _embed_sync(text: str) -> list[float]:
    assert _model is not None
    vec = _model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _embed_query_sync(query: str) -> list[float]:
    key = _normalize(query)
    if key not in _query_cache:
        vec = _embed_sync(QUERY_PREFIX + query)
        _query_cache[key] = vec
        if len(_query_cache) > CACHE_MAX:  # FIFO eviction
            _query_cache.pop(next(iter(_query_cache)))
    return _query_cache[key]


def _find_chunks_file() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "data" / "KB_chunks" / "harbor_pine_chunks.json",
        Path("data") / "KB_chunks" / "harbor_pine_chunks.json",
        Path("../data") / "KB_chunks" / "harbor_pine_chunks.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


async def init_retriever(
    json_path: str | None = None,
) -> None:
    """Load model and pre-embed all chunks. Call once at startup."""
    import asyncio

    global _model, _items

    if json_path is None:
        json_path = str(_find_chunks_file())

    t0 = time.perf_counter()
    _model = await asyncio.to_thread(SentenceTransformer, MODEL)

    chunks = json.loads(Path(json_path).read_text(encoding="utf-8"))
    texts = [f"{c['title']}\n{c['content']}" for c in chunks]
    vecs = await asyncio.to_thread(_model.encode, texts, normalize_embeddings=True)

    _items = []
    for c, vec in zip(chunks, vecs):
        _items.append({
            "id": c["id"],
            "title": c["title"],
            "text": c["content"],
            "source": c.get("source"),
            "vec": vec.tolist(),
        })

    await asyncio.to_thread(_embed_query_sync, "warm up")
    elapsed = round((time.perf_counter() - t0) * 1000)
    print(f"[retriever] ready: {len(_items)} chunks, {elapsed} ms")


async def retrieve(query: str, top_k: int = 3) -> dict:
    """Return top matching chunks for query. Raises if init_retriever not called."""
    import asyncio

    if _model is None:
        raise RuntimeError("Call init_retriever() before retrieve()")

    t0 = time.perf_counter()
    q = await asyncio.to_thread(_embed_query_sync, query)
    t1 = time.perf_counter()

    # vectors are normalized — dot product == cosine similarity
    scored = []
    for it in _items:
        s = sum(a * b for a, b in zip(q, it["vec"]))
        scored.append((it, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    scored = [(it, s) for it, s in scored if s >= MIN_SCORE][:top_k]

    t2 = time.perf_counter()

    chunks = []
    combined = ""
    for it, s in scored:
        if len(combined) + len(it["text"]) > MAX_CHAR_CAP:
            continue
        chunks.append({
            "text": it["text"],
            "score": s,
            "metadata": {"source": it["source"], "section": it["title"], "id": it["id"]},
        })
        combined += f"[Source: {it['title']}]\n{it['text']}\n\n"

    def r(n):
        return round(n * 1000, 2)

    return {
        "query": query,
        "chunks": chunks,
        "combinedContext": combined.strip(),
        "latencyMs": r(t2 - t0),
        "embedLatencyMs": r(t1 - t0),
        "searchLatencyMs": r(t2 - t1),
    }
