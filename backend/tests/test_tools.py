"""S9: the read-only tools and the registry, on a small in-memory KB.
The last tests load the real knowledge_base/ and are skipped if it is absent."""

import asyncio
import time
from pathlib import Path

import pytest

from backend.kb.validate import Experience, Link, Project, Skill
from backend.tools.kb_data import KbData, load_kb_data, project_sections
from backend.tools.registry import Tool, ToolRegistry, build_registry, load_descriptions
from backend.tools.schemas import Args, GetSkillsArgs

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTIONS = {n: f"{n} description" for n in ("searchProjects", "getProjectDetail", "getSkills", "getLinks")}


def project(pid, name, tech, status="shipped"):
    return Project.model_validate({
        "id": pid, "name": name, "one_line": f"{name} is a test project.", "status": status, "tech": tech,
        "role": "Built it.", "links": {"repo": f"https://example.com/{pid}"}, "highlights": ["h"], "updated": "2026-10-01",
    })


def make_kb() -> KbData:
    return KbData(
        projects=[project("beacon", "Beacon", ["TypeScript", "Redis"]),
                  project("valyrian", "Valyrian", ["Java"], status="runnable_not_deployed")],
        skills=[Skill(id="redis", skill="Redis", category="backend", evidence=["beacon", "acme"]),
                Skill(id="java", skill="Java", category="language", evidence=["valyrian"]),
                Skill(id="pg", skill="PostgreSQL", category="database", evidence=["beacon"]),
                Skill(id="gem", skill="Gemini AI Integration", category="ai", evidence=["beacon"])],
        links=[Link(id="gh", label="GitHub", type="github_profile", url="https://github.com/x", description="Code"),
               Link(id="li", label="LinkedIn", type="professional_profile", url="https://linkedin.com/x", description="Profile")],
        experience=[Experience.model_validate({
            "id": "acme", "organization": "Acme", "role": "Intern", "type": "internship", "start_date": "2025-01",
            "end_date": "2025-06", "current": False, "location": "Remote", "tech": ["Redis"], "one_line": "Intern.",
            "highlights": [{"id": "h1", "description": "Did work."}], "updated": "2026-10-01"})],
        sections={"beacon": {"Overview": "Beacon monitors sites.", "Limitations and Future Work": "No SSO."},
                  "valyrian": {"Overview": "An interpreter."}},
    )


@pytest.fixture
def registry():
    return build_registry(make_kb(), DESCRIPTIONS)


def run(registry, name, args):
    return asyncio.run(registry.execute(name, args))


# --- the tools --------------------------------------------------------------

def test_search_projects_filters_by_tech_whole_word(registry):
    rec = run(registry, "searchProjects", {"tech": "java"})
    assert [p["id"] for p in rec["result"]["projects"]] == ["valyrian"]  # not matched by 'TypeScript'
    assert rec["result"]["projects"][0]["status"] == "runnable_not_deployed"


def test_search_projects_query_matches_tech_and_no_args_lists_all(registry):
    assert [p["id"] for p in run(registry, "searchProjects", {"query": "redis"})["result"]["projects"]] == ["beacon"]
    assert len(run(registry, "searchProjects", {})["result"]["projects"]) == 2


def test_project_detail_maps_short_section_name_and_emits_card(registry):
    rec = run(registry, "getProjectDetail", {"project_id": "Beacon", "section": "limitations"})
    assert rec["ok"] and rec["result"]["section"] == "Limitations and Future Work"
    assert rec["result"]["text"] == "No SSO." and rec["result"]["links"]["repo"] == "https://example.com/beacon"
    assert [c["type"] for c in rec["cards"]] == ["project_detail"]


def test_project_detail_errors_name_the_valid_choices(registry):
    rec = run(registry, "getProjectDetail", {"project_id": "nope", "section": "Overview"})
    assert rec["result"]["error"] == "unknown_project" and "beacon" in rec["result"]["details"]
    rec = run(registry, "getProjectDetail", {"project_id": "valyrian", "section": "Architecture"})
    assert rec["result"]["error"] == "unknown_section" and "Overview" in rec["result"]["details"]
    assert rec["cards"] == []


