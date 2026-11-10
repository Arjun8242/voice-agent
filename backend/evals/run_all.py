"""S17: one command for every eval suite, with a report stored per git commit.

    python -m backend.evals.run_all [--runs 3] [--suite routing booking ...]

Runs the four suites (routing, unanswerable, grounded, booking) through the real graph and LLM, prints each suite's
pass rate against its target in thresholds.yaml, and writes reports/<git sha>.json (a -dirty suffix
when the tree has uncommitted changes). It then lists every suite and category whose rate fell since
the previous report, so a regression shows up the day it happens. Exit 1 when a suite is below its
target, 2 when a case file is malformed. --suite runs only the named suites and updates just their entries in the
commit's report, so the suites can be run on different days (keep the code unchanged in between: the report is
named by the commit, with -dirty when uncommitted). All suites use a fake calendar, so a run never sends a real invite.
The retrieval smoke set (run_smoke) needs no LLM and runs on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.evals import run_booking, run_questions

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
# name -> (the runner, its case file); routing, unanswerable and grounded share the single-question runner
SUITES = {**{name: (run_questions, path) for name, path in run_questions.FILES.items()},
          "booking": (run_booking, run_booking.DEFAULT_FILE)}


def commit_name() -> str:
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return (git("rev-parse", "--short", "HEAD") or "nogit") + ("-dirty" if git("status", "--porcelain") else "")


def suite_report(results: list[dict], min_rate: float | None, runs: int = 3) -> dict:
    s = run_questions.summarise(results)
    failed = {}
    for r in results:
        if not r["passed"]:
            failed.setdefault(r["id"], {"id": r["id"], "note": r["note"], "reply": r.get("reply", "")[:200]})
    return {"runs": runs, "passed": s["passed"], "total": s["total"], "rate": round(s["rate"], 4), "min_rate": min_rate,
            "meets": None if min_rate is None else s["rate"] >= min_rate,
            "categories": s["categories"], "failed": list(failed.values())}


def regressions(old: dict, new: dict) -> list[str]:
    """Suites and categories whose pass rate is lower in `new` than in `old`."""
    lines = []
    for name, suite in new["suites"].items():
        before = old["suites"].get(name)
        if not before:
            continue
        if suite["rate"] < before["rate"]:
            lines.append(f"{name}: {before['rate']:.0%} -> {suite['rate']:.0%}")
        for cat, (ok, total) in suite["categories"].items():
            was = before["categories"].get(cat)
            if was and total and was[1] and ok / total < was[0] / was[1]:
                lines.append(f"  {name}/{cat}: {was[0] / was[1]:.0%} -> {ok / total:.0%}")
    return lines


async def run_everything(cases: dict[str, list[dict]], runs: int, names: list[str]) -> dict[str, list[dict]]:
    results = {}
    for name in names:
        print(f"\n=== {name}: {len(cases[name])} cases x {runs} runs ===", flush=True)
        results[name] = await SUITES[name][0].run(cases[name], runs)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the S17 eval suites and store the report.")
    p.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    p.add_argument("--suite", nargs="+", choices=list(SUITES), help="only these suites (default: all)")
    args = p.parse_args(argv)

    cases = {name: run_questions.load_cases(path) for name, (_, path) in SUITES.items()}
    problems = [f"{name}: {e}" for name, (module, _) in SUITES.items() for e in module.check_cases(cases[name])]
    if problems:
        print("Fix these before running:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2

    results = asyncio.run(run_everything(cases, args.runs, args.suite or list(SUITES)))

    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{commit_name()}.json"
    # a suite run on its own replaces only its entry: the other suites keep what an earlier run recorded
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"commit": path.stem, "suites": {}}
    report["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["suites"].update({name: suite_report(rs, run_questions.min_rate_for(name), args.runs) for name, rs in results.items()})
    others = sorted((f for f in REPORTS.glob("*.json") if f != path), key=lambda f: f.stat().st_mtime)
    previous = json.loads(others[-1].read_text(encoding="utf-8")) if others else None
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n=== report {report['commit']} ===")
    for name, s in report["suites"].items():
        target = "no target set" if s["min_rate"] is None else f"{'meets' if s['meets'] else 'BELOW'} target {s['min_rate']:.0%}"
        print(f"  {name:<12} {s['passed']}/{s['total']}  {s['rate']:.1%}  {target}  ({s.get('runs', '?')} runs per case)")
        for f in s["failed"]:
            print(f"      failed: {f['id']}: {f['note']}")
    if previous:
        drops = regressions(previous, report)
        print(f"\nCompared with {previous['commit']}: " + ("nothing got worse." if not drops else "\n  " + "\n  ".join(drops)))
    else:
        print("\nNo earlier report to compare with.")
    print(f"Saved {path.relative_to(ROOT)}")
    return 1 if any(s["meets"] is False for s in report["suites"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
