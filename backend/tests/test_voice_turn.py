"""S10 + S11: voice_turn turns graph stream events into WebSocket messages and speech,
and with_turn_id tags messages. No Gemini, no TTS, no retriever: a fake graph or the
real graph with a scripted model, a fake send, and a fake stream_tts."""

import asyncio
import importlib

import pytest

from backend.graph.graph import build_graph
from backend.graph.nodes.agent import ERROR_REPLY
from backend.server.protocol import with_turn_id
from backend.server.session import new_conversation
from backend.tools.registry import build_registry
from backend.tests.test_tool_graph import ScriptedModel, call, no_retrieval
from backend.tests.test_tools import DESCRIPTIONS, make_kb

# the package re-exports the function voice_turn, which hides the module of the same name
vt = importlib.import_module("backend.pipeline.voice_turn")


class FakeGraph:
    """Stands in for the compiled graph: astream yields (mode, event) like LangGraph does."""

    def __init__(self, events=(), fail=None, hang_after_events=False):
        self.events, self.fail, self.hang = list(events), fail, hang_after_events

    async def astream(self, inputs, config, stream_mode):
        self.inputs, self.config = inputs, config
        for mode, event in self.events:
            yield mode, event
        if self.fail:
            raise self.fail
        if self.hang:
            await asyncio.sleep(10)


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
    async def stream_tts(text, interrupt_event, on_chunk, client):
        await on_chunk(b"mp3:" + text.encode())
    monkeypatch.setattr(vt, "stream_tts", stream_tts)


def run(graph, send, state=None, session_id="s1"):
    state = state or new_conversation()
    asyncio.run(vt.voice_turn("hi", state, send, asyncio.Event(), None, graph, session_id))
    return state


def kinds(sent):
    return [m[0] if isinstance(m, tuple) else "audio" for m in sent]


def test_tokens_stream_as_text_and_each_sentence_is_spoken(send, sent):
    state = run(FakeGraph([token("Hello there. How "), token("are you?")]), send)
    texts = [m[1]["text"] for m in sent if isinstance(m, tuple) and m[0] == "assistant_text"]
    assert texts == ["Hello there. How ", "are you?"]
    assert [m[1]["sentenceId"] for m in sent if isinstance(m, tuple) and m[0] == "tts_end"] == [0, 1]
    assert [m for m in sent if isinstance(m, bytes)][0].endswith(b"mp3:Hello there.")
    assert sent[-1][0] == "done" and state.sentence_counter == 2
    assert state.agent_speaking is True  # the browser may still be playing; cleared by playback_ended


def test_the_trailing_text_without_punctuation_is_still_spoken(send, sent):
    run(FakeGraph([token("No full stop")]), send)
    assert [m for m in sent if isinstance(m, bytes)][0].endswith(b"mp3:No full stop")


def test_card_event_becomes_ui_card_in_order_and_retrieval_becomes_a_metric(send, sent):
    card = {"card_id": "link:gh", "type": "link", "data": {"label": "GitHub"}}
    run(FakeGraph([("custom", {"type": "retrieval", "ms": 12.5}), ("custom", {"type": "card", "card": card}),
                   token("Here it is."), ("values", {"final_text": "ignored"})]), send)
    assert ("metric", {"stage": "rag_complete", "ragLatencyMs": 12.5}) in sent
    assert ("ui_card", {"card": card}) in sent
    assert kinds(sent).index("ui_card") < kinds(sent).index("assistant_text")  # card shows before the speech
    assert sum(1 for k in kinds(sent) if k == "done") == 1


def test_first_token_metric_is_sent_once(send, sent):
    run(FakeGraph([token("A. "), token("B.")]), send)
    assert [m[1]["stage"] for m in sent if isinstance(m, tuple) and m[0] == "metric"] == ["gemini_first_token"]


def test_the_graph_gets_the_session_id_as_thread_id(send):
    graph = FakeGraph([token("Hi.")])
    run(graph, send, session_id="abc")
    assert graph.config == {"configurable": {"thread_id": "abc"}} and graph.inputs == {"query": "hi"}


def test_graph_failure_before_any_speech_speaks_the_error_reply_and_finishes(send, sent):
    run(FakeGraph(fail=RuntimeError("boom")), send)
    assert [m for m in sent if isinstance(m, bytes)][0].endswith(b"mp3:" + ERROR_REPLY.encode())
    assert sent[-1][0] == "done"


def test_cancelling_the_turn_stops_the_graph_and_sends_no_done(send, sent):
    async def scenario():
        task = asyncio.create_task(vt.voice_turn("hi", new_conversation(), send, asyncio.Event(), None,
                                                 FakeGraph([token("Part one. ")], hang_after_events=True), "s"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert "done" not in kinds(sent)


def test_real_graph_tool_turn_sends_the_card_before_the_spoken_answer(send, sent):
    model = ScriptedModel([call("getLinks", type="github_profile")], ["Here is his GitHub."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=build_registry(make_kb(), DESCRIPTIONS))
    run(graph, send)
    cards = [m[1]["card"] for m in sent if isinstance(m, tuple) and m[0] == "ui_card"]
    assert [c["card_id"] for c in cards] == ["link:gh"]
    assert kinds(sent).index("ui_card") < kinds(sent).index("assistant_text") and sent[-1][0] == "done"


def test_second_turn_on_the_same_session_sees_the_first_in_its_prompt(send):
    model = ScriptedModel(["Hello."], ["Sure."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=None)
    run(graph, send, session_id="same")
    asyncio.run(vt.voice_turn("again", new_conversation(), send, asyncio.Event(), None, graph, "same"))
    assert "Visitor: hi" in model.calls[1]["prompt"] and "Agent: Hello." in model.calls[1]["prompt"]


# --- with_turn_id -----------------------------------------------------------

def test_with_turn_id_tags_json_and_leaves_audio_alone(sent, send):
    tagged = with_turn_id(send, 7)

    async def go():
        await tagged("assistant_text", {"text": "x"})
        await tagged("done")
        await tagged(b"\x00\x01audio")
    asyncio.run(go())
    assert sent == [("assistant_text", {"text": "x", "turnId": 7}), ("done", {"turnId": 7}), b"\x00\x01audio"]
