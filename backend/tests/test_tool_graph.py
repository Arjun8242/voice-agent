"""S9: the agent <-> tools loop, with a scripted fake model (no Gemini, no retriever)."""

import asyncio

import pytest

from backend.graph.graph import build_graph
from backend.graph.nodes.tools import MAX_TOOL_STEPS
from backend.graph.runner import run_turn
from backend.tools.registry import build_registry
from backend.tests.test_tools import DESCRIPTIONS, make_kb


async def no_retrieval(query, top_k=4, topic=None):
    return {"query": query, "chunks": [], "status": "none_relevant", "combinedContext": ""}


class ScriptedModel:
    """Each agent call takes the next script entry: a list of pieces (str = text, dict = tool call)."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, prompt, system_instruction, tools=None):
        self.calls.append({"prompt": prompt, "tools": tools})
        pieces = self.script.pop(0) if self.script else ["fallback answer"]

        async def gen():
            for p in pieces:
                yield p
        return gen()


def call(name, **args):
    return {"name": name, "args": args}


def make_graph(model, with_tools=True):
    registry = build_registry(make_kb(), DESCRIPTIONS) if with_tools else None
    return build_graph(no_retrieval, model, aliases={"beacon": "beacon"}, registry=registry)


def turn(graph, text, session="s1"):
    return asyncio.run(run_turn(graph, session_id=session, text=text))


def test_answer_without_tools():
    model = ScriptedModel(["Hello ", "there."])
    out = turn(make_graph(model), "hi")
    assert out["reply"] == "Hello there." and out["tool_calls"] == [] and out["cards"] == []
    assert model.calls[0]["tools"] is not None  # tools were offered, the model chose not to use them


def test_one_tool_call_then_answer_sees_the_result():
    model = ScriptedModel([call("getSkills", skill="Redis")], ["Yes, he uses Redis in Beacon."])
    out = turn(make_graph(model), "Does he know Redis?")
    assert out["reply"] == "Yes, he uses Redis in Beacon."
    assert [(c["name"], c["args"], c["ok"]) for c in out["tool_calls"]] == [("getSkills", {"skill": "Redis"}, True)]
    assert 'getSkills({"skill": "Redis"}) returned' in model.calls[1]["prompt"]


def test_parallel_calls_and_chained_calls_keep_all_results():
    model = ScriptedModel(
        [call("searchProjects", tech="Redis"), call("getLinks", type="github_profile")],
        [call("getProjectDetail", project_id="beacon", section="Overview")],
        ["Beacon monitors sites."],
    )
    out = turn(make_graph(model), "Show me his Redis project and GitHub")
    assert [c["name"] for c in out["tool_calls"]] == ["searchProjects", "getLinks", "getProjectDetail"]
    assert [c["type"] for c in out["cards"]] == ["link", "project_detail"]
    last_prompt = model.calls[2]["prompt"]
    assert "searchProjects(" in last_prompt and "getProjectDetail(" in last_prompt  # earlier results not lost


def test_tool_error_goes_back_to_the_model_and_turn_finishes():
    model = ScriptedModel([call("getProjectDetail", project_id="beacon", section="Pricing")], ["I don't have that."])
    out = turn(make_graph(model), "Beacon pricing?")
    assert out["reply"] == "I don't have that." and out["tool_calls"][0]["result"]["error"] == "unknown_section"
    assert '"unknown_section"' in model.calls[1]["prompt"]


def test_step_cap_stops_a_model_that_always_wants_tools():
    model = ScriptedModel(*[[call("getSkills", skill="Redis")] for _ in range(10)])
    model.script[MAX_TOOL_STEPS] = ["Final answer."]  # the call after the cap
    out = turn(make_graph(model), "loop")
    assert out["reply"] == "Final answer." and len(out["tool_calls"]) == MAX_TOOL_STEPS
    assert model.calls[-1]["tools"] is None and "used all tool calls" in model.calls[-1]["prompt"]


def test_calls_over_the_cap_in_one_response_are_reported_not_run():
    model = ScriptedModel([call("getSkills", skill=str(i)) for i in range(MAX_TOOL_STEPS + 2)], ["Done."])
    out = turn(make_graph(model), "many")
    errors = [c["result"].get("error") for c in out["tool_calls"]]
    assert errors.count("step_cap") == 2 and len(errors) == MAX_TOOL_STEPS + 2


def test_per_turn_fields_reset_between_turns_of_one_session():
    model = ScriptedModel([call("getLinks", type="github_profile")], ["Here."],
                          [call("getLinks", type="github_profile")], ["Here again."], ["Bye."])
    graph = make_graph(model)
    first, second, third = turn(graph, "github"), turn(graph, "github again"), turn(graph, "bye")
    assert len(first["cards"]) == len(second["cards"]) == 1 and len(second["tool_calls"]) == 1
    assert third["cards"] == [] and third["tool_calls"] == []


def test_errors_are_not_duplicated_or_carried_to_the_next_turn():
    def failing(prompt, system_instruction, tools=None):
        async def gen():
            raise RuntimeError("boom")
            yield  # makes this an async generator
        return gen()
    graph = make_graph(failing)
    assert turn(graph, "a")["errors"] == ["agent: boom"]
    assert turn(graph, "b")["errors"] == ["agent: boom"]


def test_without_registry_the_model_gets_no_tools():
    model = ScriptedModel(["Plain answer."])
    out = turn(make_graph(model, with_tools=False), "hi")
    assert out["reply"] == "Plain answer." and model.calls[0]["tools"] is None


def test_cancelling_mid_tools_leaves_the_session_usable():
    started = asyncio.Event()

    class SlowRegistry:
        def declarations(self):
            return [{"name": "slow", "description": "d", "parameters": {"type": "object"}}]

        async def execute(self, name, args):
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
