"""From upload to interview: POST /interview/upload builds the session's plan from a resume PDF and a JD,
then the interview over /internal/turn asks that plan's questions. Scripted models, no network."""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.graph.api import router as internal_router
from backend.graph.interview.graph import build_interview_graph
from backend.interview.personas import BRIDGES, INTRO_QUESTION, OPENING, THANKS
from backend.server.interview_upload import router as upload_router
from backend.tests.helpers import ScriptedModel
from backend.tests.interview.fixtures import JOB_DESCRIPTION, RESUME, model_reply, scanned_pdf, text_pdf

KEY = "test-key"
SESSION = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", KEY)
    app = FastAPI()
    app.include_router(internal_router)
    app.include_router(upload_router)
    app.state.analyzer = ScriptedModel(model_reply())
    app.state.interview_plans = {}
    app.state.interview_graph = build_interview_graph(ScriptedModel())
    return app


def upload(app, pdf: bytes, job_description: str = JOB_DESCRIPTION):
    body = {"session_id": SESSION, "resume_pdf": base64.b64encode(pdf).decode(), "job_description": job_description}
    return TestClient(app).post("/interview/upload", json=body)


def interview_turn(app, answer: str | None = None) -> dict:
    body = {"session_id": SESSION, "mode": "interview", **({"answer": answer} if answer else {})}
    return TestClient(app).post("/internal/turn", json=body, headers={"api-key": KEY}).json()


def test_the_upload_returns_a_preview_and_the_interview_asks_the_plans_questions(app):
    response = upload(app, text_pdf(RESUME))
    assert response.status_code == 200
    assert response.json()["preview"] == ("We'll cover your work at Acme Payments, Java, how you work through real "
                                          "situations and your open-source contribution.")
    assert interview_turn(app)["reply"] == f"{OPENING} {INTRO_QUESTION}"
    second = interview_turn(app, "I'm a final-year student who interned at Acme.")
    assert second["reply"] == f"{THANKS} {BRIDGES['deep_dive']} How did you cut checkout latency at Acme?"
    assert "priya.sharma@example.com" not in app.state.analyzer.calls[0]["prompt"]  # contacts never reach the model


def test_a_scanned_pdf_is_rejected_before_any_llm_call(app):
    response = upload(app, scanned_pdf())
    assert response.status_code == 422 and response.json()["detail"]["code"] == "too_little_text"
    assert app.state.analyzer.calls == [] and app.state.interview_plans == {}


def test_when_the_analysis_fails_twice_the_session_gets_the_fallback_plan(app):
    app.state.analyzer = ScriptedModel(["not json"], ["still not json"])
    response = upload(app, text_pdf(RESUME))
    assert response.json()["fallback"] is True
    assert [t["kind"] for t in app.state.interview_plans[SESSION]["topics"]] == ["intro", "deep_dive", "behavioral"]


def test_an_upload_for_an_id_the_server_could_not_have_made_is_refused(app):
    body = {"session_id": "../../etc", "resume_pdf": base64.b64encode(text_pdf(RESUME)).decode()}
    assert TestClient(app).post("/interview/upload", json=body).status_code == 422
