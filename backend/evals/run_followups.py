"""follow-up quality. The real interviewer model writes a follow-up to a scripted answer, and an
LLM judge reads it. Text only, no Sarvam.

    python -m backend.evals.run_followups [--runs 1] [--only <case id>] [--check]

Each case in followups.yaml is a one-topic plan run through the real interview graph: code asks the seed
question, the case's answer goes in, the model writes the follow-up. A case passes when
  - code: the follow-up is not empty, no control tag leaks into it, and it says nothing in must_not_contain
  - judge (followup_judge.md): it refers to the answer, invents no fact about the candidate, asks one question
(v2 design pass bar: "follow-up refers to the last answer; no fact outside the topic context").
The judge is rag/llm.py judge_text: GROQ_JUDGE_MODEL, a different model family from the interviewer, at temperature
0 in JSON mode, so it does not grade its own writing and a rerun gives the same verdict.
Target is followups.min_pass_rate in thresholds.yaml. Calls Groq twice per case per run (follow-up + judge).
Exit 1 below the target, 2 if followups.yaml is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

EVALS = Path(__file__).resolve().parent
CASES = EVALS / "followups.yaml"
JUDGE_PROMPT = EVALS / "followup_judge.md"
THRESHOLDS = EVALS / "thresholds.yaml"
KINDS = {"deep_dive", "technical", "achievement"}  # min_q 2: the model must write a follow-up, never move on
FIELDS = {"id", "persona", "kind", "title", "notes", "seed", "answer", "must_not_contain"}


class Verdict(BaseModel):
    refers_to_answer: bool
    invents_facts: bool
    one_question: bool
    reason: str = ""


def load_cases(path: Path = CASES) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(f"{path}: top level must be a list of cases")
    return data


def check_cases(cases: list[dict]) -> list[str]:
    errors, seen = [], set()
    for i, case in enumerate(cases):
        label = f"case {i} ({case.get('id', '?')})"
        if not case.get("id") or case["id"] in seen:
            errors.append(f"{label}: missing or duplicate id")
        seen.add(case.get("id"))
        if set(case) - FIELDS:
            errors.append(f"{label}: unknown fields {sorted(set(case) - FIELDS)}")
        if case.get("kind") not in KINDS or case.get("persona") not in {"neutral", "strict"}:
            errors.append(f"{label}: kind must be one of {sorted(KINDS)} and persona neutral or strict")
        if not all(str(case.get(key, "")).strip() for key in ("title", "notes", "seed", "answer")):
            errors.append(f"{label}: needs title, notes, seed and answer")
    return errors


def parse_verdict(text: str) -> Verdict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return Verdict.model_validate_json(text[start:end + 1])
    except ValidationError:
        return None


def judge_message(case: dict, follow_up: str) -> str:
    return (f"<notes>\n{case['notes'].strip()}\n</notes>\n\n<question>\n{case['seed']}\n</question>\n\n"
            f"<answer>\n{case['answer']}\n</answer>\n\n<next_turn>\n{follow_up}\n</next_turn>")


def code_problems(case: dict, follow_up: str) -> list[str]:
    problems = [] if follow_up.strip() else ["empty follow-up"]
    if "[[" in follow_up or "decision=" in follow_up:
        problems.append("control tag spoken")
    problems += [f"says '{s}'" for s in case.get("must_not_contain", []) if s.lower() in follow_up.lower()]
    return problems


def evaluate(case: dict, follow_up: str, verdict: Verdict | None) -> dict:
    notes = code_problems(case, follow_up)
    if verdict is None:
        notes.append("judge reply unreadable")
    else:
        notes += [label for label, bad in (("not about the answer", not verdict.refers_to_answer),
                                           ("invents a fact", verdict.invents_facts),
                                           ("not one question", not verdict.one_question)) if bad]
    return {"id": case["id"], "passed": not notes, "follow_up": follow_up,
            "note": "; ".join(notes) + (f" (judge: {verdict.reason})" if verdict and notes else "")}


async def follow_up_to(case: dict, graph) -> str:
    """What the interviewer says after the case's answer, in a fresh session."""
    from backend.interview.plan import make_topic

    topic = make_topic(case["kind"], "eval", case["title"], case["notes"], case["seed"])
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    await graph.ainvoke({"query": "", "topics": [topic], "persona": case["persona"]}, config)  # code asks the seed
    spoken = []
    async for mode, chunk in graph.astream({"query": case["answer"], "topics": [topic]}, config,
                                           stream_mode=["custom", "values"]):
        if mode == "custom":
            spoken.append(chunk["text"])
    return "".join(spoken).strip()


async def run(cases: list[dict], runs: int) -> list[dict]:
    from backend.graph.interview.graph import build_interview_graph
    from backend.rag.llm import judge_text, stream_text

    graph = build_interview_graph(stream_text)
    judge_prompt = JUDGE_PROMPT.read_text(encoding="utf-8").strip()
    results = []
    for case in cases:
        for _ in range(runs):
            follow_up = await follow_up_to(case, graph)
            verdict = parse_verdict(await judge_text(judge_message(case, follow_up), judge_prompt))
            results.append(evaluate(case, follow_up, verdict))
    return results


def report(results: list[dict], min_rate: float) -> int:
    for r in results:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['id']}\n        \"{r['follow_up']}\"")
        if r["note"]:
            print(f"        {r['note']}")
    rate = sum(r["passed"] for r in results) / len(results)
    print(f"\npass rate {rate:.0%} (target {min_rate:.0%})")
    return 0 if rate >= min_rate else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the follow-up quality eval (calls Groq).")
    p.add_argument("--runs", type=int, default=1, help="runs per case (default 1; each is 2 model calls)")
    p.add_argument("--only", help="run just this case id")
    p.add_argument("--check", action="store_true", help="only validate followups.yaml; no model calls")
    args = p.parse_args(argv)
    cases = load_cases()
    errors = check_cases(cases)
    if errors:
        print("\n".join(errors))
        return 2
    if args.check:
        print(f"followups.yaml: {len(cases)} cases, valid")
        return 0
    cases = [c for c in cases if not args.only or c["id"] == args.only]
    min_rate = (yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")) or {}).get("followups", {}).get("min_pass_rate", 0)
    return report(asyncio.run(run(cases, args.runs)), min_rate)


if __name__ == "__main__":
    sys.exit(main())
