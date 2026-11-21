"""the real résumé analysis call on fixture résumés and job descriptions -> interview plans.

    python -m backend.evals.run_plans [--runs 1] [--only <case id>] [--check]

a file the upload refuses (a scan, not a PDF) must be refused with the expected code, before any model call.
Each case then goes through what POST /interview/upload does: contacts stripped, one analysis call (one retry
on bad JSON), claim verification, plan assembly. Checks are code only:
  - valid: the model returned schema-valid JSON within the retry (else the upload would use the fallback plan)
  - stages: the plan has exactly the expected stage kinds, plus any of optional_stages (for a real résumé where
    reasonable interviewers could disagree, such as whether a hackathon placing is an achievement)
  - deep dive: the deep-dive topic is about one of the expected roles or projects
  - technical: with a JD, the technical topic is one of the expected requirements (gaps first)
  - injection: text the résumé tried to inject appears nowhere in the plan
Also reported: the share of the model's claims kept by verification. Kept claims are in the résumé by
construction; a low keep rate means the model misquotes or invents, and the plan loses material.
Targets are plans.min_pass_rate and plans.min_claim_keep_rate in thresholds.yaml. Calls Groq: one or two
analysis calls per case per run. Exit 1 below a target, 2 if plans.yaml is malformed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from functools import partial
from pathlib import Path

import yaml

EVALS = Path(__file__).resolve().parent
CASES = EVALS / "plans.yaml"
ROOT = EVALS.parents[1]
REAL_CASES = ROOT / "data" / "eval_resumes.yaml"  # optional; pdf paths in it are relative to the repo root
THRESHOLDS = EVALS / "thresholds.yaml"
EXPECT_KEYS = {"stages", "optional_stages", "deep_dive_any", "technical_any", "must_not_contain", "rejected"}
KINDS = {"intro", "deep_dive", "technical", "behavioral", "achievement"}


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
        if bool(case.get("pdf")) == bool(case.get("resume")):
            errors.append(f"{label}: give either resume (text) or pdf (a path), not both")
        elif case.get("pdf") and not (ROOT / case["pdf"]).is_file():
            errors.append(f"{label}: no file at {case['pdf']}")
        elif case.get("resume") and len(case["resume"].strip()) < 300:
            errors.append(f"{label}: resume shorter than the upload's 300-character minimum")
        expect = case.get("expect") or {}
        stages = set(expect.get("stages", [])) | set(expect.get("optional_stages", []))
        if set(expect) - EXPECT_KEYS or not stages <= KINDS or not (expect.get("stages") or expect.get("rejected")):
            errors.append(f"{label}: expect needs stages from {sorted(KINDS)} (or rejected), and only keys {sorted(EXPECT_KEYS)}")
        if expect.get("technical_any") and not str(case.get("job_description", "")).strip():
            errors.append(f"{label}: technical_any is for cases with a job description")
    return errors


def claims_of(analysis) -> list:
    roles = [*analysis.projects, *analysis.experience]
    return [claim for role in roles for claim in role.claims] + analysis.achievements + analysis.oss_contributions


def has_any(text: str, words: list[str]) -> bool:
    return any(word.lower() in text.lower() for word in words)


def plan_text(plan) -> str:
    topics = " ".join(f"{t['title']} {t['text']} {t['seed_question']}" for t in plan["topics"])
    return f"{plan['profile_summary']} {topics}"


def evaluate(case: dict, raw, analysis, plan) -> dict:
    """Code checks on one case's analysis and plan; raw is the model's last reply before verification."""
    expect, notes = case["expect"], []
    total = len(claims_of(raw)) if raw else 0
    kept = len(claims_of(analysis)) if analysis else 0
    if analysis is None:
        return {"id": case["id"], "passed": False, "kept": kept, "total": total, "note": "no valid JSON in 2 tries"}
    by_kind = {t["kind"]: t for t in plan["topics"]}
    extra = set(by_kind) - set(expect["stages"]) - set(expect.get("optional_stages", []))
    if not set(expect["stages"]) <= set(by_kind) or extra:
        notes.append(f"stages {sorted(by_kind)}, expected {sorted(expect['stages'])}")
    deep = by_kind.get("deep_dive")
    if deep and not has_any(f"{deep['title']} {deep['text']}", expect.get("deep_dive_any", [])):
        notes.append(f"deep dive on '{deep['title']}'")
    tech = by_kind.get("technical")
    if expect.get("technical_any") and not (tech and has_any(tech["title"], expect["technical_any"])):
        notes.append(f"technical on '{tech['title'] if tech else None}'")
    leaked = [s for s in expect.get("must_not_contain", []) if s.lower() in plan_text(plan).lower()]
    if leaked:
        notes.append(f"injected text in the plan: {leaked}")
    return {"id": case["id"], "passed": not notes, "kept": kept, "total": total, "note": "; ".join(notes)}


async def run_case(case: dict, generate) -> dict:
    from backend.interview.analyze import analyze, parse_analysis
    from backend.interview.assemble import assemble_plan
    from backend.interview.resume import (
        MAX_RESUME_CHARS,
        ResumeError,
        clean_job_description,
        clean_resume,
        strip_contacts,
    )

    replies: list[str] = []

    def recording(prompt: str, system_instruction: str):
        async def pieces():
            async for piece in generate(prompt, system_instruction):
                if isinstance(piece, str):
                    replies.append(piece)
                yield piece
        replies.clear()  # keep only the latest attempt's reply
        return pieces()

    if case.get("pdf"):
        try:
            resume = clean_resume((ROOT / case["pdf"]).read_bytes())
        except ResumeError as err:  # refused like the upload refuses it: right only if the case expects it
            expected = case["expect"].get("rejected")
            note = "" if err.code == expected else f"upload refused it: {err.code}"
            return {"id": case["id"], "passed": err.code == expected, "kept": 0, "total": 0, "note": note}
        if case["expect"].get("rejected"):
            return {"id": case["id"], "passed": False, "kept": 0, "total": 0, "note": "upload accepted it"}
    else:
        resume = strip_contacts(case["resume"]).strip()[:MAX_RESUME_CHARS]
    analysis = await analyze(resume, clean_job_description(case.get("job_description") or ""), recording)
    raw = parse_analysis("".join(replies))
    plan = assemble_plan(analysis, choose=lambda options: options[0]) if analysis else None
    return evaluate(case, raw, analysis, plan)


async def run(cases: list[dict], runs: int) -> list[dict]:
    from backend.interview.analyze import ANALYSIS_MAX_TOKENS
    from backend.rag.llm import stream_text

    generate = partial(stream_text, max_tokens=ANALYSIS_MAX_TOKENS)
    return [await run_case(case, generate) for case in cases for _ in range(runs)]


def report(results: list[dict], targets: dict) -> int:
    for r in results:
        rate = f"{r['kept']}/{r['total']} claims kept"
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['id']:<30} {rate:<20} {r['note']}")
    passed = sum(r["passed"] for r in results) / len(results)
    total = sum(r["total"] for r in results)
    keep = sum(r["kept"] for r in results) / total if total else None  # None: only refused files, no claims
    min_pass, min_keep = targets.get("min_pass_rate", 0), targets.get("min_claim_keep_rate", 0)
    kept = "n/a" if keep is None else f"{keep:.0%}"
    print(f"\npass rate {passed:.0%} (target {min_pass:.0%}), claims kept {kept} (target {min_keep:.0%})")
    return 0 if passed >= min_pass and (keep is None or keep >= min_keep) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the plan eval (calls Groq).")
    p.add_argument("--runs", type=int, default=1, help="runs per case (default 1; each is 1-2 analysis calls)")
    p.add_argument("--only", help="run just this case id")
    p.add_argument("--check", action="store_true", help="only validate plans.yaml; no model calls")
    args = p.parse_args(argv)
    cases = load_cases() + (load_cases(REAL_CASES) if REAL_CASES.is_file() else [])
    errors = check_cases(cases)
    if errors:
        print("\n".join(errors))
        return 2
    if args.check:
        real = sum(bool(case.get("pdf")) for case in cases)
        print(f"{len(cases)} cases ({real} real PDFs), valid")
        return 0
    cases = [c for c in cases if not args.only or c["id"] == args.only]
    targets = (yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")) or {}).get("plans", {})
    return report(asyncio.run(run(cases, args.runs)), targets)


if __name__ == "__main__":
    sys.exit(main())
