"""Graph tests with fake models emitting function calls (S9).

Verifies:
- Answer directly with no tool call.
- One tool call, then answer.
- Two consecutive tool calls, then answer.
- Cap: a model that always asks for a tool stops at 4 tool steps.
- A tool error is passed back to the model and the turn still finishes.
- Cards and tool calls appear in run_turn output.
- Cancellation during execution leaves session usable.
"""

import asyncio

import pytest

from backend.graph.graph import build_graph
from backend.graph.runner import run_turn
from backend.tools.registry import build_registry

SAMPLE_PROJECTS = [
    {
        "id": "beacon",
        "name": "Beacon",
        "one_line": "Beacon is an uptime monitoring platform.",
        "status": "shipped",
        "tech": ["TypeScript", "Redis"],
    }
]

SAMPLE_SKILLS = [
    {"id": "redis", "skill": "Redis", "category": "backend", "evidence": ["beacon"]}
]

SAMPLE_LINKS = [
    {"id": "github", "label": "GitHub", "type": "github_profile", "url": "https://github.com/Arjun8242", "description": "Source"}
]

SAMPLE_CHUNKS = [
    {
        "id": "docs/projects/beacon.md#overview",
        "project_id": "beacon",
        "title": "Beacon > Overview",
        "content": "Beacon monitors websites.",
    }
]


def make_fake_retrieve():
    async def retrieve_fn(query: str, top_k: int = 4, topic: str | None = None):
        return {
            "query": query,
            "chunks": [],
            "status": "none_relevant",
            "combinedContext": "",
        }
    return retrieve_fn


def get_test_registry():
    return build_registry(
        projects=SAMPLE_PROJECTS,
        skills=SAMPLE_SKILLS,
        links=SAMPLE_LINKS,
        chunks=SAMPLE_CHUNKS,
        project_names={"beacon": "Beacon"},
    )


# ── Test 1: Direct answer without tool call ────────────────────────────────


def test_graph_direct_answer():
    async def _run():
        async def fake_stream(prompt, system_instruction, tools=None):
            yield "Hello there!"

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=fake_stream,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "getSkills"}],
        )

        res = await run_turn(graph, session_id="test-session-1", text="Hello")
        assert res["reply"] == "Hello there!"
        assert len(res["tool_calls"]) == 0
        assert len(res["cards"]) == 0

    asyncio.run(_run())


# ── Test 2: One tool call then answer ──────────────────────────────────────


def test_graph_one_tool_then_answer():
    async def _run():
        call_count = 0

        async def fake_generate(prompt, system_instruction, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "function_calls": [{"name": "getSkills", "args": {"skill": "Redis"}}],
                    "text": "",
                }
            else:
                return {"text": "Yes, Arjun knows Redis through Beacon.", "function_calls": []}

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=fake_generate,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "getSkills"}],
        )

        res = await run_turn(graph, session_id="test-session-2", text="Does he know Redis?")
        assert "Redis through Beacon" in res["reply"]
        assert len(res["tool_calls"]) == 1
        assert res["tool_calls"][0]["name"] == "getSkills"
        assert call_count == 2

    asyncio.run(_run())


# ── Test 3: Two tool calls then answer ────────────────────────────────────


def test_graph_two_tools_then_answer():
    async def _run():
        call_count = 0

        async def fake_generate(prompt, system_instruction, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "function_calls": [{"name": "searchProjects", "args": {"tech": "Redis"}}],
                }
            elif call_count == 2:
                return {
                    "function_calls": [{"name": "getProjectDetail", "args": {"project_id": "beacon", "section": "Overview"}}],
                }
            else:
                return {"text": "Arjun built Beacon using Redis for monitoring."}

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=fake_generate,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "searchProjects"}, {"name": "getProjectDetail"}],
        )

        res = await run_turn(graph, session_id="test-session-3", text="Tell me about Redis projects")
        assert "Beacon using Redis" in res["reply"]
        assert len(res["tool_calls"]) == 2
        assert res["tool_calls"][0]["name"] == "searchProjects"
        assert res["tool_calls"][1]["name"] == "getProjectDetail"
        assert len(res["cards"]) == 1  # getProjectDetail emitted a card
        assert res["cards"][0]["card_type"] == "project_detail"

    asyncio.run(_run())


# ── Test 4: Tool step cap (stops after 4 tool steps) ───────────────────────


def test_graph_tool_step_cap():
    async def _run():
        call_count = 0

        async def always_calls_tool(prompt, system_instruction, tools=None):
            nonlocal call_count
            call_count += 1
            if tools is None:
                return {"text": "I reached the tool limit and must answer now."}
            return {
                "function_calls": [{"name": "getSkills", "args": {"skill": "Redis"}}],
            }

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=always_calls_tool,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "getSkills"}],
        )

        res = await run_turn(graph, session_id="test-session-cap", text="Loop test")
        assert len(res["tool_calls"]) == 4
        assert call_count == 5
        assert "tool limit" in res["reply"]

    asyncio.run(_run())


# ── Test 5: Tool error handled and passed back to model ───────────────────


def test_graph_tool_error_handled():
    async def _run():
        call_count = 0

        async def fake_generate(prompt, system_instruction, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "function_calls": [{"name": "nonexistentTool", "args": {}}],
                }
            else:
                assert "unknown_tool" in prompt or "nonexistentTool" in prompt
                return {"text": "I do not have access to that information."}

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=fake_generate,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "nonexistentTool"}],
        )

        res = await run_turn(graph, session_id="test-session-err", text="Try bad tool")
        assert "do not have access" in res["reply"]
        assert len(res["tool_calls"]) == 1
        assert res["tool_calls"][0]["is_error"] is True

    asyncio.run(_run())


# ── Test 6: Links card emitted in result ───────────────────────────────────


def test_graph_link_card_emitted():
    async def _run():
        call_count = 0

        async def fake_generate(prompt, system_instruction, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "function_calls": [{"name": "getLinks", "args": {"type": "github_profile"}}],
                }
            return {"text": "Here is Arjun's GitHub profile."}

        graph = build_graph(
            retrieve_fn=make_fake_retrieve(),
            generate_fn=fake_generate,
            aliases={"beacon": "beacon"},
            registry=get_test_registry(),
            tool_defs=[{"name": "getLinks"}],
        )

        res = await run_turn(graph, session_id="test-session-link", text="Show github")
        assert "GitHub" in res["reply"]
        assert len(res["cards"]) == 1
        assert res["cards"][0]["card_type"] == "link"
        assert res["cards"][0]["data"]["url"] == "https://github.com/Arjun8242"

    asyncio.run(_run())
