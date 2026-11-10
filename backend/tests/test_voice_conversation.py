"""A voice conversation over the WebSocket (S11, S12): scripted timelines through the real handle_connection,
including barge-in and the session_start a page refresh sends.

Only the edges are fake: the WebSocket, speech-to-text, TTS and the model. Each test plays one
timeline (visitor speaks, answer starts, visitor cuts in, browser reports playback, next question)
and checks what the next prompt contains and that nothing from the cancelled turn arrives late.
"""

import asyncio
import importlib
import json
import sys
import time

import pytest
from fastapi.websockets import WebSocketState

from backend.graph.graph import build_graph
from backend.server.session import CUT_OFF_NOTE
from backend.tests.helpers import call, no_retrieval

connection = importlib.import_module("backend.server.connection")

FIRST, SECOND = "First sentence.", "Second sentence."
HEARD_FIRST = f"Agent: {FIRST} {CUT_OFF_NOTE}"


# --- fakes ------------------------------------------------------------------

class FakeWebSocket:
    client_state = WebSocketState.CONNECTED

    def __init__(self):
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []  # JSON messages the server sent

    async def accept(self):
        pass

    async def receive(self):
        item = await self.incoming.get()
        if item is None:
            raise RuntimeError("disconnect")
        return item

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        pass  # audio frames are not needed here


class FakeStt:
    def __init__(self, handlers):
        self.handlers = handlers

    def send_audio(self, data):
        pass

    def close(self):
        pass


class GatedModel:
    """Each agent call takes the next script entry: a list of text pieces, tool calls (dicts) and
    asyncio.Events. An Event pauses the model until the test sets it, so a turn can be held mid-answer."""

    def __init__(self, *script):
        self.script, self.prompts = list(script), []

    def __call__(self, prompt, system_instruction, tools=None, tool_calls=None):
        self.prompts.append(prompt)
        pieces = self.script.pop(0) if self.script else ["Ok."]

        async def gen():
            for piece in pieces:
                if isinstance(piece, asyncio.Event):
                    await piece.wait()
                else:
                    yield piece
        return gen()


class SlowCardRegistry:
    """A tool that takes 0.3 s and then returns a card: the card must never be sent if the turn is cut off."""

    def declarations(self):
        return [{"name": "slowCard", "description": "d", "parameters": {"type": "object"}}]

    async def execute(self, name, args, ctx=None):
        self.started = True
        await asyncio.sleep(0.3)
        card = {"card_id": "link:late", "type": "link", "data": {}}
        return {"name": name, "args": args, "cards": [card], "ok": True, "ms": 300.0, "result": {}}


class Harness:
    def __init__(self, ws, stt_holder, task, model):
        self.ws, self.stt_holder, self.task, self.model = ws, stt_holder, task, model

    @property
    def handlers(self):
        return self.stt_holder[0].handlers

    def of_type(self, kind):
        return [m for m in self.ws.sent if m["type"] == kind]

    async def until(self, condition, what, timeout=3.0):
        start = time.monotonic()
        while not condition():
            if time.monotonic() - start > timeout:
                raise AssertionError(f"timed out waiting for {what}; sent so far: {[m['type'] for m in self.ws.sent]}")
            await asyncio.sleep(0.01)

    async def say(self, text):
        await self.handlers.on_final(text)

    async def cut_in(self):
        """The visitor starts speaking over the answer; returns the turn id the server reports as interrupted."""
        before = len(self.of_type("interrupted"))
        self.handlers.on_speech_start()
        await self.until(lambda: len(self.of_type("interrupted")) > before, "the interrupted message")
        return self.of_type("interrupted")[-1]["turnId"]

    def report(self, turn_id, last_sentence_id):
        """What the browser sends right after it gets 'interrupted'."""
        self.send_text(json.dumps({"type": "playback_progress", "turnId": turn_id, "lastSentenceId": last_sentence_id}))

    def ended(self, turn_id):
        """What the browser sends when the answer's audio finished playing."""
        self.send_text(json.dumps({"type": "playback_ended", "turnId": turn_id}))

    def send_text(self, text):
        self.ws.incoming.put_nowait({"type": "websocket.receive", "text": text})

    async def answered(self, turn_id):
        await self.until(lambda: any(m["type"] == "done" and m.get("turnId") == turn_id for m in self.ws.sent), f"done of turn {turn_id}")

    async def spoken(self, count):
        await self.until(lambda: len(self.of_type("tts_end")) >= count, f"{count} spoken sentences")


