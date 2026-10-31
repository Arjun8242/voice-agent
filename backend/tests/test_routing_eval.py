"""Tests for the routing eval logic and test cases (S9)."""

from pathlib import Path
import yaml
import pytest

from backend.evals.run_routing import evaluate_routing, load_yaml, DEFAULT_CASES, DEFAULT_THRESHOLDS


def test_routing_cases_file_is_valid():
    cases = load_yaml(DEFAULT_CASES)
    assert isinstance(cases, list)
    assert len(cases) >= 15  # Requirement: 15 to 40 cases

    ids = set()
    for c in cases:
        assert "id" in c
        assert c["id"] not in ids, f"Duplicate id: {c['id']}"
        ids.add(c["id"])
        assert "category" in c
        assert "query" in c
        assert "expected_tool" in c


def test_thresholds_file_is_valid():
    thresh = load_yaml(DEFAULT_THRESHOLDS)
    assert "routing" in thresh
    assert "overall_tool_accuracy_pct" in thresh["routing"]


def test_evaluate_routing_exact_match():
    case = {
        "id": "test-1",
        "category": "skill",
        "expected_tool": "getSkills",
        "expected_args": {"skill": "Redis"},
    }
    turn_res = {
        "tool_calls": [{"name": "getSkills", "args": {"skill": "Redis"}}],
        "reply": "Yes, Arjun knows Redis.",
    }
    r = evaluate_routing(case, turn_res)
    assert r["passed"] is True
    assert r["tool_passed"] is True
    assert r["args_passed"] is True


def test_evaluate_routing_wrong_tool():
    case = {
        "id": "test-2",
        "category": "skill",
        "expected_tool": "getSkills",
        "expected_args": {"skill": "Redis"},
    }
    turn_res = {
        "tool_calls": [{"name": "searchProjects", "args": {"tech": "Redis"}}],
        "reply": "Found Beacon.",
    }
    r = evaluate_routing(case, turn_res)
    assert r["passed"] is False
    assert r["tool_passed"] is False


def test_evaluate_routing_expected_refusal():
    case = {
        "id": "test-3",
        "category": "meeting",
        "expected_tool": None,
        "expect_refusal": True,
    }
    turn_res = {
        "tool_calls": [],
        "reply": "I cannot book meetings yet. Please contact Arjun directly.",
    }
    r = evaluate_routing(case, turn_res)
    assert r["passed"] is True
    assert r["refusal_passed"] is True

