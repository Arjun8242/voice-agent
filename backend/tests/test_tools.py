"""Unit tests for S9 tools and registry (no LLM, no network).

Covers:
- searchProjects: exact match, tech filter, query filter, empty matches.
- getProjectDetail: exact section, case normalization, unknown project (structured error),
  unknown section (returns available sections, no exception), cards.
- getSkills: all skills, specific skill evidence, alias handling (ts, js, postgres),
  unknown skill explicit not found.
- getLinks: existing links by type, unknown type returns available types.
- Registry: rejects unknown tools, validates args (Pydantic), per-tool timeout
  returns structured error, booking tools not registered.
"""

import asyncio
import time
from pathlib import Path

import pytest
import yaml

from backend.tools.links import get_links
from backend.tools.project_detail import get_project_detail
from backend.tools.registry import RegisteredTool, ToolRegistry, build_registry
from backend.tools.schemas import (
    GetLinksArgs,
    GetProjectDetailArgs,
    GetSkillsArgs,
    SearchProjectsArgs,
    ToolError,
)
from backend.tools.search_projects import search_projects
from backend.tools.skills import get_skills

# ── Fixtures with real-like data ──────────────────────────────────────────

SAMPLE_PROJECTS = [
    {
        "id": "beacon",
        "name": "Beacon",
        "one_line": "Beacon is a distributed uptime monitoring platform.",
        "status": "shipped",
        "tech": ["TypeScript", "Redis", "PostgreSQL", "Next.js"],
    },
    {
        "id": "fitai",
        "name": "FitAI",
        "one_line": "FitAI is a full-stack fitness platform with Google Gemini.",
        "status": "shipped",
        "tech": ["JavaScript", "MongoDB", "Express", "Docker"],
    },
    {
        "id": "valyrian",
        "name": "Valyrian",
        "one_line": "Valyrian is an interpreted programming language in Java.",
        "status": "runnable_not_deployed",
        "tech": ["Java", "Gradle"],
    },
]

SAMPLE_SKILLS = [
    {"id": "redis", "skill": "Redis", "category": "backend", "evidence": ["beacon"]},
    {"id": "typescript", "skill": "TypeScript", "category": "language", "evidence": ["beacon"]},
    {"id": "docker", "skill": "Docker", "category": "devops", "evidence": ["beacon", "fitai"]},
]

SAMPLE_LINKS = [
    {"id": "github", "label": "GitHub", "type": "github_profile", "url": "https://github.com/Arjun8242", "description": "Source code"},
    {"id": "resume", "label": "Resume", "type": "resume", "url": "https://example.com/resume.pdf", "description": "Resume"},
    {"id": "portfolio", "label": "Portfolio", "type": "portfolio", "url": "https://arjunbuilds.me", "description": "Portfolio"},
]

SAMPLE_CHUNKS = [
    {
        "id": "docs/projects/beacon.md#overview",
        "project_id": "beacon",
        "title": "Beacon > Overview",
        "content": "Beacon monitors websites and sends alerts.",
    },
    {
        "id": "docs/projects/beacon.md#architecture",
        "project_id": "beacon",
        "title": "Beacon > Architecture",
        "content": "Scheduler, queue, and worker pool stages.",
    },
    {
        "id": "docs/projects/beacon.md#architecture-p2",
        "project_id": "beacon",
        "title": "Beacon > Architecture (part 2)",
        "content": "Second part of Beacon architecture.",
    },
]

PROJECT_NAMES = {"beacon": "Beacon", "fitai": "FitAI", "valyrian": "Valyrian"}


# ── searchProjects tests ──────────────────────────────────────────────────


def test_search_projects_all():
    res = search_projects(SearchProjectsArgs(), projects=SAMPLE_PROJECTS)
    assert len(res.projects) == 3


def test_search_projects_by_tech():
    res = search_projects(SearchProjectsArgs(tech="redis"), projects=SAMPLE_PROJECTS)
    assert len(res.projects) == 1
    assert res.projects[0].id == "beacon"


def test_search_projects_by_query():
    res = search_projects(SearchProjectsArgs(query="interpreted"), projects=SAMPLE_PROJECTS)
    assert len(res.projects) == 1
    assert res.projects[0].id == "valyrian"


def test_search_projects_no_match():
    res = search_projects(SearchProjectsArgs(query="nonexistent_xyz"), projects=SAMPLE_PROJECTS)
    assert len(res.projects) == 0


# ── getProjectDetail tests ────────────────────────────────────────────────


def test_get_project_detail_exact():
    res = get_project_detail(
        GetProjectDetailArgs(project_id="beacon", section="Architecture"),
        projects=SAMPLE_PROJECTS,
        chunks=SAMPLE_CHUNKS,
    )
    assert not isinstance(res, ToolError)
    assert res.project_id == "beacon"
    assert "Scheduler" in res.content
    assert "Second part" in res.content  # multi-part chunks combined


