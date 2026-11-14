"""Interview mode over the WebSocket (C1): start_interview switches the connection to the interview graph,
its hold times, its STT silence and the persona's voice. Fake WebSocket, STT, TTS and models, as in
test_voice_conversation.py, whose harness this reuses."""

from __future__ import annotations

import asyncio
import json
import sys

from backend.config import TTS_SPEAKER
from backend.graph.interview.graph import build_interview_graph
from backend.interview.plan import Topic
from backend.providers.stt import stt_url
from backend.tests.helpers import ScriptedModel
from backend.tests.test_voice_conversation import TURN_LOG, GatedModel, connection, fake_tts, run  # noqa: F401 (fake_tts is an autouse fixture)

TOPICS = [Topic(topic_id="beacon", title="Beacon", text="Beacon takes a Postgres advisory lock.")]
OPENING = "What does Beacon do?"


def interviewer(*replies: list[str]) -> tuple[object, ScriptedModel]:
    model = ScriptedModel(["[[decision=next]]\n", OPENING], *replies)
    return build_interview_graph(model, TOPICS), model


def start(h, persona: str | None = "neutral") -> None:
    h.send_text(json.dumps({"type": "start_interview", "persona": persona}))


def record_speakers(monkeypatch) -> list[str]:
    """Replace the fake TTS with one that also records which voice each sentence used."""
    speakers: list[str] = []

    async def stream_tts(text, interrupt_event, on_chunk, client, speaker=""):
        speakers.append(speaker)
        await on_chunk(b"mp3")
    monkeypatch.setattr(sys.modules[connection.voice_turn.__module__], "stream_tts", stream_tts)
    return speakers


def test_start_interview_asks_the_opening_question_without_any_speech():
    graph, model = interviewer()
    recruiter = GatedModel()

    async def scenario(h):
        start(h)
        await h.answered(1)
        assert [m["text"] for m in h.of_type("assistant_text")] == [OPENING]
        assert h.of_type("transcript_final") == []  # nobody spoke: the interviewer opens
    run(scenario, recruiter, interview_graph=graph)
    assert len(model.calls) == 1 and recruiter.prompts == []


def test_the_strict_persona_speaks_with_its_own_voice(monkeypatch):
    speakers = record_speakers(monkeypatch)
    graph, _ = interviewer()

    async def scenario(h):
        start(h, "strict")
        await h.answered(1)
    run(scenario, GatedModel(), interview_graph=graph)
    assert speakers == ["shubh"]


def test_an_unknown_persona_gets_the_neutral_voice(monkeypatch):
    speakers = record_speakers(monkeypatch)
    graph, model = interviewer()

    async def scenario(h):
        start(h, "pirate")
        await h.answered(1)
    run(scenario, GatedModel(), interview_graph=graph)
    assert speakers == [TTS_SPEAKER]


def test_recruiter_turns_keep_the_default_voice(monkeypatch):
    speakers = record_speakers(monkeypatch)

    async def scenario(h):
        await h.say("q1")
        await h.answered(1)
    run(scenario, GatedModel(["Hello."]))
    assert speakers == [""]  # "" means TTS_SPEAKER inside stream_tts


def test_answers_go_to_the_interview_graph_after_the_longer_interview_hold():
    graph, model = interviewer(["[[decision=probe]]\n", "Why a lock?"])

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await h.say("It schedules checks.")
        await asyncio.sleep(0.6)  # past the 300 ms recruiter hold, inside the 1200 ms interview hold
        assert h.of_type("transcript_final") == []
        await h.until(lambda: h.of_type("transcript_final"), "the held answer", timeout=3)
        await h.answered(2)
        assert [m["text"] for m in h.of_type("assistant_text")][-1] == "Why a lock?"
    run(scenario, GatedModel(), interview_graph=graph)
    assert "Candidate's latest message: It schedules checks." in model.calls[1]["prompt"]


def test_start_interview_sets_the_interview_stt_silence():
    graph, _ = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        assert h.stt_holder[0].url == stt_url("interview")
    run(scenario, GatedModel(), interview_graph=graph)


def test_a_second_start_interview_is_ignored():
    graph, model = interviewer()

    async def scenario(h):
        start(h)
        start(h, "strict")
        await h.answered(1)
        await asyncio.sleep(0.2)
        assert len(h.of_type("done")) == 1
    run(scenario, GatedModel(), interview_graph=graph)
    assert len(model.calls) == 1


def test_start_interview_without_an_interview_graph_does_nothing():
    async def scenario(h):
        start(h)
        await asyncio.sleep(0.2)
        assert h.of_type("done") == [] and h.of_type("assistant_text") == []
    run(scenario, GatedModel())


