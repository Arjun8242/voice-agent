"""Speaking an answer: graph events become WebSocket messages and audio sentence by sentence, the text
is split into sentences without breaking names like Next.js, and speech from the visitor cuts the answer
off only when it is real speech. A fake graph or the real graph with a scripted model, a fake send and a
fake stream_tts; no network."""

import asyncio

import pytest

from backend.graph.graph import build_graph
from backend.graph.nodes.agent import ERROR_REPLY
from backend.pipeline.barge_in import BargeIn
from backend.pipeline.sentence import extract_next_sentence, extract_sentences
from backend.server.session import new_conversation
from backend.tests.helpers import DESCRIPTIONS, FakeGraph, ScriptedModel, call, make_kb, no_retrieval, vt
from backend.tools.registry import build_registry


def token(text):
    return ("custom", {"type": "token", "text": text})


@pytest.fixture
def sent():
    return []


@pytest.fixture
def send(sent):
    async def _send(message_type, payload=None):
        sent.append(message_type if isinstance(message_type, (bytes, bytearray)) else (message_type, payload or {}))
    return _send


@pytest.fixture(autouse=True)
def fake_tts(monkeypatch):
    async def stream_tts(text, interrupt_event, on_chunk, client, speaker=""):
        await on_chunk(b"mp3:" + text.encode())
    monkeypatch.setattr(vt, "stream_tts", stream_tts)


def run(graph, send, session_id="s1"):
    state = new_conversation()
    asyncio.run(vt.voice_turn("hi", state, send, asyncio.Event(), None, graph, session_id))
    return state


def kinds(sent):
    return [m[0] if isinstance(m, tuple) else "audio" for m in sent]


def audio(sent):
    return [m for m in sent if isinstance(m, bytes)]


# --- one spoken turn -------------------------------------------------------------------

def test_text_streams_as_it_comes_and_each_sentence_is_spoken_including_the_last_unfinished_one(send, sent):
    state = run(FakeGraph([token("Hello there. How "), token("are you? No full stop")]), send)
    assert [m[1]["text"] for m in sent if isinstance(m, tuple) and m[0] == "assistant_text"] == ["Hello there. How ", "are you? No full stop"]
    assert [a.split(b"mp3:")[1] for a in audio(sent)] == [b"Hello there.", b"How are you?", b"No full stop"]
    assert sent[-1][0] == "done" and state.agent_speaking is True  # the browser may still be playing


def test_a_tool_card_appears_before_the_spoken_answer(send, sent):
    model = ScriptedModel([call("getLinks", type="github_profile")], ["Here is his GitHub."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=build_registry(make_kb(), DESCRIPTIONS))
    run(graph, send)
    cards = [m[1]["card"] for m in sent if isinstance(m, tuple) and m[0] == "ui_card"]
    assert [c["card_id"] for c in cards] == ["link:gh"]
    assert kinds(sent).index("ui_card") < kinds(sent).index("assistant_text") and sent[-1][0] == "done"


def test_a_failure_before_any_speech_speaks_the_error_reply_and_finishes(send, sent):
    run(FakeGraph(fail=RuntimeError("boom")), send)
    assert audio(sent)[0].endswith(b"mp3:" + ERROR_REPLY.encode()) and sent[-1][0] == "done"


def test_a_cancelled_turn_stops_and_sends_no_done(send, sent):
    async def scenario():
        task = asyncio.create_task(vt.voice_turn("hi", new_conversation(), send, asyncio.Event(), None,
                                                 FakeGraph([token("Part one. ")], hang_after_events=True), "s"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert "done" not in kinds(sent)


# --- splitting the answer into sentences -----------------------------------------------

def test_dots_inside_names_and_numbers_do_not_end_a_sentence():
    out = extract_sentences("It uses a Next.js dashboard and Node.js workers. Version 3.5 shipped in 2026. Done now.")
    assert out["sentences"] == ["It uses a Next.js dashboard and Node.js workers.", "Version 3.5 shipped in 2026."]
    assert out["remaining"] == "Done now."  # the last sentence waits for the end-of-stream flush


def test_streamed_tokens_give_the_same_sentences_as_the_whole_text():
    tokens = ["Arjun built Beacon with Next", ".js and Express", ". It is shipped", ". Anything else?", " Ask away."]
    buffer, spoken = "", []
    for piece in tokens:
        buffer += piece
        while (nxt := extract_next_sentence(buffer)):
            spoken.append(nxt["sentence"])
            buffer = nxt["remaining"]
    if buffer.strip():  # what voice_turn does when the stream ends
        spoken.append(buffer.strip())
    assert spoken == ["Arjun built Beacon with Next.js and Express.", "It is shipped.", "Anything else?", "Ask away."]


# --- telling real speech from a cough ------------------------------------------------------

def barge_in(answering, speaking):
    cuts = []
    detector = BargeIn(is_answering=lambda: answering["now"], is_speaking=lambda: speaking,
                       interrupt=lambda: cuts.append(1), confirm_ms=50)
    return detector, cuts


def test_speech_over_the_answer_cuts_it_off_only_after_it_lasts():
    async def scenario():
        answering = {"now": True}
        detector, cuts = barge_in(answering, speaking=True)
        detector.on_speech_start()
        await asyncio.sleep(0.01)
        assert cuts == []  # too short to be sure yet
        await asyncio.sleep(0.1)
        assert cuts == [1]
        detector.dispose()
    asyncio.run(scenario())


def test_a_short_noise_or_an_answer_that_already_finished_is_not_cut_off():
    async def scenario():
        answering = {"now": True}
        cough, cuts = barge_in(answering, speaking=True)
        cough.on_speech_start()
        await asyncio.sleep(0.01)
        cough.on_speech_end()  # stopped before the confirm time
        await asyncio.sleep(0.1)
        assert cuts == []
        cough.dispose()

        late, late_cuts = barge_in(answering, speaking=True)
        late.on_speech_start()
        answering["now"] = False  # the answer finished on its own while we waited
        await asyncio.sleep(0.1)
        assert late_cuts == []
        late.dispose()
    asyncio.run(scenario())
