"""tag.py: the control tag the interviewer model writes before it speaks, and the stream buffer that hides it.

The model's reply starts with one tag, then the spoken text:

    [[decision=probe]]
    Right, the scheduler takes a lock. What happens if the worker holding it dies?

One streamed call carries both. A tool call would not work here: rag/llm.py yields tool calls only
after the whole stream ends (docs/interviewer-mode-plan.md §6.3).

Rules a reader would not guess:
- Tag text never reaches TTS. Until the tag is closed, the buffer holds the stream back; a reply that
  does not start with "[[" is all speech and flows through at once.
- A missing, unknown or broken tag means decision "next" (move on), and tag_ok is False so evals can
  count the failures. A broken tag is dropped up to its line end; if it never ends, nothing of it is spoken.
- Unknown keys inside a tag are ignored, so the prompt can add fields later without breaking parsing.
"""

from __future__ import annotations

import re

from backend.interview.personas import ALL_DECISIONS, Decision

FALLBACK_DECISION: Decision = "next"
MAX_TAG_CHARS = 120  # a tag longer than this is broken; stop holding the stream back
TAG = re.compile(r"\[\[(.*?)\]\]", re.S)


def parse_tag(body: str) -> Decision | None:
    """The decision inside a tag body ("decision=probe; extra=1"), or None if it is missing or unknown."""
    for field in body.split(";"):
        key, _, value = field.partition("=")
        if key.strip().lower() == "decision":
            decision = value.strip().lower()
            return decision if decision in ALL_DECISIONS else None
    return None


class TagBuffer:
    """Feed it the model's text pieces; it returns the part that may be spoken, with the tag removed.

    After the stream ends, call finish() for anything still held back, then read decision and tag_ok.
    """

    def __init__(self) -> None:
        self._held = ""
        self._resolved = False  # the tag was found, or there is none: everything from now on is speech
        self._strip_leading = False  # speech has not started yet, so whitespace is still dropped
        self.tag_ok = False
        self.decision: Decision = FALLBACK_DECISION

    def feed(self, piece: str) -> str:
        if self._resolved:
            if self._strip_leading:  # the tag ended at a piece boundary: its newline must not be spoken
                piece = piece.lstrip()
                self._strip_leading = not piece
            return piece
        self._held += piece
        return self._resolve(final=False)

    def finish(self) -> str:
        """End of stream: return speech still held back. A tag that never closed is not spoken."""
        if self._resolved:
            return ""
        return self._resolve(final=True)

    def _resolve(self, final: bool) -> str:
        head = self._held.lstrip()
        if not head:
            return ""
        if not head.startswith("[["):
            if head == "[" and not final:
                return ""  # one bracket so far: could still become a tag
            return self._speak(head)  # no tag at all: the whole reply is speech
        match = TAG.match(head)
        if match:
            decision = parse_tag(match.group(1))
            self.tag_ok, self.decision = decision is not None, decision or FALLBACK_DECISION
            return self._speak(head[match.end():].lstrip())
        newline = head.find("\n")
        if newline != -1:
            return self._speak(head[newline + 1:].lstrip())  # broken tag: drop its line, keep the speech after it
        if final or len(head) > MAX_TAG_CHARS:
            return self._speak("")  # an unclosed tag with no line end: drop it all
        return ""  # maybe a tag still arriving: keep holding

    def _speak(self, text: str) -> str:
        self._resolved = True
        self._held = ""
        self._strip_leading = not text
        return text
