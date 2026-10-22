"""retriever.py: Convenience alias for local_retriever.py."""
from .local_retriever import (
    init_retriever,
    retrieve,
    MIN_SCORE,
    DEFAULT_MIN_SCORE,
    MODEL,
    QUERY_PREFIX,
    MAX_CHAR_CAP,
    CACHE_MAX,
)

__all__ = [
    "init_retriever",
    "retrieve",
    "MIN_SCORE",
    "DEFAULT_MIN_SCORE",
    "MODEL",
    "QUERY_PREFIX",
    "MAX_CHAR_CAP",
    "CACHE_MAX",
]
