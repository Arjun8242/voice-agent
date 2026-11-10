"""

    python -m backend.evals.run_booking [--runs 3] [--only <case id>] [--file backend/evals/booking.yaml]

Each run is a fresh session, a fresh fake calendar and a throwaway SQLite file, so a run never sends a
real invite. Checks are code only (see booking.yaml). Reports and exits like run_questions: exit 1 when
below booking.min_pass_rate in thresholds.yaml, 2 when the case file is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from backend.evals.run_questions import KB_DIR, args_match, load_cases, min_rate_for, print_report

DEFAULT_FILE = Path(__file__).resolve().parent / "booking.yaml"
EVAL_TZ = "Asia/Kolkata" 


def check_cases(cases: list[dict]) -> list[str]:
    errors, seen = [], set()
    for i, c in enumerate(cases):
        label = f"case {i} ({c.get('id', '?')})"
        if not c.get("id") or c["id"] in seen:
            errors.append(f"{label}: missing or duplicate id")
        seen.add(c.get("id"))
        turns = c.get("turns")
        if not c.get("category") or not isinstance(turns, list) or not turns:
            errors.append(f"{label}: needs category and a list of turns")
        elif any(("user" in t) == ("ui" in t) for t in turns):
            errors.append(f"{label}: every turn needs exactly one of user or ui")
        if not isinstance(c.get("expect"), dict) or not c["expect"]:
            errors.append(f"{label}: needs expect")
    return errors


def evaluate(case: dict, last_turn: dict, final_state: str | None, events: int) -> dict:
    """Pass/fail for one run, with a note saying what was wrong."""
    expect, problems = case["expect"], []
    if expect.get("ask") and "?" not in last_turn.get("reply", ""):
        problems.append("expected a question back")
    if "last_tool" in expect and expect["last_tool"] is None:
        if last_turn.get("tool_calls"):
            problems.append(f"expected no tool in the last turn, got {[c['name'] for c in last_turn['tool_calls']]}")
    elif "last_tool" in expect:
        calls = [c for c in last_turn.get("tool_calls", []) if c["name"] == expect["last_tool"]]
        if not calls:
            problems.append(f"expected {expect['last_tool']} in the last turn, got {[c['name'] for c in last_turn.get('tool_calls', [])] or 'no tool'}")
        else:
            args = calls[-1]["args"]
            if not args_match(args, expect.get("args")):
                problems.append(f"wrong args: {args}")
            if "covers" in expect:  # the searched window must contain this time; zero-padded HH:MM strings compare correctly as text
                lo, hi = args.get("time_from"), args.get("time_to")
                if not (lo and hi and lo <= expect["covers"] <= hi):
                    problems.append(f"window {lo}-{hi} does not cover {expect['covers']}")
            if "weekday" in expect:
                try:
                    day = date.fromisoformat(args["date_from"]).strftime("%A")
                except (KeyError, TypeError, ValueError):
                    day = None
                if str(day).lower() != str(expect["weekday"]).lower():
                    problems.append(f"expected {expect['weekday']}, date_from was {args.get('date_from')} ({day})")
    if "must_not_match" in expect and re.search(expect["must_not_match"], last_turn.get("reply", "")):
        problems.append(f"reply matches {expect['must_not_match']!r}")
    if "final_state" in expect and final_state != expect["final_state"]:
        problems.append(f"final state {final_state}, expected {expect['final_state']}")
    if "calendar_events" in expect and events != expect["calendar_events"]:
        problems.append(f"{events} calendar events, expected {expect['calendar_events']}")
    return {"id": case["id"], "category": case["category"], "passed": not problems, "note": "; ".join(problems)}


async def run_case(case: dict, n: int, kb, sched, retrieve, generate, aliases) -> dict:
    from backend.booking.execute import BookingExecutor
    from backend.booking.store import BookingStore
    from backend.gcal import FakeCalendar
    from backend.graph.graph import build_graph
    from backend.graph.nodes.booking_gate import create_booking_gate_node
    from backend.graph.runner import run_turn
    from backend.tools.registry import build_registry

    calendar = FakeCalendar()
    for f in case.get("fail_next", []):
        calendar.fail_next(f["method"], f.get("code", "timeout"), f.get("after_effect", False))
    store = BookingStore(Path(tempfile.mkdtemp()) / "booking.db")
    registry = build_registry(kb, calendar=calendar, scheduling=sched, store=store)
    graph = build_graph(retrieve, generate, aliases, registry=registry, gate=create_booking_gate_node(store, calendar, sched))
    executor = BookingExecutor(store, calendar, sched)

    session, slots, booking_id, turn, errors = f"booking-{case['id']}-{n}", [], None, {}, []
    tz = case.get("timezone", EVAL_TZ)  # the visitor's timezone; the host's stays Asia/Kolkata
    for step in case["turns"]:
        if "user" in step:
            turn = await run_turn(graph, session, step["user"], visitor_timezone=tz)
        else:
            payload = dict(step["ui"].get("payload") or {})
            if "slot" in payload:
                payload["slot_id"] = slots[payload.pop("slot") - 1]
            elif booking_id:
                payload["booking_id"] = booking_id
            turn = await run_turn(graph, session, "", ui_action={"action": step["ui"]["action"], "payload": payload}, visitor_timezone=tz)
        errors += turn["errors"]
        if turn["booking_execute"]:
            await executor.run(turn["booking_execute"]["booking_id"], turn["booking_execute"]["kind"])
        for card in turn["cards"]:
            if card["type"] == "slots":
                slots = [s["slot_id"] for s in card["data"]["slots"]]
        booking = store.for_session(session)
        booking_id = booking["booking_id"] if booking else booking_id
    final_state = store.get(booking_id)["status"] if booking_id else None
    r = evaluate(case, turn, final_state, len(calendar.events))
    r["calls"], r["reply"], r["errors"] = [c["name"] for c in turn["tool_calls"]], turn["reply"], errors
    if errors:  # any turn, not just the last: a dead model can still "pass" checks like calendar_events == 0
        r["passed"], r["note"] = False, f"the model failed during the run: {errors[0][:140]}"
    return r


async def run(cases: list[dict], runs: int) -> list[dict]:
    from backend.rag.llm import stream_text
    from backend.rag.retriever import init_retriever, project_aliases, retrieve
    from backend.tools.kb_data import load_kb_data, load_scheduling

    await init_retriever()
    kb, sched, aliases = load_kb_data(KB_DIR), load_scheduling(KB_DIR), project_aliases()
    results = []
    for case in cases:
        for n in range(runs):
            r = await run_case(case, n, kb, sched, retrieve, stream_text, aliases)
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'}  {case['id']} #{n + 1}  {r['calls']}  {r['note']}", flush=True)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the S17 booking and multi-turn cases.")
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    p.add_argument("--only", help="run just this case id")
    args = p.parse_args(argv)

    cases = load_cases(args.file)
    problems = check_cases(cases)
    if problems:
        print("Fix these before running:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    print(f"{len(cases)} cases x {args.runs} runs")
    return print_report(asyncio.run(run(cases, args.runs)), min_rate_for("booking"), name="booking")


if __name__ == "__main__":
    sys.exit(main())
