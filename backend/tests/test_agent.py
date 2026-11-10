"""The agent answering a question: the agent <-> tools loop, the read-only tools on a small knowledge
base, and the Groq adapter that turns the model's stream into text and tool calls.
The model is scripted (no network); the Groq tests use a fake Groq stream."""

import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from backend.graph.graph import build_graph
from backend.graph.nodes.tools import MAX_TOOL_STEPS
from backend.graph.runner import run_turn, stream_turn
from backend.rag import llm
from backend.tests.helpers import DESCRIPTIONS, ScriptedModel, call, make_kb, no_retrieval
from backend.tools.registry import Tool, ToolRegistry, build_registry
from backend.tools.schemas import Args, GetSkillsArgs


def make_graph(model):
    return build_graph(no_retrieval, model, aliases={"beacon": "beacon"}, registry=build_registry(make_kb(), DESCRIPTIONS))


def turn(graph, text, session="s1"):
    return asyncio.run(run_turn(graph, session_id=session, text=text))


# --- the agent <-> tools loop ---------------------------------------------------------

def test_a_tool_result_reaches_the_answer_and_chained_calls_keep_every_result():
    model = ScriptedModel(
        [call("searchProjects", tech="Redis"), call("getLinks", type="github_profile")],
        [call("getProjectDetail", project_id="beacon", section="Overview")],
        ["Beacon monitors sites."],
    )
    out = turn(make_graph(model), "Show me his Redis project and GitHub")
    assert out["reply"] == "Beacon monitors sites."
    assert [c["name"] for c in out["tool_calls"]] == ["searchProjects", "getLinks", "getProjectDetail"]
    assert [c["type"] for c in out["cards"]] == ["link", "project_detail"]
    assert [c["name"] for c in model.calls[2]["tool_calls"]] == ["searchProjects", "getLinks", "getProjectDetail"]  # all results reach the next call


def test_a_tool_error_goes_back_to_the_model_and_the_turn_still_finishes():
    model = ScriptedModel([call("getProjectDetail", project_id="beacon", section="Pricing")], ["I don't have that."])
    out = turn(make_graph(model), "Beacon pricing?")
    assert out["reply"] == "I don't have that." and out["tool_calls"][0]["result"]["error"] == "unknown_section"
    assert model.calls[1]["tool_calls"][0]["result"]["error"] == "unknown_section"


def test_a_model_that_always_wants_tools_is_stopped_and_must_answer():
    model = ScriptedModel(*[[call("getSkills", skill="Redis")] for _ in range(10)])
    model.script[MAX_TOOL_STEPS] = ["Final answer."]  # the call after the cap
    out = turn(make_graph(model), "loop")
    assert out["reply"] == "Final answer." and len(out["tool_calls"]) == MAX_TOOL_STEPS
    assert model.calls[-1]["tools"] is None and "used all tool calls" in model.calls[-1]["prompt"]


def test_cards_and_tool_calls_belong_to_one_turn_and_arrive_before_the_answer():
    model = ScriptedModel([call("getLinks", type="github_profile")], ["Here."], ["Bye."])
    graph = make_graph(model)

    async def events(text):
        return [e async for mode, e in stream_turn(graph, "ev", text) if mode == "custom"]

    types = [e["type"] for e in asyncio.run(events("github"))]
    assert types.count("card") == 1 and types.index("card") < types.index("token")
    second = turn(graph, "bye", session="ev")
    assert second["cards"] == [] and second["tool_calls"] == []  # nothing carried over from the first turn


