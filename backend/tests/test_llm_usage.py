"""Token usage (B9): Groq's reported counts travel from the stream to the turn log and /internal/turn,
and are never spoken or mistaken for a tool call."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

from backend.graph.graph import build_graph
from backend.graph.interview.graph import build_interview_graph
from backend.graph.runner import run_turn
from backend.interview.plan import Topic
from backend.observability.timings import report
from backend.observability.usage import LlmUsage, add_usage, empty_totals
from backend.rag import llm
from backend.tests.helpers import ScriptedModel, no_retrieval
from backend.tests.test_agent import FakeGroq, chunk

USAGE = LlmUsage(input_tokens=2500, output_tokens=180, cached_tokens=2000, reasoning_tokens=60)


def groq_usage(prompt=2500, completion=180, cached=2000, reasoning=60):
    return NS(prompt_tokens=prompt, completion_tokens=completion,
              prompt_tokens_details=NS(cached_tokens=cached), completion_tokens_details=NS(reasoning_tokens=reasoning))


def stream(*chunks) -> list:
    llm._client = FakeGroq(*chunks)
    try:
        return asyncio.run(_collect())
    finally:
        llm._client = None


async def _collect() -> list:
    return [piece async for piece in llm.stream_text("the prompt", "the system")]


# --- the Groq adapter --------------------------------------------------------------------

def test_the_final_chunks_usage_comes_last_after_the_text():
    final = NS(choices=[], x_groq=NS(usage=groq_usage()))
    assert stream(chunk("Hello."), final) == ["Hello.", USAGE]


def test_usage_in_the_openai_field_is_read_too():
    final = NS(choices=[], x_groq=None, usage=groq_usage(cached=0, reasoning=0))
    assert stream(chunk("Hi."), final)[-1] == LlmUsage(2500, 180, 0, 0)


def test_missing_detail_fields_count_as_zero():
    bare = NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None, completion_tokens_details=None)
    assert stream(NS(choices=[], x_groq=NS(usage=bare)))[-1] == LlmUsage(10, 5, 0, 0)


def test_a_stream_without_usage_yields_only_its_text():
    assert stream(chunk("Hi.")) == ["Hi."]


def test_usage_comes_after_the_tool_calls():
    final = NS(choices=[], x_groq=NS(usage=groq_usage()))
    pieces = stream(chunk(calls=[(0, "getSkills", '{"skill": "Redis"}')]), final)
    assert pieces == [{"name": "getSkills", "args": {"skill": "Redis"}}, USAGE]


# --- through the graphs --------------------------------------------------------------------

def test_the_recruiter_graph_counts_usage_and_never_speaks_it():
    graph = build_graph(no_retrieval, ScriptedModel(["Beacon is a monitor.", USAGE]), aliases={})
    result = asyncio.run(run_turn(graph, "s1", "What is Beacon?"))
    assert result["reply"] == "Beacon is a monitor." and result["tool_calls"] == []
    assert result["usage"] == {"llm_calls": 1, "input_tokens": 2500, "output_tokens": 180,
                               "cached_tokens": 2000, "reasoning_tokens": 60}


def test_the_interview_graph_counts_usage_and_never_speaks_it():
    topics = [Topic(topic_id="beacon", title="Beacon", text="Notes.")]
    graph = build_interview_graph(ScriptedModel(["[[decision=next]]\nWhat does Beacon do?", USAGE]), topics)
    result = asyncio.run(run_turn(graph, "s1", ""))
    assert result["reply"] == "What does Beacon do?" and result["usage"]["input_tokens"] == 2500


def test_a_turn_without_a_model_call_reports_zero():
    topics = [Topic(topic_id="beacon", title="Beacon", text="Notes.")]
    graph = build_interview_graph(ScriptedModel(), topics)
    result = asyncio.run(run_turn(graph, "s1", "Let's end the interview."))
    assert result["usage"] == empty_totals()


def test_usage_from_several_calls_in_one_turn_is_summed():
    totals = empty_totals()
    add_usage(totals, {"type": "usage", "input_tokens": 100, "output_tokens": 10, "cached_tokens": 0, "reasoning_tokens": 4})
    add_usage(totals, {"type": "usage", "input_tokens": 300, "output_tokens": 20, "cached_tokens": 50, "reasoning_tokens": 6})
    assert totals == {"llm_calls": 2, "input_tokens": 400, "output_tokens": 30, "cached_tokens": 50, "reasoning_tokens": 10}


# --- the report -----------------------------------------------------------------------------------

def test_the_report_gives_tokens_per_turn_and_skips_turns_logged_before_usage_existed():
    records = [{"input_tokens": 2000, "output_tokens": 100}, {"input_tokens": 3000, "output_tokens": 300}, {"total_ms": 5.0}]
    row = lambda name: next(line for line in report(records).splitlines() if line.startswith(name)).split()[1:]
    assert row("input_tokens")[:2] == ["2", "2500"]  # n and p50; the last record has no token fields
    assert row("output_tokens")[0] == "2"