def test_skill_lookup_by_name_alias_and_word(registry):
    found = run(registry, "getSkills", {"skill": "redis"})["result"]
    assert found["found"] and found["skills"][0]["skill"] == "Redis"
    assert [e["kind"] for e in found["skills"][0]["evidence"]] == ["project", "experience"]
    assert run(registry, "getSkills", {"skill": "Postgres"})["result"]["skills"][0]["skill"] == "PostgreSQL"
    assert run(registry, "getSkills", {"skill": "gemini"})["result"]["skills"][0]["skill"] == "Gemini AI Integration"


def test_unlisted_skill_is_explicit_and_reports_project_use(registry):
    k8s = run(registry, "getSkills", {"skill": "Kubernetes"})["result"]
    assert k8s == {"found": False, "skill": "Kubernetes", "used_in_projects": []}
    ts = run(registry, "getSkills", {"skill": "TypeScript"})["result"]  # in Beacon's tech list, not in skills
    assert ts["found"] is False and [p["id"] for p in ts["used_in_projects"]] == ["beacon"]


def test_all_skills_without_argument(registry):
    assert len(run(registry, "getSkills", {})["result"]["skills"]) == 4


def test_links_by_type_with_one_card_per_link(registry):
    rec = run(registry, "getLinks", {"type": "github_profile"})
    assert rec["result"]["links"][0]["url"] == "https://github.com/x"
    assert [c["card_id"] for c in rec["cards"]] == ["link:gh"]


# --- the registry -----------------------------------------------------------

def test_unknown_link_type_is_rejected_by_the_schema(registry):
    rec = run(registry, "getLinks", {"type": "twitter"})
    assert not rec["ok"] and rec["result"]["error"] == "invalid_args"


def test_unknown_tool_and_extra_args_return_errors_not_exceptions(registry):
    assert run(registry, "startBooking", {})["result"]["error"] == "unknown_tool"
    assert run(registry, "getSkills", {"skil": "Redis"})["result"]["error"] == "invalid_args"


def test_slow_handler_times_out():
    def slow(args, **_):
        time.sleep(0.3)
        return {}, []
    reg = ToolRegistry([Tool("slow", "d", Args, slow, timeout_s=0.05)])
    rec = asyncio.run(reg.execute("slow", {}))
    assert rec["result"]["error"] == "timeout" and rec["ms"] < 300


def test_handler_bug_becomes_tool_failed():
    def broken(args):
        raise KeyError("x")
    rec = asyncio.run(ToolRegistry([Tool("b", "d", Args, broken)]).execute("b", {}))
    assert rec["result"]["error"] == "tool_failed" and not rec["ok"]


def test_declarations_carry_schema_and_link_enum(registry):
    decl = {d["name"]: d for d in registry.declarations()}
    assert decl["getSkills"]["description"] == "getSkills description"
    assert decl["getSkills"]["parameters"]["properties"]["skill"]["description"] == GetSkillsArgs.model_fields["skill"].description
    assert decl["getLinks"]["parameters"]["properties"]["type"]["enum"] == ["github_profile", "professional_profile"]
    assert decl["getProjectDetail"]["parameters"]["required"] == ["project_id", "section"]


def test_missing_description_fails_at_build():
    with pytest.raises(ValueError, match="getLinks"):
        build_registry(make_kb(), {k: v for k, v in DESCRIPTIONS.items() if k != "getLinks"})


def test_project_sections_fold_subsections_under_level_two():
    md = "# P\nintro\n## Architecture\nTop.\n### Parser\nParses.\n## Overview\nO."
    assert project_sections(md) == {"Architecture": "Top.\n\nParser\n\nParses.", "Overview": "O."}


# --- against the real knowledge base ---------------------------------------

KB = ROOT / "knowledge_base"


@pytest.mark.skipif(not KB.exists(), reason="knowledge_base/ not present")
def test_real_kb_builds_with_the_real_descriptions():
    reg = build_registry(load_kb_data(KB), load_descriptions())
    assert set(reg.tools) == set(DESCRIPTIONS)


@pytest.mark.skipif(not KB.exists(), reason="knowledge_base/ not present")
def test_real_kb_every_project_has_overview_architecture_limitations():
    reg = build_registry(load_kb_data(KB), load_descriptions())
    for pid in reg.tools["getProjectDetail"].handler.keywords["kb"].sections:
        for section in ("Overview", "Architecture", "Limitations"):
            rec = asyncio.run(reg.execute("getProjectDetail", {"project_id": pid, "section": section}))
            assert rec["ok"] and rec["result"]["text"], (pid, section)