def test_a_cut_in_during_a_tool_call_leaves_the_session_usable():
    started = asyncio.Event()

    class SlowRegistry:
        def declarations(self):
            return [{"name": "slow", "description": "d", "parameters": {"type": "object"}}]

        async def execute(self, name, args, ctx=None):
            started.set()
            await asyncio.sleep(10)

    model = ScriptedModel([call("slow")], ["after cancel"])
    graph = build_graph(no_retrieval, model, aliases={}, registry=SlowRegistry())

    async def scenario():
        task = asyncio.create_task(run_turn(graph, session_id="c", text="go"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return await run_turn(graph, session_id="c", text="next")

    out = asyncio.run(scenario())
    assert out["reply"] == "after cancel" and out["tool_calls"] == []


# --- the tools ------------------------------------------------------------------------

@pytest.fixture
def registry():
    return build_registry(make_kb(), DESCRIPTIONS)


def run(registry, name, args):
    return asyncio.run(registry.execute(name, args))


def test_projects_are_found_by_technology_as_a_whole_word(registry):
    rec = run(registry, "searchProjects", {"tech": "java"})
    assert [p["id"] for p in rec["result"]["projects"]] == ["valyrian"]  # not matched by 'TypeScript'
    assert rec["result"]["projects"][0]["status"] == "runnable_not_deployed"


def test_a_project_section_is_shown_and_a_wrong_name_lists_the_valid_choices(registry):
    rec = run(registry, "getProjectDetail", {"project_id": "Beacon", "section": "limitations"})
    assert rec["ok"] and rec["result"]["section"] == "Limitations and Future Work" and rec["result"]["text"] == "No SSO."
    assert [c["type"] for c in rec["cards"]] == ["project_detail"]
    rec = run(registry, "getProjectDetail", {"project_id": "nope", "section": "Overview"})
    assert rec["result"]["error"] == "unknown_project" and "beacon" in rec["result"]["details"]
    rec = run(registry, "getProjectDetail", {"project_id": "valyrian", "section": "Architecture"})
    assert rec["result"]["error"] == "unknown_section" and "Overview" in rec["result"]["details"] and rec["cards"] == []


def test_a_skill_is_found_by_name_or_alias_and_an_unlisted_one_is_said_plainly(registry):
    found = run(registry, "getSkills", {"skill": "redis"})["result"]
    assert found["found"] and [e["kind"] for e in found["skills"][0]["evidence"]] == ["project", "experience"]
    assert run(registry, "getSkills", {"skill": "Postgres"})["result"]["skills"][0]["skill"] == "PostgreSQL"
    assert run(registry, "getSkills", {"skill": "Kubernetes"})["result"] == {"found": False, "skill": "Kubernetes", "used_in_projects": []}
    ts = run(registry, "getSkills", {"skill": "TypeScript"})["result"]  # in Beacon's tech list, not in skills
    assert ts["found"] is False and [p["id"] for p in ts["used_in_projects"]] == ["beacon"]


def test_a_link_is_shown_as_one_card(registry):
    rec = run(registry, "getLinks", {"type": "github_profile"})
    assert rec["result"]["links"][0]["url"] == "https://github.com/x" and [c["card_id"] for c in rec["cards"]] == ["link:gh"]


def test_bad_calls_slow_tools_and_broken_tools_become_errors_not_crashes(registry):
    assert run(registry, "nope", {})["result"]["error"] == "unknown_tool"
    assert run(registry, "getSkills", {"skil": "Redis"})["result"]["error"] == "invalid_args"
    assert run(registry, "getLinks", {"type": "twitter"})["result"]["error"] == "invalid_args"

    def slow(args, ctx):
        time.sleep(0.3)
        return {}, []

    def broken(args, ctx):
        raise KeyError("x")

    tools = ToolRegistry([Tool("slow", "d", Args, slow, timeout_s=0.05), Tool("broken", "d", Args, broken)])
    assert asyncio.run(tools.execute("slow", {}))["result"]["error"] == "timeout"
    assert asyncio.run(tools.execute("broken", {}))["result"]["error"] == "tool_failed"


def test_the_model_sees_each_arguments_description_and_allowed_values(registry):
    decl = {d["name"]: d for d in registry.declarations()}
    assert decl["getSkills"]["parameters"]["properties"]["skill"]["description"] == GetSkillsArgs.model_fields["skill"].description
    assert decl["getLinks"]["parameters"]["properties"]["type"]["enum"] == ["github_profile", "professional_profile"]


# --- the Groq adapter -------------------------------------------------------------------

def chunk(content=None, calls=(), reasoning=None):
    delta = NS(content=content, reasoning=reasoning, tool_calls=[
        NS(index=i, function=NS(name=name, arguments=args)) for i, name, args in calls] or None)
    return NS(choices=[NS(delta=delta)])


class FakeGroq:
    def __init__(self, *chunks):
        self.chunks = chunks
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **request):
        self.request = request

        async def stream():
            for c in self.chunks:
                yield c
        return stream()


def groq(*chunks):
    llm._client = FakeGroq(*chunks)

    async def go():
        return [piece async for piece in llm.stream_text("the prompt", "the system", [{"name": "t", "description": "d", "parameters": {}}])]
    try:
        return asyncio.run(go())
    finally:
        llm._client = None


def test_tool_results_go_to_groq_as_tool_messages_not_prompt_text():
    fake = llm._client = FakeGroq(chunk("ok"))
    done = [{"name": "getSkills", "args": {"skill": "Redis"}, "result": {"found": True}}]
    try:
        asyncio.run(anext(llm.stream_text("the prompt", "the system", None, done)))
    finally:
        llm._client = None
    roles = [m["role"] for m in fake.request["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    call_id = fake.request["messages"][2]["tool_calls"][0]["id"]
    assert fake.request["messages"][3] == {"role": "tool", "tool_call_id": call_id, "content": '{"found": true}'}


def test_groq_text_is_streamed_and_its_reasoning_is_never_spoken():
    assert groq(chunk(reasoning="the user wants..."), chunk("Hello "), chunk("there."), NS(choices=[])) == ["Hello ", "there."]


def test_groq_tool_calls_streamed_in_pieces_arrive_whole_and_separate():
    pieces = groq(chunk(calls=[(0, "getSkills", ""), (1, "getLinks", '{"type": "resume"}')]),
                  chunk(calls=[(0, None, '{"skill": "Re')]), chunk(calls=[(0, None, 'dis"}')]))
    assert pieces == [{"name": "getSkills", "args": {"skill": "Redis"}}, {"name": "getLinks", "args": {"type": "resume"}}]
    assert groq(chunk(calls=[(0, "cancelBooking", "")])) == [{"name": "cancelBooking", "args": {}}]  # no arguments
    assert groq(chunk(calls=[(0, "getSkills", '{"skill": ')])) == [{"name": "getSkills", "args": {}}]  # broken JSON