def run(scenario, model, registry=None, graph=None):
    """Start a connection on a fresh graph (or the given one), run the scenario coroutine, then disconnect."""
    async def main():
        ws, holder = FakeWebSocket(), []
        nonlocal graph
        graph = graph or build_graph(no_retrieval, model, aliases={}, registry=registry)
        original = connection.create_stt
        connection.create_stt = lambda handlers: holder.append(FakeStt(handlers)) or holder[-1]
        task = asyncio.create_task(connection.handle_connection(ws, None, graph))
        try:
            h = Harness(ws, holder, task, model)
            await h.until(lambda: holder, "the connection to start")
            await scenario(h)
        finally:
            connection.create_stt = original
            ws.incoming.put_nowait(None)
            await asyncio.wait_for(task, 3)
    asyncio.run(main())


@pytest.fixture(autouse=True)
def fake_tts(monkeypatch):
    async def stream_tts(text, interrupt_event, on_chunk, client):
        await on_chunk(b"mp3")
    # backend/__init__.py puts backend/ on sys.path, so connection may hold the top-level copy
    # (pipeline.voice_turn) instead of backend.pipeline.voice_turn. Patch the copy it really uses.
    used = sys.modules[connection.voice_turn.__module__]
    monkeypatch.setattr(used, "stream_tts", stream_tts)
    TURN_LOG.clear()
    monkeypatch.setattr(used, "append_turn_log", TURN_LOG.append)  # never write the real data/turn_log.jsonl


TURN_LOG: list[dict] = []  # turn-log lines written during the current test


def two_sentences_then_hold():
    """First turn of most timelines: two sentences are spoken, then the model stalls (answer still running)."""
    return [f"{FIRST} ", f"{SECOND} ", asyncio.Event()]


# --- timelines --------------------------------------------------------------

def test_1_cut_in_while_speaking_keeps_only_the_heard_sentence():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        turn = await h.cut_in()
        h.report(turn, 0)  # the browser was playing sentence 0
        await h.say("q2")
        await h.answered(2)
        prompt = model.prompts[1]
        assert f"Visitor: q1\n{HEARD_FIRST}" in prompt
        assert SECOND not in prompt  # queued and sent, but never heard
    run(scenario, model)


def test_2_cut_in_before_any_audio_played_records_no_answer():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        turn = await h.cut_in()
        h.report(turn, None)  # nothing had started playing
        await h.say("q2")
        await h.answered(2)
        assert "Agent:" not in model.prompts[1] and "Visitor: q1" in model.prompts[1]
    run(scenario, model)


def test_3_cut_in_during_a_tool_call_sends_no_late_card_and_the_session_still_works():
    model = GatedModel([call("slowCard")], ["Next answer."])
    registry = SlowCardRegistry()

    async def scenario(h):
        await h.say("q1")
        await h.until(lambda: getattr(registry, "started", False), "the tool to start")
        turn = await h.cut_in()  # no audio yet, so the interrupt is immediate
        await asyncio.sleep(0.5)  # longer than the tool: a leaked card would have arrived by now
        assert h.of_type("ui_card") == []
        assert all(m.get("turnId") != turn for m in h.ws.sent if m["type"] in ("assistant_text", "done"))
        await h.say("q2")
        await h.answered(2)
        assert [m["text"] for m in h.of_type("assistant_text")] == ["Next answer."]
    run(scenario, model, registry)


