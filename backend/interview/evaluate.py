"""evaluate.py: the end-of-interview report. One LLM call per interview (docs/interviewer-mode-plan.md §6.4).

The model scores each recorded answer against its topic's notes and lists what was right, missing,
wrong or unverifiable, each backed by a quote from the notes; then three tips.

Rules a reader would not guess (the model proposes, code decides):
- Every quote must really appear in its topic's notes. A point whose quote does not is dropped and
  counted in dropped_quotes: a missing point the notes never mention must not reach the candidate.
- Topic, question and answer text in the report come from the recorded answers, never from the model.
- Invalid JSON, or a review missing for some answer, gets one more try; then the report fails (None).
- No answers means no LLM call: the report is simply empty.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from backend.graph.interview.state import Answer
from backend.interview.plan import Topic

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluator.md"
MAX_ATTEMPTS = 2
MAX_TIPS = 3
EVALUATOR_MAX_TOKENS = 4096  # reasoning plus about 2k of JSON (plan §8.2); a spoken turn gets 512


class Point(BaseModel):
    point: str
    quote: str


class Claim(BaseModel):
    claim: str
    quote: str


class ModelReview(BaseModel):
    """One answer's review as the model writes it."""

    index: int
    score: int = Field(ge=1, le=5)
    correct_points: list[Point] = []
    missing_points: list[Point] = []
    incorrect_claims: list[Claim] = []
    unverifiable_claims: list[str] = []


class ModelReport(BaseModel):
    answers: list[ModelReview]
    tips: list[str] = []


class AnswerReview(BaseModel):
    """One answer's review as the browser gets it: the model's judgement on our own record of the answer."""

    topic_id: str
    topic: str
    question: str
    answer: str
    score: int
    correct_points: list[Point]
    missing_points: list[Point]
    incorrect_claims: list[Claim]
    unverifiable_claims: list[str]


class Report(BaseModel):
    reviews: list[AnswerReview]
    tips: list[str]
    average_score: float | None
    dropped_quotes: int  # points removed because their quote was not in the notes (an eval metric)


@lru_cache(maxsize=1)
def load_evaluator_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_evaluator_message(answers: list[Answer], topics: dict[str, Topic]) -> str:
    """Each topic's notes once, in the order the interview reached them, then the numbered answers."""
    used = list(dict.fromkeys(a["topic_id"] for a in answers))
    notes = [f"## Topic: {title_of(t, topics)}\nNotes:\n{topics[t]['text'] if t in topics else ''}" for t in used]
    numbered = [f"{i}. Topic: {title_of(a['topic_id'], topics)}\nQuestion: {a['question']}\nAnswer: {a['text']}"
                for i, a in enumerate(answers, start=1)]
    return "\n\n".join(notes) + "\n\n## Answers\n\n" + "\n\n".join(numbered)


def title_of(topic_id: str, topics: dict[str, Topic]) -> str:
    return topics[topic_id]["title"] if topic_id in topics else topic_id


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


def plain_words(text: str) -> str:
    """Lowercase words only, so a quote matches the notes whatever the punctuation or markdown."""
    return " ".join(re.sub(r"[^\w']+", " ", text.lower()).split())


def in_notes(quote: str, notes: str) -> bool:
    words = plain_words(quote)
    return bool(words) and words in plain_words(notes)


def ground(review: ModelReview, notes: str) -> tuple[ModelReview, int]:
    """The review with every point whose quote is not in the notes removed, and how many were removed."""
    correct = [p for p in review.correct_points if in_notes(p.quote, notes)]
    missing = [p for p in review.missing_points if in_notes(p.quote, notes)]
    incorrect = [c for c in review.incorrect_claims if in_notes(c.quote, notes)]
    dropped = (len(review.correct_points) - len(correct) + len(review.missing_points) - len(missing)
               + len(review.incorrect_claims) - len(incorrect))
    update = {"correct_points": correct, "missing_points": missing, "incorrect_claims": incorrect}
    return review.model_copy(update=update), dropped


def build_report(model_report: ModelReport, answers: list[Answer], topics: dict[str, Topic]) -> Report:
    reviews, dropped = [], 0
    for review in sorted(model_report.answers, key=lambda r: r.index):
        answer = answers[review.index - 1]
        grounded, removed = ground(review, topics[answer["topic_id"]]["text"] if answer["topic_id"] in topics else "")
        dropped += removed
        reviews.append(AnswerReview(
            topic_id=answer["topic_id"], topic=title_of(answer["topic_id"], topics), question=answer["question"],
            answer=answer["text"], score=grounded.score, correct_points=grounded.correct_points,
            missing_points=grounded.missing_points, incorrect_claims=grounded.incorrect_claims,
            unverifiable_claims=grounded.unverifiable_claims,
        ))
    tips = [t.strip() for t in model_report.tips if t.strip()][:MAX_TIPS]
    average = round(sum(r.score for r in reviews) / len(reviews), 1) if reviews else None
    return Report(reviews=reviews, tips=tips, average_score=average, dropped_quotes=dropped)


async def collect_text(pieces: AsyncIterator) -> str:
    """The model's text; its LlmUsage piece is not part of the JSON."""
    return "".join([piece async for piece in pieces if isinstance(piece, str)])


async def evaluate_interview(answers: list[Answer], topics: list[Topic], generate_fn: Callable) -> Report | None:
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces (rag/llm.py stream_text,
    given a larger max_tokens at startup). None when the model gave no valid report in MAX_ATTEMPTS tries."""
    if not answers:
        return Report(reviews=[], tips=[], average_score=None, dropped_quotes=0)
    by_id = {t["topic_id"]: t for t in topics}
    message = build_evaluator_message(answers, by_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = await collect_text(generate_fn(message, load_evaluator_prompt()))
        except Exception as err:  # a failed model call is retried like a bad reply; CancelledError passes through
            print(f"[evaluate] attempt {attempt}: {type(err).__name__}")
            continue
        parsed = parse_model_report(text, len(answers))
        if parsed is not None:
            return build_report(parsed, answers, by_id)
        print(f"[evaluate] attempt {attempt}: the reply was not a valid report")
    return None
