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


def extract_sentences(buffer: str) -> dict:
    """
    Drain the buffer into a list of complete sentences, returning the leftover.

    Returns {"sentences": list[str], "remaining": str}.
    """
    sentences: list[str] = []
    remaining = buffer

    while True:
        result = extract_next_sentence(remaining)
        if result is None:
            break
        sentences.append(result["sentence"])
        remaining = result["remaining"]

    return {"sentences": [s for s in sentences if s], "remaining": remaining}