def test_card_clicks_are_ignored_during_an_interview():
    graph, model = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.send_text(json.dumps({"type": "ui_action", "action": "select_slot", "payload": {}}))
        await asyncio.sleep(0.3)
        assert len(h.of_type("done")) == 1  # no second turn
    run(scenario, GatedModel(), interview_graph=graph)
    assert len(model.calls) == 1


def test_interview_turns_are_logged_with_their_mode():
    graph, _ = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
    run(scenario, GatedModel(), interview_graph=graph)
    assert [r["mode"] for r in TURN_LOG] == ["interview"]


# --- the End button (C2) ---------------------------------------------------------------------

def end(h) -> None:
    h.send_text(json.dumps({"type": "end_interview"}))


def test_the_end_button_speaks_the_closing_line_without_the_model():
    from backend.interview.personas import CLOSING
    graph, model = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        end(h)
        await h.answered(2)
        assert [m["text"] for m in h.of_type("assistant_text")][-1] == CLOSING
    run(scenario, GatedModel(), interview_graph=graph)
    assert len(model.calls) == 1


def test_the_end_button_cuts_off_a_question_still_being_asked():
    from backend.interview.personas import CLOSING
    model = GatedModel(["[[decision=next]]\n", OPENING], ["[[decision=probe]]\n", "Why a lock? ", asyncio.Event()])
    graph = build_interview_graph(model, TOPICS)

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await h.say("It schedules checks.")
        await h.spoken(2)  # "Why a lock?" is being spoken and the model is still going
        end(h)
        await h.until(lambda: h.of_type("interrupted"), "the question to be cut off")
        await h.answered(3)
        assert h.of_type("interrupted")[0]["turnId"] == 2
        assert [m["text"] for m in h.of_type("assistant_text") if m["turnId"] == 3] == [CLOSING]
    run(scenario, GatedModel(), interview_graph=graph)
    assert len(model.prompts) == 2  # the closing line needed no model call


def test_the_end_button_outside_an_interview_does_nothing():
    async def scenario(h):
        end(h)
        await asyncio.sleep(0.2)
        assert h.of_type("done") == []
    run(scenario, GatedModel(), interview_graph=interviewer()[0])


# --- silence nudges (C3) ------------------------------------------------------------------------

from backend.interview.personas import NEUTRAL  # noqa: E402
from backend.pipeline.turn_taking import TurnPolicy  # noqa: E402

FAST_INTERVIEW = TurnPolicy(base_hold_ms=100, long_hold_ms=200, think_hold_ms=400, reopen_ms=100, nudge_ms=(300, 600))


def fast_nudges(monkeypatch) -> None:
    monkeypatch.setattr(connection, "INTERVIEW_POLICY", FAST_INTERVIEW)


def spoken_texts(h) -> list[str]:
    return [m["text"] for m in h.of_type("assistant_text")]


def test_silence_after_the_question_gets_both_nudges_and_no_more(monkeypatch):
    fast_nudges(monkeypatch)
    graph, model = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)  # the question has been heard in full
        await h.answered(2)
        assert spoken_texts(h)[-1] == NEUTRAL.nudges[0]
        h.ended(2)  # the nudge's own audio ending must not restart the clock
        await h.answered(3)
        assert spoken_texts(h)[-1] == NEUTRAL.nudges[1]
        h.ended(3)
        await asyncio.sleep(1.0)
        assert len(h.of_type("done")) == 3
    run(scenario, GatedModel(), interview_graph=graph)
    assert len(model.calls) == 1  # nudges never call the model


def test_speaking_before_the_nudge_cancels_it(monkeypatch):
    fast_nudges(monkeypatch)
    graph, _ = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await asyncio.sleep(0.1)
        h.handlers.on_speech_start()  # the candidate starts answering
        await asyncio.sleep(0.8)
        assert NEUTRAL.nudges[0] not in spoken_texts(h)
    run(scenario, GatedModel(), interview_graph=graph)


def test_the_strict_interviewer_never_nudges(monkeypatch):
    fast_nudges(monkeypatch)
    graph, _ = interviewer()

    async def scenario(h):
        start(h, "strict")
        await h.answered(1)
        h.ended(1)
        await asyncio.sleep(0.9)
        assert len(h.of_type("done")) == 1
    run(scenario, GatedModel(), interview_graph=graph)


def test_no_nudges_after_the_end_button(monkeypatch):
    fast_nudges(monkeypatch)
    graph, _ = interviewer()

    async def scenario(h):
        start(h)
        await h.answered(1)
        end(h)
        await h.answered(2)
        h.ended(2)  # the closing line finished playing
        await asyncio.sleep(0.9)
        assert len(h.of_type("done")) == 2
    run(scenario, GatedModel(), interview_graph=graph)


