"""
sentence.py — split a streaming text buffer into complete sentences.

Corresponds to src/pipeline/sentence.ts.
"""

import re


def extract_next_sentence(buffer: str) -> dict | None:
    """
    Find the first sentence end and split there.

    Returns {"sentence": str, "remaining": str}, or None if no sentence end found.
    """
    match = re.search(r"[.!?]+[\"')\]]*(?=\s)", buffer)
    if match is None:
        return None
    return {
        "sentence": buffer[: match.end()].strip(),
        "remaining": buffer[match.end() :].lstrip(), #removes the leading whitespace from remaining text
    }

