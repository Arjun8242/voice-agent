"""S9: the routing runner's checks, and the routing set itself (no model needed)."""

from pathlib import Path

from backend.evals import run_routing as rr


def turn(*calls, reply="ok"):
    return {"reply": reply, "tool_calls": [{"name": n, "args": a} for n, a in calls]}


CASE = {"id": "c", "category": "skill", "query": "q", "expect": {"tool": "getSkills", "args": {"skill": ["Postgres", "PostgreSQL"]}}}


def test_right_tool_and_any_listed_value_passes_case_insensitively():
    assert rr.evaluate(CASE, turn(("getSkills", {"skill": "postgresql"})))["passed"]


def test_wrong_args_and_wrong_tool_fail_with_a_note():
    r = rr.evaluate(CASE, turn(("getSkills", {"skill": "MySQL"})))
    assert not r["passed"] and r["note"].startswith("wrong args")
    r = rr.evaluate(CASE, turn(("searchProjects", {})))
    assert not r["passed"] and "expected getSkills" in r["note"]


def test_expected_call_may_follow_another_call():
    case = {**CASE, "expect": {"tool": "getProjectDetail", "args": {"project_id": "beacon"}}}
    assert rr.evaluate(case, turn(("searchProjects", {}), ("getProjectDetail", {"project_id": "beacon", "section": "Overview"})))["passed"]


def test_null_arg_means_absent_and_arg_sets_are_alternatives():
    case = {**CASE, "expect": {"tool": "getSkills", "args": {"skill": None}}}
    assert rr.evaluate(case, turn(("getSkills", {})))["passed"]
    assert not rr.evaluate(case, turn(("getSkills", {"skill": "Redis"})))["passed"]
    case = {**CASE, "expect": {"tool": "searchProjects", "args": [{"tech": "Redis"}, {"query": "Redis"}]}}
    assert rr.evaluate(case, turn(("searchProjects", {"query": "redis"})))["passed"]


def test_no_tool_and_ask_cases():
    none = {**CASE, "expect": {"tool": None}}
    assert rr.evaluate(none, turn())["passed"]
    assert not rr.evaluate(none, turn(("getLinks", {"type": "resume"})))["passed"]
    ask = {**CASE, "expect": {"tool": None, "ask": True}}
    assert rr.evaluate(ask, turn(reply="Which project do you mean?"))["passed"]
    assert not rr.evaluate(ask, turn(reply="Sure."))["passed"]


def test_summary_counts_per_category():
    s = rr.summarise([{"category": "a", "passed": True}, {"category": "a", "passed": False}, {"category": "b", "passed": True}])
    assert s["categories"] == {"a": [1, 2], "b": [1, 1]} and s["passed"] == 2 and s["total"] == 3


def test_check_cases_catches_bad_entries():
    bad = [{"id": "x", "category": "c", "query": "q", "expect": {"tool": "startBooking"}},
           {"id": "x", "category": "c", "query": "q", "expect": {"tool": None, "args": {"a": 1}}}]
    errors = rr.check_cases(bad)
    assert any("unknown tool" in e for e in errors) and any("duplicate" in e for e in errors) and any("args given" in e for e in errors)


def test_routing_set_is_well_formed():
    cases = rr.load_cases(rr.DEFAULT_FILE)
    assert rr.check_cases(cases) == []
    assert 15 <= len(cases) <= 40  # design doc section 9
