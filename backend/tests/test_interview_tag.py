"""The interviewer's control tag: parsed into a decision, and never passed on to TTS (plan T22)."""

from __future__ import annotations

import pytest

from backend.graph.interview.tag import MAX_TAG_CHARS, TagBuffer, parse_tag

SPEECH = "Right, the scheduler takes a lock. What if its worker dies?"


def stream(pieces: list[str]) -> tuple[str, TagBuffer]:
    """Feed pieces as the model would stream them; return everything the buffer let through."""
    buffer = TagBuffer()
    spoken = "".join(buffer.feed(piece) for piece in pieces) + buffer.finish()
    return spoken, buffer


def every_split(reply: str) -> list[list[str]]:
    """The reply cut into two pieces at every position, plus one character at a time."""
    return [[reply[:i], reply[i:]] for i in range(len(reply) + 1)] + [list(reply)]


# --- parse_tag ---------------------------------------------------------------------

@pytest.mark.parametrize("body, decision", [
    ("decision=probe", "probe"),
    (" decision = Challenge ", "challenge"),
    ("rating=3; decision=next", "next"),  # unknown keys are ignored, order does not matter
    ("decision=clarify_back;", "clarify_back"),
    ("decision=example; decision=next", "example"),  # the first one wins
])
def test_a_tag_body_gives_its_decision(body, decision):
    assert parse_tag(body) == decision


@pytest.mark.parametrize("body", ["", "decision=", "decision=skip", "decision probe", "probe", "rating=3"])
def test_a_tag_body_without_a_known_decision_gives_none(body):
    assert parse_tag(body) is None


# --- the stream buffer: what reaches TTS -------------------------------------------------

@pytest.mark.parametrize("reply", [
    f"[[decision=probe]]\n{SPEECH}",
    f"[[decision=probe]] {SPEECH}",  # no newline after the tag
    f"  \n[[decision=probe]]\n\n{SPEECH}",  # whitespace before and after
])
def test_a_tag_is_removed_and_its_decision_kept_however_the_stream_is_cut(reply):
    for pieces in every_split(reply):
        spoken, buffer = stream(pieces)
        assert spoken == SPEECH, pieces
        assert (buffer.decision, buffer.tag_ok) == ("probe", True)


def test_a_reply_without_a_tag_is_all_speech_and_falls_back_to_next():
    for pieces in every_split(SPEECH):
        spoken, buffer = stream(pieces)
        assert spoken == SPEECH
        assert (buffer.decision, buffer.tag_ok) == ("next", False)


def test_a_reply_without_a_tag_is_not_held_back():
    buffer = TagBuffer()
    assert buffer.feed("Right, ") == "Right, "  # the first piece goes straight to TTS


def test_speech_starting_with_one_bracket_is_spoken():
    spoken, buffer = stream(["[", "a]rray access is O(1)."])
    assert spoken == "[a]rray access is O(1)." and buffer.tag_ok is False


def test_an_unknown_decision_is_removed_from_speech_and_falls_back_to_next():
    spoken, buffer = stream(["[[decision=skip]]\n", SPEECH])
    assert spoken == SPEECH and (buffer.decision, buffer.tag_ok) == ("next", False)


def test_a_broken_tag_is_dropped_up_to_its_line_end():
    spoken, buffer = stream(["[[decision=probe\n", SPEECH])  # never closed
    assert spoken == SPEECH and (buffer.decision, buffer.tag_ok) == ("next", False)


def test_an_unclosed_tag_with_no_line_end_is_never_spoken():
    spoken, buffer = stream(["[[decision=probe ", "and the model keeps going without closing it"])
    assert spoken == "" and buffer.tag_ok is False


def test_an_endless_tag_stops_holding_the_stream_back_after_the_limit():
    buffer = TagBuffer()
    assert buffer.feed("[[" + "x" * MAX_TAG_CHARS) == ""  # dropped, not spoken
    assert buffer.feed(SPEECH) == SPEECH  # the rest flows through instead of waiting for the stream to end


def test_text_after_the_tag_flows_through_piece_by_piece():
    buffer = TagBuffer()
    assert buffer.feed("[[decision=next]]") == ""
    assert buffer.feed("\nGood. ") == "Good. "
    assert buffer.feed("Next topic.") == "Next topic."
    assert buffer.finish() == ""


def test_a_second_tag_later_in_the_reply_is_spoken_as_text():
    # only the first line is a control tag; the prompt forbids more, and the buffer does not hunt for them
    spoken, _ = stream(["[[decision=probe]]\n", "Fine. [[decision=next]]"])
    assert spoken == "Fine. [[decision=next]]"


@pytest.mark.parametrize("pieces", [[], [""], ["   ", "\n"]])
def test_an_empty_reply_speaks_nothing_and_falls_back_to_next(pieces):
    spoken, buffer = stream(pieces)
    assert spoken == "" and (buffer.decision, buffer.tag_ok) == ("next", False)
