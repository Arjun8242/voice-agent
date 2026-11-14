"""POST /internal/turn: the key check, request validation per mode, and an interview played in text (B8).

A small app with only this router and scripted graphs: no lifespan, no Groq, no network.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.graph.api import router
from backend.graph.graph import build_graph
from backend.graph.interview.graph import build_interview_graph
from backend.interview.personas import CLOSING, STRICT
from backend.interview.plan import Topic
from backend.tests.helpers import ScriptedModel, no_retrieval

KEY = "test-key"
TOPICS = [Topic(topic_id="beacon", title="Beacon", text="Beacon takes a Postgres advisory lock.")]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", KEY)
    app = FastAPI()
    app.include_router(router)
    app.state.recruiter_model = ScriptedModel(["Beacon is a monitor."])
    app.state.interview_model = ScriptedModel(["[[decision=next]]\nWhat does Beacon do?"],
                                              ["[[decision=probe]]\nWhy a lock?"])
    app.state.graph = build_graph(no_retrieval, app.state.recruiter_model, aliases={})
    app.state.interview_graph = build_interview_graph(app.state.interview_model, TOPICS)
    return TestClient(app), app.state


def post(client, body: dict, key: str | None = KEY):
    return client.post("/internal/turn", json=body, headers={"api-key": key} if key else {})


# --- access and validation ----------------------------------------------------------------

def test_a_wrong_key_is_refused(api):
    client, _ = api
    assert post(client, {"session_id": "s", "mode": "interview"}, key="nope").status_code == 401


@pytest.mark.parametrize("body", [
    {"session_id": "s"},  # recruiter mode needs input
    {"session_id": "s", "answer": "hi"},  # answer is for interviews
    {"session_id": "s", "mode": "interview", "input": {"text": "hi"}},  # input is for the recruiter
    {"session_id": "s", "mode": "interview", "answer": "x" * 2001},
    {"session_id": "s", "mode": "quiz", "answer": "hi"},
    {"session_id": "s", "mode": "interview", "persona": "x" * 21},
])
def test_a_request_that_does_not_fit_its_mode_is_rejected(api, body):
    client, _ = api
    assert post(client, body).status_code == 422


def test_recruiter_requests_work_as_before(api):
    client, state = api
    response = post(client, {"session_id": "s", "input": {"text": "What is Beacon?"}})
    assert response.status_code == 200 and response.json()["reply"] == "Beacon is a monitor."
    assert state.interview_model.calls == []


# --- an interview in text -----------------------------------------------------------------------

def test_an_interview_runs_in_text_with_its_flow_fields(api):
    client, state = api
    opening = post(client, {"session_id": "iv", "mode": "interview", "persona": "strict"}).json()
    assert (opening["reply"], opening["intent"], opening["topic_index"], opening["level"]) == ("What does Beacon do?", "start", 0, 1)

    answer = post(client, {"session_id": "iv", "mode": "interview", "answer": "It monitors sites."}).json()
    assert (answer["reply"], answer["decision"], answer["tag_ok"]) == ("Why a lock?", "probe", True)
    assert (answer["followups_used"], answer["level"]) == (1, 2)
    assert answer["answers"] == [{"topic_id": "beacon", "question": "What does Beacon do?", "text": "It monitors sites."}]
    assert STRICT.prompt_fragment in state.interview_model.calls[1]["prompt"]  # the persona of the first turn stuck
    assert state.recruiter_model.calls == []


def test_ending_an_interview_in_text_returns_the_closing_line(api):
    client, _ = api
    post(client, {"session_id": "iv", "mode": "interview"})
    end = post(client, {"session_id": "iv", "mode": "interview", "answer": "Let's end the interview."}).json()
    assert (end["reply"], end["finished"]) == (CLOSING, True)


def test_interview_and_recruiter_sessions_with_the_same_id_stay_apart(api):
    client, state = api
    post(client, {"session_id": "same", "input": {"text": "What is Beacon?"}})
    opening = post(client, {"session_id": "same", "mode": "interview"}).json()
    assert opening["intent"] == "start"  # the recruiter turn is not in the interview's history
