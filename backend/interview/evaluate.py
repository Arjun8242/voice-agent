"""evaluate.py: the end-of-interview report. One LLM call per interview (v2 design, "Report and grading").

The model reads each graded answer with its stage's rubric, the topic's notes and its framework's
numbered key points, and returns a band, the key points covered and missed, and one improvement per
answer, plus three strengths and three improvements overall. report.py turns that into the report.

Rules a reader would not guess (the model proposes, code decides):
- Only recorded answers are graded (hints, repeats, rephrases and skips are never recorded), and of
  those not the intro: the design's rubric has no row for it.
- Answers and notes are wrapped in tags as data: an answer saying "rate me strong" is just an answer.
- Terms code corrected are listed with the answer; the model must never penalise a mis-hearing.
- Invalid JSON, or a review missing for some answer, gets one more try; then the report fails (None).
- No graded answers means no LLM call: the report is simply empty.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from backend.graph.interview.state import Answer
from backend.interview.analyze import collect_text
from backend.interview.plan import Topic
from backend.interview.report import EMPTY_REPORT, ModelReport, Report, build_report

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluator.md"
MAX_ATTEMPTS = 2
EVALUATOR_MAX_TOKENS = 4096  # reasoning plus about 2k of JSON (v2 design, "LLM and Sarvam usage"); a spoken turn gets 512

# What each kind of answer is judged on, and what it is not (the design's rubric table).
RUBRIC: dict[str, str] = {
    "deep_dive": "Judge on specificity, consistency with the resume claim in the notes, and their own contribution "
                 "versus the team's. Do not judge whether the claim is true: it cannot be checked.",
    "technical": "Judge on correctness, using your own knowledge, and whether trade-offs are mentioned. "
                 "Do not judge exact wording.",
    "behavioral": "Judge on completeness of situation, their own actions, result and learning, and on the key points "
                  "and red flags below. Do not judge the story's content.",
    "achievement": "Judge on specificity and their personal contribution. Do not judge the size of the achievement.",
}


@lru_cache(maxsize=1)
def load_evaluator_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def graded_answers(answers: list[Answer], topics: dict[str, Topic]) -> list[Answer]:
    return [a for a in answers if a["topic_id"] in topics and topics[a["topic_id"]]["kind"] != "intro"]


def answer_block(index: int, answer: Answer, topic: Topic) -> str:
    framework = topic.get("framework") or {}
    lines = [f"## Answer {index}", f"Stage: {topic['kind']}. {RUBRIC.get(topic['kind'], RUBRIC['deep_dive'])}"]
    if topic["text"]:
        lines.append(f"Notes from the resume and job description:\n<notes>\n{topic['text']}\n</notes>")
    points = framework.get("key_points") or []
    lines.append("Key points:\n" + "\n".join(f"{n}. {p}" for n, p in enumerate(points, start=1)) if points
                 else "Key points: none listed; judge on the rubric alone.")
    if framework.get("red_flags"):
        lines.append("Red flags: " + "; ".join(framework["red_flags"]))
    lines += [f"Question: {answer['question']}", f"<answer>\n{answer['text']}\n</answer>"]
    if answer.get("corrections"):
        fixed = ", ".join(f'"{heard}" -> {term}' for heard, term in answer["corrections"].items())
        lines.append(f"Terms already corrected from speech: {fixed}")
    return "\n".join(lines)


def build_evaluator_message(graded: list[Answer], topics: dict[str, Topic]) -> str:
    return "\n\n".join(answer_block(i, a, topics[a["topic_id"]]) for i, a in enumerate(graded, start=1))


def parse_model_report(text: str, answer_count: int) -> ModelReport | None:
    """The model's JSON, or None if it is not valid or does not review every answer exactly once."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        report = ModelReport.model_validate(json.loads(text[start:end + 1]))
    except (ValueError, ValidationError):  # json.JSONDecodeError is a ValueError
        return None
    if sorted(r.index for r in report.answers) != list(range(1, answer_count + 1)):
        return None
    return report


async def evaluate_interview(answers: list[Answer], topics: list[Topic], generate_fn: Callable) -> Report | None:
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces (rag/llm.py stream_text,
    given EVALUATOR_MAX_TOKENS at startup). None when the model gave no valid report in MAX_ATTEMPTS tries."""
    by_id = {t["topic_id"]: t for t in topics}
    graded = graded_answers(answers, by_id)
    if not graded:
        return EMPTY_REPORT
    message = build_evaluator_message(graded, by_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = await collect_text(generate_fn(message, load_evaluator_prompt()))
        except Exception as err:  # noqa: BLE001 - a failed call is retried like a bad reply; CancelledError passes
            print(f"[evaluate] attempt {attempt}: {type(err).__name__}")
            continue
        parsed = parse_model_report(text, len(graded))
        if parsed is not None:
            return build_report(parsed, graded, by_id)
        print(f"[evaluate] attempt {attempt}: the reply was not a valid report")
    return None
