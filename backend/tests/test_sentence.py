"""Sentence splitting for the streamed answer. A dot inside a name must not end a sentence."""

import pytest

from backend.pipeline.sentence import extract_next_sentence, extract_sentences


def test_tech_names_with_dots_stay_in_one_sentence():
    text = "It uses a Next.js dashboard and Node.js workers. Done now. "
    out = extract_sentences(text)
    assert out["sentences"] == ["It uses a Next.js dashboard and Node.js workers."]
    assert out["remaining"] == "Done now."  # the last sentence waits for the end-of-stream flush


def test_numbers_with_dots_do_not_split():
    assert extract_next_sentence("Version 3.5 shipped in 2026. Next") == {"sentence": "Version 3.5 shipped in 2026.", "remaining": "Next"}


def test_terminator_at_the_end_of_the_buffer_waits_for_more_text():
    assert extract_next_sentence("He built it with Next.") is None  # "js" may still arrive
    assert extract_next_sentence("He built it with Next.js") is None
    assert extract_next_sentence("Hello there.") is None  # flushed by the caller at the end of the stream


def test_streamed_tokens_give_the_same_sentences_as_the_whole_text():
    tokens = ["Arjun built Beacon with Next", ".js and Express", ". It is shipped", ". Anything else?", " Ask away."]
    buffer, spoken = "", []
    for token in tokens:
        buffer += token
        while (nxt := extract_next_sentence(buffer)):
            spoken.append(nxt["sentence"])
            buffer = nxt["remaining"]
    if buffer.strip():  # what voice_turn does when the stream ends
        spoken.append(buffer.strip())
    assert spoken == ["Arjun built Beacon with Next.js and Express.", "It is shipped.", "Anything else?", "Ask away."]


@pytest.mark.parametrize("text,first", [
    ('He said "stop." Then left.', 'He said "stop."'),
    ("Really?! Yes.", "Really?!"),
    ("Wait... what. Ok", "Wait..."),
])
def test_closing_quotes_and_repeated_punctuation_end_the_sentence(text, first):
    assert extract_next_sentence(text)["sentence"] == first
