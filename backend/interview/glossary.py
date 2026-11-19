"""glossary.py: correct tech names that speech-to-text split or mis-heard, before any LLM sees the answer.

The glossary is every tech name from the candidate's resume and job description (phase 3 fills it).
"post gress" -> "PostgreSQL", "type script" -> "TypeScript". Pure code: no LLM call, no Sarvam call.

Rules a reader would not guess:
- Words are compared squashed: lower case, letters, digits, + and # only ("Node.js" -> "nodejs").
- A single word is replaced only on an exact squashed match (a casing fix). Fuzzy matching is for
  two or three words only: one fuzzy word would turn "nodes" into "Node.js" or "reacts" into "React".
- A fuzzy match must also start with the term's first letter and be within MAX_LENGTH_GAP letters of
  it, so a run never swallows the word before the term ("in type script" -> "in TypeScript").
- Terms shorter than MIN_TERM_CHARS are never matched: "Go" or "C" would hit ordinary words.
- A run of words never crosses punctuation, and an exact match beats a fuzzy one.
- Only real corrections are reported (not casing), so the report can show "heard X, read as Y".
- Anything the glossary misses is left alone: the interviewer and the evaluator read it by meaning.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

MIN_TERM_CHARS = 4
MATCH_RATIO = 0.8
MAX_LENGTH_GAP = 2
MAX_WORDS = 3


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", text.lower())


def runs(words: list[str], start: int) -> list[tuple[int, str]]:
    """The runs of 1 to MAX_WORDS words from start, longest first, as (word count, squashed text).
    A run never crosses punctuation: "fast api, in" is not one run."""
    found = []
    for count in range(1, min(MAX_WORDS, len(words) - start) + 1):
        found.append((count, squash(" ".join(words[start:start + count]))))
        if re.search(r"[^\w+#]$", words[start + count - 1]):
            break
    return [(count, heard) for count, heard in reversed(found) if len(heard) >= MIN_TERM_CHARS]


def find_term(words: list[str], start: int, terms: dict[str, str]) -> tuple[int, str] | None:
    """The run of words from start that names a glossary term: (word count, term), or None.
    An exact match of any length wins over a fuzzy one, so "fast api" is not read as "fast api in"."""
    candidates = runs(words, start)
    for count, heard in candidates:
        if heard in terms:
            return count, terms[heard]
    for count, heard in candidates:
        for key, term in terms.items():
            if count > 1 and is_close(heard, key):
                return count, term
    return None


def is_close(heard: str, key: str) -> bool:
    if heard[0] != key[0] or abs(len(heard) - len(key)) > MAX_LENGTH_GAP:
        return False
    return SequenceMatcher(None, heard, key).ratio() >= MATCH_RATIO


def normalize_terms(text: str, glossary: list[str]) -> tuple[str, dict[str, str]]:
    """The text with glossary terms put back, and the corrections made (heard -> term)."""
    terms = {squash(term): term for term in glossary if len(squash(term)) >= MIN_TERM_CHARS}
    if not terms:
        return text, {}
    words, out, corrections, i = text.split(), [], {}, 0
    while i < len(words):
        found = find_term(words, i, terms)
        if found is None:
            out.append(words[i])
            i += 1
            continue
        count, term = found
        heard = " ".join(words[i:i + count])
        trailing = re.search(r"[^\w+#]*$", heard).group()  # keep "post gress." ending its sentence
        core = heard[:len(heard) - len(trailing)]
        if core.lower() != term.lower():
            corrections[core] = term
        out.append(term + trailing)
        i += count
    return " ".join(out), corrections
