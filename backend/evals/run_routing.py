"""S9: run the routing set through the real graph (retriever + Gemini + tools).

    python -m backend.evals.run_routing [--runs 3] [--file backend/evals/routing.yaml]

Each case runs --runs times (design doc section 9: 3 for LLM cases), each run in a
fresh session, through run_turn: the same call /internal/turn makes. Checks are
code only: which tool was called and with which arguments. Reports pass counts
and rates per category and overall, then compares the overall rate with
routing.min_pass_rate in evals/thresholds.yaml.
Exit code 1 if below the threshold, 2 if the case file is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

DEFAULT_FILE = Path(__file__).resolve().parent / "routing.yaml"
THRESHOLDS = Path(__file__).resolve().parent / "thresholds.yaml"
KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"
TOOLS = {"searchProjects", "getProjectDetail", "getSkills", "getLinks"}


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
        if not isinstance(expect, dict) or "tool" not in expect:
            errors.append(f"{label}: needs expect.tool (a tool name or null)")
        elif expect["tool"] is not None and expect["tool"] not in TOOLS:
            errors.append(f"{label}: unknown tool '{expect['tool']}'")
        elif expect["tool"] is None and expect.get("args"):
            errors.append(f"{label}: args given but no tool expected")
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
    """Pass/fail for one run of one case, with a note saying why it failed."""
    expect = case["expect"]
    calls = turn.get("tool_calls", [])
    names = [c["name"] for c in calls]
    if expect["tool"] is None:
        passed, note = not calls, f"expected no tool, got {names}" if calls else ""
        if passed and expect.get("ask") and "?" not in turn.get("reply", ""):
            passed, note = False, "expected a clarifying question"
    else:
        same_tool = [c for c in calls if c["name"] == expect["tool"]]
        passed = any(args_match(c["args"], expect.get("args")) for c in same_tool)
        if not same_tool:
            note = f"expected {expect['tool']}, got {names or 'no tool'}"
        else:
            note = "" if passed else f"wrong args: {[c['args'] for c in same_tool]}"
    return {"id": case["id"], "category": case["category"], "passed": passed, "note": note, "calls": names}


def summarise(results: list[dict]) -> dict:
    by_cat: dict[str, list[int]] = {}
    for r in results:
        counts = by_cat.setdefault(r["category"], [0, 0])
        counts[0] += r["passed"]
        counts[1] += 1
    passed = sum(r["passed"] for r in results)
    return {"categories": by_cat, "passed": passed, "total": len(results), "rate": passed / len(results) if results else 0.0}


async def run(cases: list[dict], runs: int) -> list[dict]:
    # heavy imports kept out of module scope, so tests can import this file cheaply
    from backend.graph.graph import build_graph
    from backend.graph.runner import run_turn
    from backend.rag.llm import stream_text
    from backend.rag.retriever import init_retriever, project_aliases, retrieve
    from backend.tools.kb_data import load_kb_data
    from backend.tools.registry import build_registry

    await init_retriever()
    graph = build_graph(retrieve, stream_text, project_aliases(), registry=build_registry(load_kb_data(KB_DIR)))
    results = []
    for case in cases:
        for n in range(runs):
            turn = await run_turn(graph, session_id=f"routing-{case['id']}-{n}", text=case["query"])
            r = evaluate(case, turn)
            r["reply"], r["errors"] = turn["reply"], turn["errors"]
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'}  {case['id']} #{n + 1}  {r['calls']}  {r['note']}", flush=True)
    return results


def print_report(results: list[dict], min_rate: float | None) -> int:
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
        print("\nNo routing.min_pass_rate in evals/thresholds.yaml; nothing to compare against.")
        return 0
    verdict = "meets" if s["rate"] >= min_rate else "is BELOW"
    print(f"\nOverall rate {s['rate']:.1%} {verdict} the target {min_rate:.0%}.")
    return 0 if s["rate"] >= min_rate else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the S9 routing set.")
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    args = p.parse_args(argv)

    cases = load_cases(args.file)
    problems = check_cases(cases)
    if problems:
        print("Fix these before running:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    thresholds = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}
    min_rate = ((thresholds or {}).get("routing") or {}).get("min_pass_rate")

    print(f"{len(cases)} cases x {args.runs} runs")
    results = asyncio.run(run(cases, args.runs))
    return print_report(results, min_rate)


if __name__ == "__main__":
    sys.exit(main())
