"""S6: run the smoke set against the retriever.

    python -m evals.run_smoke [--k 4] [--index data/kb_index.json] [--file evals/smoke.yaml]

The retriever drops chunks below MIN_SCORE before returning them, which hides the
scores you need for tuning. So this runner turns the threshold off, fetches the raw
top-k once per question, and applies thresholds itself. It reports:
  1. pass/fail per question at the retriever's current MIN_SCORE
  2. a sweep over thresholds, and whether one threshold separates answerable from
     unanswerable questions
Exit code 1 if any counted question fails at the current threshold.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

TYPES = {"direct", "followup", "boundary", "unanswerable", "exploratory"}
ANSWERABLE = {"direct", "followup", "boundary"}
SWEEP = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 .. 0.80
DEFAULT_FILE = Path(__file__).resolve().parent / "smoke.yaml"
DEFAULT_INDEX = Path(__file__).resolve().parents[2] / "data" / "kb_index.json"


# ---------------------------------------------------------------------------
# Loading and checking the question file (no model needed)
# ---------------------------------------------------------------------------


def load_questions(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: top level must be a list of questions")
    return data


def check_questions(questions: list[dict]) -> list[str]:
    errors, seen = [], set()
    for i, q in enumerate(questions):
        label = f"question {i} ({q.get('id', '?')})"
        if not q.get("id"):
            errors.append(f"{label}: missing id")
        elif q["id"] in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(q.get("id"))
        if not str(q.get("query", "")).strip():
            errors.append(f"{label}: missing query")
        if q.get("type") not in TYPES:
            errors.append(f"{label}: type must be one of {sorted(TYPES)}")
            continue
        expect = q.get("expect") or []
        if q["type"] in ANSWERABLE and not expect:
            errors.append(f"{label}: needs a non-empty 'expect' list")
        if q["type"] not in ANSWERABLE and expect:
            errors.append(f"{label}: type '{q['type']}' must not have 'expect'")
        for e in expect:
            if not e.get("source") or not e.get("heading"):
                errors.append(f"{label}: each expect needs source and heading")
    return errors


def title_matches(title: str, heading: str) -> bool:
    t, h = title.lower().strip(), heading.lower().strip()
    return t == h or t.endswith(" > " + h)


def chunk_matches(chunk: dict, expect: dict) -> bool:
    meta = chunk.get("metadata", {})
    if meta.get("source") != expect["source"]:
        return False
    if not title_matches(meta.get("section", ""), expect["heading"]):
        return False
    text = chunk.get("text", "").lower()
    return all(w.lower() in text for w in expect.get("contains", []))


def check_labels(questions: list[dict], records: list[dict]) -> list[str]:
    """Every 'expect' must match a real chunk in the index, or the label is a typo."""
    errors = []
    for q in questions:
        for e in q.get("expect") or []:
            ok = any(
                r.get("source") == e["source"]
                and title_matches(r.get("title", ""), e["heading"])
                and all(w.lower() in r.get("content", "").lower() for w in e.get("contains", []))
                for r in records
            )
            if not ok:
                errors.append(f"{q['id']}: no chunk matches {e['source']} / '{e['heading']}'")
    return errors


# ---------------------------------------------------------------------------
# Scoring (pure functions, tested without the model)
# ---------------------------------------------------------------------------


def find_hit(chunks: list[dict], expect: list[dict]) -> tuple[int, dict] | None:
    """First chunk (1-based rank) that matches any acceptable evidence."""
    for rank, chunk in enumerate(chunks, start=1):
        if any(chunk_matches(chunk, e) for e in expect):
            return rank, chunk
    return None


def top_score(chunks: list[dict]) -> float:
    return max((c["score"] for c in chunks), default=0.0)


def evaluate(q: dict, chunks: list[dict], threshold: float) -> dict:
    """Judge one question at one threshold. passed is None for exploratory ones."""
    kept = [c for c in chunks if c["score"] >= threshold]
    if q["type"] == "exploratory":
        return {"passed": None, "rank": None, "score": top_score(chunks), "note": "inspect"}
    if q["type"] == "unanswerable":
        return {
            "passed": not kept,
            "rank": None,
            "score": top_score(chunks),
            "note": "" if not kept else f"returned '{kept[0]['metadata'].get('section')}'",
        }
    hit = find_hit(kept, q["expect"])
    if hit:
        return {"passed": True, "rank": hit[0], "score": hit[1]["score"], "note": ""}
    anywhere = find_hit(chunks, q["expect"])
    if anywhere:
        note = f"right chunk is rank {anywhere[0]} but scored {anywhere[1]['score']:.3f} < {threshold}"
    else:
        note = "right chunk not in top-k at all"
    return {"passed": False, "rank": None, "score": top_score(chunks), "note": note}


def sweep(questions: list[dict], results: dict[str, list[dict]]) -> dict:
    rows = []
    for t in SWEEP:
        ans = [evaluate(q, results[q["id"]], t)["passed"] for q in questions if q["type"] in ANSWERABLE]
        una = [evaluate(q, results[q["id"]], t)["passed"] for q in questions if q["type"] == "unanswerable"]
        rows.append({"t": t, "ans": sum(ans), "ans_n": len(ans), "una": sum(una), "una_n": len(una)})

    hit_scores, misses = {}, []
    for q in questions:
        if q["type"] in ANSWERABLE:
            hit = find_hit(results[q["id"]], q["expect"])
            (hit_scores.__setitem__(q["id"], hit[1]["score"]) if hit else misses.append(q["id"]))
    una_scores = {q["id"]: top_score(results[q["id"]]) for q in questions if q["type"] == "unanswerable"}

    lowest = min(hit_scores.items(), key=lambda kv: kv[1], default=None)
    highest = max(una_scores.items(), key=lambda kv: kv[1], default=None)
    window = None
    if lowest and highest and not misses and lowest[1] > highest[1]:
        window = (highest[1], lowest[1])
    return {"rows": rows, "lowest_hit": lowest, "highest_unanswerable": highest, "misses": misses, "window": window}


# ---------------------------------------------------------------------------
# Running against the real retriever
# ---------------------------------------------------------------------------


async def run(questions: list[dict], index: Path, k: int) -> tuple[dict[str, list[dict]], dict[str, str], float]:
    from backend.rag import retriever  # heavy import, kept out of module scope
    configured = retriever.MIN_SCORE
    await retriever.init_retriever(str(index))
    retriever.MIN_SCORE = 0.0  # see raw scores; thresholds are applied by this runner
    results = {}
    statuses = {}
    for q in questions:
        out = await retriever.retrieve(q["query"], top_k=k, topic=q.get("topic"))
        results[q["id"]] = out["chunks"]
        statuses[q["id"]] = out["status"]
    retriever.MIN_SCORE = configured
    return results, statuses, configured
    from backend.rag import retriever  # heavy import, kept out of module scope

    configured = retriever.MIN_SCORE
    await retriever.init_retriever(str(index))
    retriever.MIN_SCORE = 0.0  # see raw scores; thresholds are applied by this runner
    results = {}
    for q in questions:
        out = await retriever.retrieve(q["query"], top_k=k, topic=q.get("topic"))
        results[q["id"]] = out["chunks"]
    retriever.MIN_SCORE = configured
    return results, statuses, configured


def print_report(questions, results, statuses, threshold, k) -> int:
    print(f"\nSmoke set: {len(questions)} questions, top_k={k}, threshold={threshold}\n")
    failed = counted = 0
    for q in questions:
        r = evaluate(q, results[q["id"]], threshold)
        status = statuses[q["id"]]
        if r["passed"] is None:
            mark = "INFO"
        else:
            counted += 1
            mark = "PASS" if r["passed"] else "FAIL"
            failed += not r["passed"]

        print(f"{mark}  {q['id']:<28} {q['type']:<12} top={r['score']:.3f}  [{status}] {r['note']}")
        if r["passed"] is None or r["passed"] is False:
            for c in results[q["id"]][:3]:
                m = c["metadata"]
                print(f"        {c['score']:.3f}  {m.get('section')}  [{m.get('id')}]")
    print(f"\n{counted - failed}/{counted} counted questions pass at threshold {threshold}")

    s = sweep(questions, results)
    print("\nThreshold sweep (answerable retrieved / unanswerable rejected):")
    for row in s["rows"]:
        star = "  <- all pass" if row["ans"] == row["ans_n"] and row["una"] == row["una_n"] else ""
        print(f"  {row['t']:.2f}   {row['ans']}/{row['ans_n']}   {row['una']}/{row['una_n']}{star}")
    if s["misses"]:
        print(f"\nRetrieval misses (no threshold can fix these, look at the KB or chunking): {s['misses']}")
    if s["lowest_hit"] and s["highest_unanswerable"]:
        lq, lh = s["lowest_hit"], s["highest_unanswerable"]
        print(f"Lowest correct hit:        {lq[1]:.3f}  ({lq[0]})")
        print(f"Highest unanswerable top:  {lh[1]:.3f}  ({lh[0]})")
    if s["window"]:
        lo, hi = s["window"]
        print(f"Separable. Any threshold in ({lo:.3f}, {hi:.3f}) passes everything; midpoint {(lo + hi) / 2:.2f}.")
    elif s["lowest_hit"] and s["highest_unanswerable"]:
        print("Not cleanly separable with one threshold; see the two questions above.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the S6 smoke set.")
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--k", type=int, default=4, help="top_k to retrieve (default 4)")
    args = p.parse_args(argv)

    questions = load_questions(args.file)
    problems = check_questions(questions)
    if args.index.exists():
        raw = json.loads(args.index.read_text(encoding="utf-8"))
        problems += check_labels(questions, raw if isinstance(raw, list) else raw.get("chunks", []))
    else:
        problems.append(f"index not found: {args.index} (run python -m backend.kb.ingest first)")
    if problems:
        print("Fix these before running:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2

    results, statuses, threshold = asyncio.run(run(questions, args.index, args.k))
    return print_report(questions, results, statuses, threshold, args.k)


if __name__ == "__main__":
    sys.exit(main())
