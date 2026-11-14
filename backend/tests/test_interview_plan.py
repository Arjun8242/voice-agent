"""build_plan: which topics an interview covers, and the text each one is grounded in."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.interview.plan import build_plan
from backend.tests.helpers import make_kb, project
from backend.tools.kb_data import load_kb_data

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


def test_one_topic_per_project_in_kb_order_then_the_experience():
    plan = build_plan(make_kb())
    assert [t["topic_id"] for t in plan] == ["beacon", "valyrian", "experience:acme"]
    assert [t["title"] for t in plan] == ["Beacon", "Valyrian", "Acme"]


def test_a_project_topic_holds_every_section_of_its_document_under_its_heading():
    beacon = build_plan(make_kb())[0]
    assert beacon["text"] == "## Overview\nBeacon monitors sites.\n\n## Limitations and Future Work\nNo SSO."


def test_the_experience_topic_holds_the_role_summary_and_highlights():
    experience = build_plan(make_kb())[-1]
    assert experience["text"] == "Intern at Acme. Intern.\n- Did work."


def test_a_project_without_a_document_is_skipped():
    kb = make_kb()
    kb.projects.append(project("ghost", "Ghost", ["Go"]))  # in projects.yaml, but no sections
    assert "ghost" not in [t["topic_id"] for t in build_plan(kb)]


def test_extra_projects_are_cut_but_the_experience_topic_stays():
    kb = make_kb()
    for pid in ("p3", "p4", "p5"):
        kb.projects.append(project(pid, pid.upper(), ["Go"]))
        kb.sections[pid] = {"Overview": f"{pid} overview."}
    plan = build_plan(kb, max_topics=4)
    assert [t["topic_id"] for t in plan] == ["beacon", "valyrian", "p3", "experience:acme"]


def test_without_experience_every_slot_goes_to_projects():
    plan = build_plan(replace(make_kb(), experience=[]))
    assert [t["topic_id"] for t in plan] == ["beacon", "valyrian"]


def test_a_cap_of_one_keeps_only_the_experience():
    assert [t["topic_id"] for t in build_plan(make_kb(), max_topics=1)] == ["experience:acme"]


def test_the_real_knowledge_base_gives_three_projects_and_the_internship():
    # guards the plan against KB edits: a renamed file or emptied document shows up here
    plan = build_plan(load_kb_data(KB_DIR))
    assert [t["topic_id"] for t in plan] == ["beacon", "fitai", "valyrian", "experience:experience"]
    for topic in plan[:3]:
        assert topic["text"].startswith("## Overview\n") and len(topic["text"]) > 2000
    assert plan[3]["title"] == "LifeLinkr"
