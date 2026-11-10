"""Run one of the single-question suites through the real graph: retriever, LLM and tools.

    python -m backend.evals.run_questions --suite routing|unanswerable|grounded [--runs 3] [--only <case id>]

routing.yaml checks the tool and its arguments, unanswerable.yaml that the agent refuses or keeps a
boundary, grounded.yaml that the reply states the fact. Each case runs --runs times (design doc section 9:
3 for LLM cases), each run in a fresh session, through run_turn: the same call /internal/turn makes.
Booking tools are there too, on a fake calendar and a throwaway table, so the model sees the tools it has
live and a run never sends a real invite. Checks are code only. Reports pass counts per category and
overall, then compares the overall rate with <suite>.min_pass_rate in thresholds.yaml when one is set.
Exit 1 if below it, 2 if the case file is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import yaml

EVALS = Path(__file__).resolve().parent
FILES = {"routing": EVALS / "routing.yaml", "unanswerable": EVALS / "unanswerable.yaml", "grounded": EVALS / "grounded.yaml"}
THRESHOLDS = EVALS / "thresholds.yaml"
KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"
TOOLS = {"searchProjects", "getProjectDetail", "getSkills", "getLinks", "checkAvailability", "startBooking", "cancelBooking"}
KEYS = {"tool", "args", "ask", "must_include_any", "must_include_all", "refuses", "must_not_match"}
FALLBACK = "trouble answering"  # the agent's error reply (graph/nodes/agent.py): a turn that returns it answered nothing
# shortcut: a refusal is spotted by these phrases, so one worded differently fails; upgrade to an LLM judge if that happens often
REFUSALS = ["don't have", "do not have", "doesn't list", "does not list", "not listed", "no information", "can only speak",
            "doesn't mention", "does not mention", "not mentioned", "no record", "not something", "outside"]


def load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: top level must be a list of cases")
    return data


def check_cases(cases: list[dict]) -> list[str]:
    errors, seen = [], set()
    for i, c in enumerate(cases):
        label = f"case {i} ({c.get('id', '?')})"
        if not c.get("id") or c["id"] in seen:
            errors.append(f"{label}: missing or duplicate id")
        seen.add(c.get("id"))
        if not str(c.get("query", "")).strip() or not c.get("category"):
            errors.append(f"{label}: needs query and category")
        expect = c.get("expect")
        if not isinstance(expect, dict) or not expect or set(expect) - KEYS:
            errors.append(f"{label}: expect needs at least one of {sorted(KEYS)}, and nothing else")
            continue
        if expect.get("tool") is not None and expect["tool"] not in TOOLS:
            errors.append(f"{label}: unknown tool '{expect['tool']}'")
        if expect.get("args") and expect.get("tool") is None:
            errors.append(f"{label}: args given but no tool expected")
        if "must_not_match" in expect:
            try:
                re.compile(expect["must_not_match"])
            except re.error as err:
                errors.append(f"{label}: must_not_match is not a valid regex ({err})")
    return errors


def _same(actual, expected) -> bool:
    if expected is None:
        return actual is None
    options = expected if isinstance(expected, list) else [expected]
    return actual is not None and str(actual).strip().lower() in {str(o).lower() for o in options}


def args_match(actual: dict, expected: dict | list | None) -> bool:
    """expected: {arg: value | [values] | None}, or a list of such dicts (any one matching)."""
    if not expected:
        return True
    sets = expected if isinstance(expected, list) else [expected]
    return any(all(_same(actual.get(k), v) for k, v in s.items()) for s in sets)


def evaluate(case: dict, turn: dict) -> dict:
    """Pass/fail for one run of one case, with a note saying what was wrong."""
    expect, problems = case["expect"], []
    calls = turn.get("tool_calls", [])
    names = [c["name"] for c in calls]
    # the model writes narrow no-break spaces, non-breaking hyphens and curly apostrophes: fold them to plain characters
    reply = unicodedata.normalize("NFKC", turn.get("reply", "")).replace("’", "'")
    lower = reply.lower()

    if turn.get("errors") or FALLBACK in lower:
        problems.append(f"the turn failed: {turn.get('errors') or reply[:60]!r}")
    if "tool" in expect:
        if expect["tool"] is None and calls:
            problems.append(f"expected no tool, got {names}")
        elif expect["tool"] is not None:
            same_tool = [c for c in calls if c["name"] == expect["tool"]]
            if not same_tool:
                problems.append(f"expected {expect['tool']}, got {names or 'no tool'}")
            elif not any(args_match(c["args"], expect.get("args")) for c in same_tool):
                problems.append(f"wrong args: {[c['args'] for c in same_tool]}")
    if expect.get("ask") and "?" not in reply:
        problems.append("expected a clarifying question")
    if "must_include_any" in expect and not any(w.lower() in lower for w in expect["must_include_any"]):
        problems.append(f"reply has none of {expect['must_include_any']}")
    if "must_include_all" in expect and not all(w.lower() in lower for w in expect["must_include_all"]):
        problems.append(f"reply is missing one of {expect['must_include_all']}")
    if expect.get("refuses") and not any(p in lower for p in REFUSALS):
        problems.append("reply does not refuse")
    if "must_not_match" in expect and re.search(expect["must_not_match"], reply):
        problems.append(f"reply matches {expect['must_not_match']!r}")
    return {"id": case["id"], "category": case["category"], "passed": not problems, "note": "; ".join(problems), "calls": names}


def summarise(results: list[dict]) -> dict:
    by_cat: dict[str, list[int]] = {}
    for r in results:
        counts = by_cat.setdefault(r["category"], [0, 0])
        counts[0] += r["passed"]
        counts[1] += 1
    passed = sum(r["passed"] for r in results)
    return {"categories": by_cat, "passed": passed, "total": len(results), "rate": passed / len(results) if results else 0.0}


async def run(cases: list[dict], runs: int) -> list[dict]:
    # heavy imports kept out of module scope, so importing this file stays cheap
    from backend.booking.store import BookingStore
    from backend.gcal import FakeCalendar
    from backend.graph.graph import build_graph
    from backend.graph.runner import run_turn
    from backend.rag.llm import stream_text
    from backend.rag.retriever import init_retriever, project_aliases, retrieve
    from backend.tools.kb_data import load_kb_data, load_scheduling
    from backend.tools.registry import build_registry

    await init_retriever()
    store = BookingStore(Path(tempfile.mkdtemp()) / "questions.db")
    registry = build_registry(load_kb_data(KB_DIR), calendar=FakeCalendar(), scheduling=load_scheduling(KB_DIR), store=store)
    graph = build_graph(retrieve, stream_text, project_aliases(), registry=registry)
    results = []
    for case in cases:
        for n in range(runs):
            session = f"questions-{case['id']}-{n}"
            for text in case.get("before", []):  # earlier visitor messages in the same session
                await run_turn(graph, session_id=session, text=text)
            turn = await run_turn(graph, session_id=session, text=case["query"])
            r = evaluate(case, turn)
            r["reply"], r["errors"] = turn["reply"], turn["errors"]
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'}  {case['id']} #{n + 1}  {r['calls']}  {r['note']}", flush=True)
    return results


def print_report(results: list[dict], min_rate: float | None, name: str) -> int:
    s = summarise(results)
    print("\nPer category (passed / runs):")
    for cat, (ok, total) in s["categories"].items():
        print(f"  {cat:<16} {ok}/{total}  {ok / total:.0%}")
    print(f"Overall: {s['passed']}/{s['total']}  {s['rate']:.1%}")
    failed_ids = sorted({r["id"] for r in results if not r["passed"]})
    if failed_ids:
        print("\nFailed at least once:")
        for cid in failed_ids:
            r = next(r for r in results if r["id"] == cid and not r["passed"])
            print(f"  {cid}: {r['note']}  | reply: {r['reply'][:100]!r}" + (f"  | errors: {r['errors']}" if r["errors"] else ""))
    if min_rate is None:
        print(f"\nNo {name}.min_pass_rate in thresholds.yaml; nothing to compare against.")
        return 0
    verdict = "meets" if s["rate"] >= min_rate else "is BELOW"
    print(f"\nOverall rate {s['rate']:.1%} {verdict} the target {min_rate:.0%}.")
    return 0 if s["rate"] >= min_rate else 1


def min_rate_for(name: str) -> float | None:
    thresholds = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}
    return ((thresholds or {}).get(name) or {}).get("min_pass_rate")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run one single-question suite.")
    p.add_argument("--suite", choices=sorted(FILES), default="routing")
    p.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    p.add_argument("--only", help="run just this case id")
    args = p.parse_args(argv)

    cases = load_cases(FILES[args.suite])
    problems = check_cases(cases)
    if problems:
        print("Fix these before running:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    print(f"{len(cases)} cases x {args.runs} runs")
    return print_report(asyncio.run(run(cases, args.runs)), min_rate_for(args.suite), name=args.suite)


if __name__ == "__main__":
    sys.exit(main())