def test_4_report_that_never_arrives_does_not_block_the_next_turn_and_a_late_one_is_ignored():
    model = GatedModel(two_sentences_then_hold(), ["Fine."], ["Again."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        turn = await h.cut_in()
        start = time.monotonic()
        await h.say("q2")  # no report: the turn waits up to 1 s, then goes on
        await h.answered(2)
        assert 0.9 < time.monotonic() - start < 2.5
        assert "Agent:" not in model.prompts[1]
        h.report(turn, 0)  # far too late
        await h.say("q3")
        await h.answered(3)
        assert CUT_OFF_NOTE not in model.prompts[2] and FIRST not in model.prompts[2]  # turn 1's answer was never recorded
    run(scenario, model)


def test_5_report_that_arrives_while_the_next_turn_waits_is_used_without_waiting_the_full_second():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        turn = await h.cut_in()
        start = time.monotonic()
        await h.say("q2")
        await asyncio.sleep(0.2)
        h.report(turn, 0)
        await h.answered(2)
        assert time.monotonic() - start < 0.9
        assert f"Visitor: q1\n{HEARD_FIRST}" in model.prompts[1]
    run(scenario, model)


def test_6_report_for_another_turn_is_ignored():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        turn = await h.cut_in()
        h.report(99, 1)  # stale or wrong turn id
        h.report(turn, 0)  # the real one
        await h.say("q2")
        await h.answered(2)
        assert HEARD_FIRST in model.prompts[1] and SECOND not in model.prompts[1]
    run(scenario, model)


def test_7_junk_text_frames_do_not_drop_the_connection():
    model = GatedModel(["Hello."])

    async def scenario(h):
        for junk in ("not json", "[1, 2]", json.dumps({"type": "unknown"}), json.dumps({"type": "playback_progress"})):
            h.send_text(junk)
        await h.say("q1")
        await h.answered(1)
        assert not h.task.done()
    run(scenario, model)


def test_8_two_cut_ins_in_a_row_each_keep_their_own_heard_text_once():
    model = GatedModel(two_sentences_then_hold(), [f"Other one. ", "Other two. ", asyncio.Event()], ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        h.report(await h.cut_in(), 0)  # sentence ids are per connection: turn 1 used 0 and 1
        await h.say("q2")
        await h.spoken(4)
        h.report(await h.cut_in(), 2)  # turn 2 used 2 and 3; sentence 2 was playing
        await h.say("q3")
        await h.answered(3)
        prompt = model.prompts[2]
        assert prompt.count(CUT_OFF_NOTE) == 2
        history = prompt.split("\n\nRetrieval status")[0]
        assert history == (
            f"Conversation so far:\nVisitor: q1\n{HEARD_FIRST}\n"
            f"Visitor: q2\nAgent: Other one. {CUT_OFF_NOTE}"
        )
        assert "Other two." not in prompt and SECOND not in prompt
    run(scenario, model)


# --- review fixes: cut-ins after the server has finished --------------------

def test_9_cut_in_after_the_turn_finished_while_audio_still_plays_replaces_the_full_answer():
    model = GatedModel([f"{FIRST} ", f"{SECOND} "], ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.answered(1)  # the server is done; the browser is still playing
        turn = await h.cut_in()
        assert turn == 1
        h.report(turn, 0)
        await h.say("q2")
        await h.answered(2)
        assert f"Visitor: q1\n{HEARD_FIRST}" in model.prompts[1]
        assert SECOND not in model.prompts[1]  # the saved full answer was replaced, not kept
    run(scenario, model)


def test_10_after_playback_ended_speech_is_a_new_question_not_a_barge_in():
    model = GatedModel([f"{FIRST} ", f"{SECOND} "], ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.answered(1)
        h.ended(1)
        await asyncio.sleep(0.05)
        h.handlers.on_speech_start()
        await asyncio.sleep(0.5)  # longer than the 300 ms barge-in confirm
        assert h.of_type("interrupted") == []
        await h.say("q2")
        await h.answered(2)
        assert f"Agent: {FIRST} {SECOND}" in model.prompts[1]  # heard in full, kept in full
    run(scenario, model)


def test_11_cut_in_while_the_last_sentence_is_still_spoken_does_not_keep_two_answers(monkeypatch):
    model = GatedModel([f"{FIRST} ", f"{SECOND} "], ["Fine."])

    async def slow_tts(text, interrupt_event, on_chunk, client):
        await on_chunk(b"mp3")
        if SECOND in text:
            await asyncio.sleep(1.5)  # the graph has finished and saved the answer; speech is not done
    monkeypatch.setattr(sys.modules[connection.voice_turn.__module__], "stream_tts", slow_tts)

    async def scenario(h):
        await h.say("q1")
        await h.spoken(1)
        h.report(await h.cut_in(), 0)
        await h.say("q2")
        await h.answered(2)
        prompt = model.prompts[1]
        assert HEARD_FIRST in prompt and SECOND not in prompt and prompt.count("Agent:") == 1
    run(scenario, model)


def test_12_speaking_again_while_the_next_turn_waits_keeps_the_heard_text():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")
        await h.spoken(2)
        first = await h.cut_in()  # the report has not arrived yet
        await h.say("q2")  # turn 2 starts and waits for it
        h.handlers.on_speech_start()  # the visitor keeps talking: turn 2 is cut off while it waits
        await h.until(lambda: len(h.of_type("interrupted")) == 2, "the second interrupt")
        h.report(first, 0)
        await h.say("q3")
        await h.answered(3)
        assert HEARD_FIRST in model.prompts[-1]
    run(scenario, model)


# --- whole-path timings -----------------------------------------------------

def test_13_each_finished_turn_logs_its_stage_times():
    model = GatedModel([f"{FIRST} ", f"{SECOND} "])

    async def scenario(h):
        h.handlers.on_speech_start()
        h.handlers.on_speech_end()
        await asyncio.sleep(0.05)  # STT takes a moment to send the final transcript
        await h.say("q1")
        await h.answered(1)
    run(scenario, model)

    assert len(TURN_LOG) == 1
    r = TURN_LOG[0]
    assert r["turn_id"] == 1 and r["stt_ms"] >= 40 and r["wait_ms"] < 50 and r["tools"] == []
    for field in ("rag_ms", "first_token_ms", "first_sentence_ms", "first_audio_ms", "total_ms"):
        assert r[field] is not None, field
    assert r["speech_end_to_first_audio_ms"] == round(r["stt_ms"] + r["wait_ms"] + r["first_audio_ms"], 1)


def test_14_a_cut_off_turn_is_logged_as_interrupted_with_the_times_it_reached():
    model = GatedModel(two_sentences_then_hold(), ["Fine."])

    async def scenario(h):
        await h.say("q1")  # no speech-end event before this final: stt time unknown
        await h.spoken(2)
        h.report(await h.cut_in(), 0)
        await h.say("q2")
        await h.answered(2)
    run(scenario, model)

    cut, done = TURN_LOG
    assert (cut["turn_id"], cut["interrupted"], done["turn_id"], done["interrupted"]) == (1, True, 2, False)
    assert cut["first_audio_ms"] is not None  # audio had started: a real measurement, kept
    assert cut["total_ms"] is None and cut["cut_off_ms"] >= cut["first_audio_ms"]  # cut short: no fake total
    assert done["total_ms"] is not None and done["cut_off_ms"] is None
    assert cut["stt_ms"] is None and cut["speech_end_to_first_audio_ms"] is None  # no speech-end event was sent


def test_15_a_cut_in_before_any_audio_is_logged_as_given_up_waiting():
    model = GatedModel([call("slowCard")], ["Next answer."])
    registry = SlowCardRegistry()

    async def scenario(h):
        await h.say("q1")
        await h.until(lambda: getattr(registry, "started", False), "the tool to start")
        await h.cut_in()
        await h.until(lambda: TURN_LOG, "the interrupted turn's log line")
    run(scenario, model, registry)

    (cut,) = TURN_LOG
    assert cut["interrupted"] is True and cut["first_audio_ms"] is None and cut["cut_off_ms"] is not None


# --- session_start: a refresh continues the same conversation ------------------------

SID = "a" * 32


def start(h, session_id, timezone="Asia/Tokyo"):
    h.send_text(json.dumps({"type": "session_start", "sessionId": session_id, "timezone": timezone}))


def thread_state(graph, session_id):
    return graph.get_state({"configurable": {"thread_id": session_id}}).values


def test_a_refresh_with_the_same_session_id_continues_the_conversation():
    model = GatedModel(["Hello."], ["Sure."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=None)

    async def first_page_load(h):
        start(h, SID)
        await h.until(lambda: h.of_type("session"), "the session reply")
        assert h.of_type("session")[0]["sessionId"] == SID
        await h.say("q1")
        await h.answered(1)

    async def after_refresh(h):  # a new connection, as after F5: same id, same graph
        start(h, SID)
        await h.until(lambda: h.of_type("session"), "the session reply")
        await h.say("q2")
        await h.answered(1)

    run(first_page_load, model, graph=graph)
    run(after_refresh, model, graph=graph)
    assert "Visitor: q1" in model.prompts[1] and "Agent: Hello." in model.prompts[1]


def test_a_missing_or_malformed_id_gets_a_fresh_valid_one():
    for bad in ("", "../../etc/passwd", "A" * 32, 123):
        model = GatedModel()

        async def scenario(h):
            start(h, bad)
            await h.until(lambda: h.of_type("session"), "the session reply")
            new = h.of_type("session")[0]["sessionId"]
            assert new != bad and len(new) == 32 and new == new.lower() and int(new, 16) >= 0
        run(scenario, model)


def test_the_visitor_timezone_is_saved_in_the_thread_state():
    model = GatedModel(["Hi."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=None)

    async def scenario(h):
        start(h, SID, "Asia/Tokyo")
        await h.until(lambda: h.of_type("session"), "the session reply")
        await h.say("q")
        await h.answered(1)
    run(scenario, model, graph=graph)
    assert thread_state(graph, SID)["visitor_timezone"] == "Asia/Tokyo"


def test_an_invalid_timezone_falls_back_to_the_default():
    model = GatedModel(["Hi."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=None)

    async def scenario(h):
        start(h, SID, "Not/AZone")
        await h.until(lambda: h.of_type("session"), "the session reply")
        await h.say("q")
        await h.answered(1)
    run(scenario, model, graph=graph)
    assert thread_state(graph, SID)["visitor_timezone"] == "Asia/Kolkata"
