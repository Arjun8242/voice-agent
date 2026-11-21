"""pacing across plan shapes and answer lengths. No LLM, no tokens, runs in seconds.

    python -m backend.evals.run_pacing

The flow tests (tests/interview/workflow/test_interview_flow.py) prove the budgets on one plan. This sweep asks
what they cannot: for each plan shape assembly can produce (full, no achievement stage, the fallback plan) and
two candidates (one whose answers always earn a follow-up, one whose answers always suffice), at answer lengths
from 30 s to 2 min, how many questions each stage got and how long the interview ran.

Pass bar (v2 design, "Testing and evals"): at answer lengths up to SECONDS_PER_QUESTION, which pacing is built
around, every stage gets at least its min_q and none passes its max_q, and the interview ends by the cap plus one
answer. Longer answers are reported, not failed: they show where stages start being dropped. Exit 1 on a failure.
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from collections.abc import AsyncIterator

from backend.config import INTERVIEW_MAX_SECONDS, SECONDS_PER_QUESTION
from backend.graph.interview.graph import build_interview_graph
from backend.interview.plan import Topic, intro_topic, make_topic

ANSWER_SECONDS = [30, 60, 75, 90, 120]
DEEP = make_topic("deep_dive", "beacon", "Beacon", "A job queue on Postgres and Redis.", "What does Beacon do?")
TECH = make_topic("technical", "kubernetes", "Kubernetes", "The job description asks for Kubernetes.",
                  "How would you deploy a service on Kubernetes?", source="gap")
BEHAVIORAL = make_topic("behavioral", "debugging", "how you work", "", "Tell me about a hard bug you fixed.")
ACHIEVEMENT = make_topic("achievement", "oss", "your open-source contribution", "A merged FastAPI PR.",
                         "Tell me about your FastAPI pull request.")
FALLBACK_DEEP = make_topic("deep_dive", "resume", "your resume", "The resume text.", "Walk me through your resume.")
SHAPES: dict[str, list[Topic]] = {
    "full": [intro_topic(), DEEP, TECH, BEHAVIORAL, ACHIEVEMENT],
    "no achievement": [intro_topic(), DEEP, TECH, BEHAVIORAL],
    "fallback": [intro_topic(), FALLBACK_DEEP, BEHAVIORAL],
}
CANDIDATES = {"earns follow-ups": "probe", "answers suffice": "next"}


START = 1000.0  # not 0: the graph reads a started_at of 0 as "not started yet"


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


def obedient_model(prefer: str):
    """An interviewer model that takes `prefer` whenever pacing offers it, else a follow-up."""
    def generate(prompt: str, system_instruction: str) -> AsyncIterator[str]:
        offered = re.search(r"Decisions allowed this turn: (.*)\.", prompt).group(1).split(", ")
        choice = prefer if prefer in offered else "probe"

        async def pieces():
            yield f"[[decision={choice}]]\n"
            yield "Thanks." if choice == "next" else "Why?"
        return pieces()
    return generate


async def interview(plan: list[Topic], prefer: str, answer_seconds: float) -> tuple[Counter, float]:
    """Questions answered per topic, and the minutes until the closing line."""
    clock = Clock()
    graph = build_interview_graph(obedient_model(prefer), clock=clock)
    config = {"configurable": {"thread_id": "pacing"}}
    state = await graph.ainvoke({"query": "", "topics": plan}, config)
    while not state.get("finished"):
        clock.now += answer_seconds
        state = await graph.ainvoke({"query": "A full answer.", "topics": plan}, config)
    return Counter(answer["topic_id"] for answer in state["answers"]), (clock.now - START) / 60


def problems(plan: list[Topic], asked: Counter, minutes: float, answer_seconds: float) -> list[str]:
    """Broken budgets; none are expected at answer lengths pacing is built for."""
    found = [f"{t['kind']} got {asked[t['topic_id']]} (min {t['min_q']}, max {t['max_q']})"
             for t in plan if not t["min_q"] <= asked[t["topic_id"]] <= t["max_q"]]
    if minutes * 60 > INTERVIEW_MAX_SECONDS + answer_seconds:
        found.append(f"ran {minutes:.1f} min, past the cap plus one answer")
    return found


def main() -> int:
    failures = 0
    for shape, plan in SHAPES.items():
        print(f"\n{shape}: " + ", ".join(f"{t['kind']} {t['min_q']}-{t['max_q']}" for t in plan))
        for candidate, prefer in CANDIDATES.items():
            for answer_seconds in ANSWER_SECONDS:
                asked, minutes = asyncio.run(interview(plan, prefer, answer_seconds))
                counts = " ".join(str(asked[t["topic_id"]]) for t in plan)
                found = problems(plan, asked, minutes, answer_seconds)
                counted = answer_seconds <= SECONDS_PER_QUESTION
                status = "ok" if not found else ("FAIL" if counted else "dropped")
                failures += counted and bool(found)
                note = "; ".join(found)
                print(f"  {candidate:<17} {answer_seconds:>4}s/answer  questions per stage {counts:<10} "
                      f"{sum(asked.values()):>2} total  {minutes:4.1f} min  {status}  {note}")
    print(f"\n{'PASS' if not failures else f'{failures} FAILED'}: answers up to {SECONDS_PER_QUESTION}s must keep every "
          "stage within its budget; longer answers are shown, not failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