def test_recruiter_mode_never_nudges(monkeypatch):
    fast_nudges(monkeypatch)

    async def scenario(h):
        await h.say("q1")
        await h.answered(1)
        h.ended(1)
        await asyncio.sleep(0.9)
        assert len(h.of_type("done")) == 1
    run(scenario, GatedModel(["Hello."]), interview_graph=interviewer()[0])


# --- the report (C4) ----------------------------------------------------------------------------

from backend.interview.evaluate import Report  # noqa: E402

EMPTY_REPORT = Report(reviews=[], tips=["Name the component first."], average_score=None, dropped_quotes=0)


class RecordingEvaluator:
    """Stands in for evaluate_interview: records the answers it was given and returns a fixed result."""

    def __init__(self, result: Report | None | Exception = EMPTY_REPORT, gate: asyncio.Event | None = None) -> None:
        self.result, self.gate, self.calls, self.cancelled = result, gate, [], False

    async def __call__(self, answers: list) -> Report | None:
        self.calls.append(answers)
        try:
            if self.gate is not None:
                await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def reports(h) -> list[dict]:
    return h.of_type("interview_report")


def test_the_end_button_starts_the_report_with_the_recorded_answers():
    graph, _ = interviewer(["[[decision=probe]]\n", "Why a lock?"])
    evaluator = RecordingEvaluator()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await h.say("It schedules checks.")
        await h.answered(2)
        end(h)
        await h.until(lambda: len(reports(h)) == 2, "the report")
        assert [r["status"] for r in reports(h)] == ["pending", "ready"]
        assert reports(h)[1]["report"]["tips"] == ["Name the component first."]
        assert all("turnId" not in r for r in reports(h))  # never dropped as a stale turn's message
    run(scenario, GatedModel(), interview_graph=graph, evaluator=evaluator)
    assert evaluator.calls == [[{"topic_id": "beacon", "question": OPENING, "text": "It schedules checks."}]]


def test_a_spoken_end_starts_the_report_too():
    graph, _ = interviewer()
    evaluator = RecordingEvaluator()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await h.say("Let's end the interview.")
        await h.until(lambda: len(reports(h)) == 2, "the report")
    run(scenario, GatedModel(), interview_graph=graph, evaluator=evaluator)
    assert len(evaluator.calls) == 1


def test_the_report_is_written_once_however_many_turns_follow_the_end():
    graph, _ = interviewer()
    evaluator = RecordingEvaluator()

    async def scenario(h):
        start(h)
        await h.answered(1)
        end(h)
        await h.answered(2)
        await h.say("Wait, one more thing.")  # the interview is over: the closing line again
        await h.answered(3)
        await h.until(lambda: len(reports(h)) == 2, "the report")
        await asyncio.sleep(0.2)
        assert len(reports(h)) == 2
    run(scenario, GatedModel(), interview_graph=graph, evaluator=evaluator)
    assert len(evaluator.calls) == 1


def test_no_report_while_the_interview_is_still_going():
    graph, _ = interviewer(["[[decision=probe]]\n", "Why a lock?"])
    evaluator = RecordingEvaluator()

    async def scenario(h):
        start(h)
        await h.answered(1)
        h.ended(1)
        await h.say("It schedules checks.")
        await h.answered(2)
        await asyncio.sleep(0.2)
        assert reports(h) == []
    run(scenario, GatedModel(), interview_graph=graph, evaluator=evaluator)
    assert evaluator.calls == []


def test_a_report_the_evaluator_could_not_write_is_reported_as_failed():
    for result in (None, RuntimeError("bug")):
        graph, _ = interviewer()

        async def scenario(h):
            start(h)
            await h.answered(1)
            end(h)
            await h.until(lambda: len(reports(h)) == 2, "the report")
            assert [r["status"] for r in reports(h)] == ["pending", "failed"]
        run(scenario, GatedModel(), interview_graph=graph, evaluator=RecordingEvaluator(result))


def test_leaving_the_page_cancels_a_report_still_being_written():
    graph, _ = interviewer()
    evaluator = RecordingEvaluator(gate=asyncio.Event())

    async def scenario(h):
        start(h)
        await h.answered(1)
        end(h)
        await h.until(lambda: reports(h), "the pending report")
        h.ws.incoming.put_nowait(None)  # the browser goes away
        await asyncio.wait_for(h.task, 3)
        await asyncio.sleep(0.05)  # checked here, before asyncio.run would cancel leftover tasks itself
        assert evaluator.cancelled is True
    run(scenario, GatedModel(), interview_graph=graph, evaluator=evaluator)
