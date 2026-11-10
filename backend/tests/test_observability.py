"""Observability (S16): the visitor's name, email and meeting title never reach LangSmith, and the
turn-log report gives p50 and p95 per stage."""

import json

from backend.observability import redact as r
from backend.observability.timings import report
from backend.tests.helpers import Flow


# --- masking what LangSmith receives ------------------------------------------------------

def test_every_checkpoint_of_a_real_booking_is_clean_once_masked(tmp_path):
    # the real shapes: ui_action payload at ingest, the summary card, the stored state after each step
    flow = Flow(tmp_path)
    flow.to_summary()
    states = [s.values for s in flow.graph.get_state_history({"configurable": {"thread_id": "s1"}})]
    raw = json.dumps(states, default=str)
    assert "priya@example.com" in raw and "Priya Shah" in raw  # they really are in the state, unmasked
    masked = json.dumps([r.redact(s) for s in states], default=str)
    assert not any(secret in masked for secret in ("priya@example.com", "Priya Shah", "Intro"))


def test_an_email_said_out_loud_is_masked_but_tool_names_and_link_titles_are_kept():
    assert r.redact({"query": "mail me at priya@example.com please"}) == {"query": "mail me at [redacted] please"}
    record = {"name": "getLinks", "cards": [{"type": "link", "data": {"title": "GitHub"}}]}
    assert r.redact(record) == record


def test_the_masked_tracer_is_used_only_when_tracing_is_on(monkeypatch):
    # langsmith caches its env vars, so the switch is stubbed rather than set through the environment
    monkeypatch.setattr("langsmith.utils.tracing_is_enabled", lambda *a, **k: False)
    assert r.tracing_callbacks() == []
    monkeypatch.setattr("langsmith.utils.tracing_is_enabled", lambda *a, **k: True)
    [tracer] = r.tracing_callbacks()  # building the client sends nothing
    assert tracer.client._hide_inputs is r.redact and tracer.client._hide_outputs is r.redact


# --- the p50 / p95 report -------------------------------------------------------------------

def test_the_report_gives_p50_and_p95_per_stage_and_counts_cut_off_turns_apart():
    records = [{"first_audio_ms": float(ms), "total_ms": float(ms), "interrupted": False, "stt_ms": None} for ms in range(1, 11)]
    records += [{"total_ms": None, "interrupted": True, "first_audio_ms": 1500.0}, {"total_ms": None, "interrupted": True, "first_audio_ms": None}]
    lines = report(records).splitlines()
    row = lambda stage: next(line for line in lines if line.startswith(stage)).split()[1:]
    assert "12 turns (fewer than 100" in lines[0]
    assert row("total_ms") == ["10", "6", "10"]  # finished turns only: n, p50 (5.5 rounds to 6), p95
    assert row("first_audio_ms")[0] == "11"  # a cut-off turn's audio still counts
    assert row("stt_ms") == ["0", "-", "-"]
    assert lines[-1] == "interrupted: 2 of 12 turns; 1 of them before any audio played"
