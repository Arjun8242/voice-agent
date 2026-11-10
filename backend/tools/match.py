"""Case-insensitive whole-word matching shared by the tools."""

import re


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def has_word(needle: str, text: str) -> bool:
    """True if needle appears in text as whole words: 'java' matches 'Java', not 'JavaScript'."""
    needle = norm(needle)
    return bool(needle) and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", norm(text)) is not None
