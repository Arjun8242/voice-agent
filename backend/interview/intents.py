"""intents.py: what a candidate's turn is asking for, decided by fixed phrase rules before any LLM call.

repeat    "can you repeat that"    -> the graph replays the last question; no LLM call
hint      "can I get a hint"       -> one LLM call in hint mode
rephrase  "what do you mean"       -> one LLM call in rephrase mode
skip      "I don't know", "skip"   -> move to the next topic
end       "let's end the interview" -> closing template
answer    anything else            -> graded as an answer

Rules a reader would not guess:
- A phrase counts only when it is the whole turn, give or take politeness ("sorry, could you repeat
  that please?"). "I don't know the exact number, but it's about 5 ms" is an answer, not a skip.
  A mixed turn ("I don't know, give me a hint") is an answer too: the interviewer model sees it.
- "I'm done" on its own is not "end": in an interview it means "I finished answering".
- Clarifications are never graded: the graph stores the intent with the turn (plan §4.1 C).
"""

from __future__ import annotations

import re
from typing import Literal

from backend.pipeline.turn_taking import normalize

Intent = Literal["answer", "repeat", "hint", "rephrase", "skip", "end"]

# Words that may surround a request without changing it. Stripped from both ends only.
POLITENESS = {"sorry", "please", "um", "uh", "hmm", "okay", "ok", "so", "actually", "excuse", "me", "yeah", "well"}

PATTERNS: list[tuple[Intent, str]] = [
    ("end", r"(?:can we |let's |let us |i want to |i'd like to |i would like to )?(?:end|stop|finish) (?:the|this) interview"
            r"|i'm done with (?:the|this) interview"),
    ("repeat", r"(?:can|could|would) you (?:repeat|say) (?:that|it|the question)(?: again)?"
               r"|repeat(?: that| the question| it)?(?: again)?|say (?:that|it) again|pardon|come again"
               r"|what was the question|what did you (?:say|ask)|i didn't (?:hear|catch) (?:that|it|you|the question)"),
    ("hint", r"(?:can|could|may) i (?:get|have) a hint|(?:give me|i need|any) (?:a )?hint|hint"),
    ("rephrase", r"what do you mean(?: by that)?|(?:can|could) you (?:clarify|rephrase|explain)(?: that| the question| it)?"
                 r"|clarify|rephrase(?: that| the question)?|which part"
                 r"|i (?:don't|didn't) (?:understand|get)(?: the question| that| it)?"),
    ("skip", r"i (?:don't|do not) know|no idea|(?:can we |let's |can i )?(?:skip|pass)(?: this one| this| that| it| the question)?"
             r"|next question|(?:can we |let's )?move on"),
]
COMPILED = [(intent, re.compile(pattern)) for intent, pattern in PATTERNS]


def strip_politeness(words: list[str]) -> list[str]:
    """Drop politeness words from both ends: ["sorry", "repeat", "that", "please"] -> ["repeat", "that"]."""
    start, end = 0, len(words)
    while start < end and words[start] in POLITENESS:
        start += 1
    while end > start and words[end - 1] in POLITENESS:
        end -= 1
    return words[start:end]


def classify_intent(text: str) -> Intent:
    """The intent of one committed candidate turn. "answer" unless the whole turn is a known request."""
    core = " ".join(strip_politeness(normalize(text).replace("do not", "don't").split()))
    for intent, pattern in COMPILED:
        if pattern.fullmatch(core):
            return intent
    return "answer"