def test_get_project_detail_case_insensitive():
    res = get_project_detail(
        GetProjectDetailArgs(project_id="BEACON", section="architecture"),
        projects=SAMPLE_PROJECTS,
        chunks=SAMPLE_CHUNKS,
    )
    assert not isinstance(res, ToolError)
    assert res.project_id == "beacon"


def test_get_project_detail_unknown_project():
    res = get_project_detail(
        GetProjectDetailArgs(project_id="unknown_proj", section="Architecture"),
        projects=SAMPLE_PROJECTS,
        chunks=SAMPLE_CHUNKS,
    )
    assert isinstance(res, ToolError)
    assert res.error == "unknown_project"
    assert "beacon" in res.details


def test_get_project_detail_unknown_section():
    res = get_project_detail(
        GetProjectDetailArgs(project_id="beacon", section="NonExistentSection"),
        projects=SAMPLE_PROJECTS,
        chunks=SAMPLE_CHUNKS,
    )
    assert isinstance(res, ToolError)
    assert res.error == "unknown_section"
    assert "Available" in res.details
    assert "Architecture" in res.details


# ── getSkills tests ───────────────────────────────────────────────────────


def test_get_skills_all():
    res = get_skills(GetSkillsArgs(), skills=SAMPLE_SKILLS, project_names=PROJECT_NAMES)
    assert res.found is True
    assert len(res.skills) == 3


def test_get_skills_exact_known():
    res = get_skills(GetSkillsArgs(skill="Redis"), skills=SAMPLE_SKILLS, project_names=PROJECT_NAMES)
    assert res.found is True
    assert len(res.skills) == 1
    assert res.skills[0].skill == "Redis"
    assert res.skills[0].evidence == ["Beacon"]


def test_get_skills_alias_ts():
    res = get_skills(GetSkillsArgs(skill="ts"), skills=SAMPLE_SKILLS, project_names=PROJECT_NAMES)
    assert res.found is True
    assert res.skills[0].skill == "TypeScript"


def test_get_skills_unknown():
    res = get_skills(GetSkillsArgs(skill="Kubernetes"), skills=SAMPLE_SKILLS, project_names=PROJECT_NAMES)
    assert res.found is False
    assert len(res.skills) == 0
    assert "does not list 'Kubernetes'" in res.message


# ── getLinks tests ────────────────────────────────────────────────────────


def test_get_links_github():
    res = get_links(GetLinksArgs(type="github_profile"), links=SAMPLE_LINKS)
    assert res.found is True
    assert len(res.links) == 1
    assert res.links[0].url == "https://github.com/Arjun8242"


def test_get_links_unknown_type():
    res = get_links(GetLinksArgs(type="myspace"), links=SAMPLE_LINKS)
    assert res.found is False
    assert "github_profile" in res.available_types
    assert "myspace" in res.message


# ── Registry tests ────────────────────────────────────────────────────────


def test_registry_registration_and_names():
    reg = build_registry(
        projects=SAMPLE_PROJECTS,
        skills=SAMPLE_SKILLS,
        links=SAMPLE_LINKS,
        chunks=SAMPLE_CHUNKS,
        project_names=PROJECT_NAMES,
    )
    assert set(reg.names) == {"searchProjects", "getProjectDetail", "getSkills", "getLinks"}
    # Booking tools MUST NOT be registered
    assert not reg.has("checkAvailability")
    assert not reg.has("startBooking")


def test_registry_unknown_tool():
    reg = ToolRegistry()
    err = reg.validate_args("mystery_tool", {})
    assert isinstance(err, ToolError)
    assert err.error == "unknown_tool"


def test_registry_invalid_args():
    reg = build_registry(
        projects=SAMPLE_PROJECTS,
        skills=SAMPLE_SKILLS,
        links=SAMPLE_LINKS,
        chunks=SAMPLE_CHUNKS,
        project_names=PROJECT_NAMES,
    )
    # getLinks requires 'type'
    err = reg.validate_args("getLinks", {})
    assert isinstance(err, ToolError)
    assert err.error == "invalid_args"


def test_registry_execution_success():
    async def _run():
        reg = build_registry(
            projects=SAMPLE_PROJECTS,
            skills=SAMPLE_SKILLS,
            links=SAMPLE_LINKS,
            chunks=SAMPLE_CHUNKS,
            project_names=PROJECT_NAMES,
        )
        res = await reg.execute("getSkills", {"skill": "Redis"})
        assert res.is_error is False
        assert res.result["found"] is True
        assert res.duration_ms >= 0

    asyncio.run(_run())


def test_registry_timeout_handling():
    async def _run():
        reg = ToolRegistry()

        def slow_fn(args):
            time.sleep(0.3)
            return {"done": True}

        from pydantic import BaseModel

        class DummyArgs(BaseModel):
            pass

        reg.register(
            RegisteredTool(
                name="slowTool",
                args_model=DummyArgs,
                handler=slow_fn,
                timeout=0.05,  # 50ms timeout
            )
        )

        res = await reg.execute("slowTool", {})
        assert res.is_error is True
        assert res.result["error"] == "timeout"

    asyncio.run(_run())
