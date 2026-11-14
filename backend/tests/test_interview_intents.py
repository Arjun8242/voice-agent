"""classify_intent: clarification requests are recognised by phrase rules; everything else is an answer."""

from __future__ import annotations

import pytest

from backend.interview.intents import classify_intent


@pytest.mark.parametrize("text, intent", [
    # repeat
    ("Can you repeat that?", "repeat"),
    ("Can you repeat that again?", "repeat"),
    ("Sorry, could you repeat the question please?", "repeat"),
    ("Repeat.", "repeat"),
    ("Say that again?", "repeat"),
    ("Pardon?", "repeat"),
    ("Sorry, come again?", "repeat"),
    ("What was the question?", "repeat"),
    ("I didn't catch that.", "repeat"),
    # hint
    ("Can I get a hint?", "hint"),
    ("Give me a hint, please.", "hint"),
    ("Hint?", "hint"),
    ("Um, any hint?", "hint"),
    # rephrase
    ("What do you mean?", "rephrase"),
    ("What do you mean by that?", "rephrase"),
    ("Could you clarify?", "rephrase"),
    ("Can you rephrase the question?", "rephrase"),
    ("Which part?", "rephrase"),
    ("I don't understand the question.", "rephrase"),
    ("I didn't get it.", "rephrase"),
    # skip
    ("I don't know.", "skip"),
    ("I do not know", "skip"),
    ("Honestly, no idea.", "answer"),  # "honestly" is not politeness: the candidate may go on to explain
    ("No idea.", "skip"),
    ("Can we skip this one?", "skip"),
    ("Pass.", "skip"),
    ("Next question, please.", "skip"),
    ("Let's move on.", "skip"),
    # end
    ("Let's end the interview.", "end"),
    ("I want to stop the interview.", "end"),
    ("I'm done with this interview.", "end"),
])
def test_known_requests_are_recognised(text, intent):
    assert classify_intent(text) == intent


@pytest.mark.parametrize("text", [
    "It uses Postgres with an advisory lock.",
    "I don't know the exact number, but it's about five milliseconds.",  # starts like a skip
    "I don't know, can you give me a hint?",  # mixed: the model decides, not the rules
    "We repeat the check every minute.",  # "repeat" inside an answer
    "The hint is in the queue design: jobs are idempotent.",
    "I'd skip the cache and read from Postgres directly.",
    "What do you mean by idempotent here, the job or the HTTP call?",  # a real question about the topic
    "I'm done.",  # finished answering, not ending the interview
    "Stop the scheduler first, then drain the queue.",
    "Move on to the next job when the lock is released.",
    "Okay.",
    "",
])
def test_answers_that_contain_request_words_stay_answers(text):
    assert classify_intent(text) == "answer"
