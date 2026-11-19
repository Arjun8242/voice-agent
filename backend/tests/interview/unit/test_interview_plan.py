"""The plan: stage budgets on every topic, stage order, and build_plan, the temporary knowledge-base
plan every session gets until the resume upload (phase 3) replaces it."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.interview.plan import STAGES, build_plan, intro_topic, make_topic, order_plan
from backend.tests.helpers import make_kb, project
from backend.tools.kb_data import load_kb_data

KB_DIR = Path(__file__).resolve().parents[4] / "knowledge_base"


def ids(plan) -> list[str]:
    """Topic ids after the intro, without their kind prefix."""
    return [t["topic_id"].split(":", 1)[1] for t in plan[1:]]


def test_every_topic_carries_its_stages_budget():
    topic = make_topic("behavioral", "conflict", "a disagreement", "", "Tell me about a disagreement.")
    assert (topic["topic_id"], topic["min_q"], topic["max_q"], topic["max_level"]) == ("behavioral:conflict", 1, 2, 3)
    assert set(STAGES) == {"intro", "deep_dive", "technical", "behavioral", "achievement"}


def test_topics_are_put_in_stage_order_and_a_stage_without_topics_is_left_out():
    tech = make_topic("technical", "sql", "SQL", "", "How do indexes work?")
    deep = make_topic("deep_dive", "beacon", "Beacon", "", "What does Beacon do?")
    assert [t["kind"] for t in order_plan([tech, deep, intro_topic()])] == ["intro", "deep_dive", "technical"]


def test_one_topic_per_project_in_kb_order_then_the_experience_after_the_intro():
    plan = build_plan(make_kb())
    assert plan[0]["kind"] == "intro" and ids(plan) == ["beacon", "valyrian", "acme"]
    assert [t["title"] for t in plan[1:]] == ["Beacon", "Valyrian", "Acme"]
    assert all(t["kind"] == "deep_dive" and t["seed_question"] for t in plan[1:])


def test_a_project_topic_holds_every_section_of_its_document_under_its_heading():
    beacon = build_plan(make_kb())[1]
    assert beacon["text"] == "## Overview\nBeacon monitors sites.\n\n## Limitations and Future Work\nNo SSO."


def test_the_experience_topic_holds_the_role_summary_and_highlights():
    experience = build_plan(make_kb())[-1]
    assert experience["text"] == "Intern at Acme. Intern.\n- Did work."


def test_a_project_without_a_document_is_skipped():
    kb = make_kb()
    kb.projects.append(project("ghost", "Ghost", ["Go"]))  # in projects.yaml, but no sections
    assert "ghost" not in ids(build_plan(kb))


def test_extra_projects_are_cut_but_the_experience_topic_stays():
    kb = make_kb()
    for pid in ("p3", "p4", "p5"):
        kb.projects.append(project(pid, pid.upper(), ["Go"]))
        kb.sections[pid] = {"Overview": f"{pid} overview."}
    assert ids(build_plan(kb, max_topics=4)) == ["beacon", "valyrian", "p3", "acme"]


def test_without_experience_every_slot_goes_to_projects():
    assert ids(build_plan(replace(make_kb(), experience=[]))) == ["beacon", "valyrian"]


def test_the_real_knowledge_base_gives_three_projects_and_the_internship():
    # guards the plan against KB edits: a renamed file or emptied document shows up here
    plan = build_plan(load_kb_data(KB_DIR))
    assert ids(plan) == ["beacon", "fitai", "valyrian", "experience"]
    for topic in plan[1:4]:
        assert topic["text"].startswith("## Overview\n") and len(topic["text"]) > 2000
    assert plan[4]["title"] == "LifeLinkr"
