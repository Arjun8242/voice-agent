"""report.py: the end-of-interview report: what the evaluator model returns, and what the browser gets.

The model only judges: a band per answer, which of the topic's key points the answer covered (by
number), one improvement, and three strengths and improvements overall. Code builds everything else
from its own records (v2 design, "Report and grading"):
- question, answer, framework, gap flag and transcription corrections come from the session, never
  from the model;
- covered and missed are the framework's own key-point text, picked by the model's numbers; a number
  outside the list is ignored, and a point marked both covered and missed counts as covered;
- each stage's band is the average of its answers' bands (strong 2, ok 1, weak 0), rounded half up.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Band = Literal["strong", "ok", "weak"]
BAND_VALUE: dict[str, int] = {"weak": 0, "ok": 1, "strong": 2}
MAX_OVERALL_ITEMS = 3


class HeardAs(BaseModel):
    """A term speech-to-text got wrong: what was heard, and what it meant."""

    heard: str
    read_as: str


class ModelReview(BaseModel):
    """One answer's judgement as the model writes it."""

    index: int
    band: Band
    covered: list[int] = []  # 1-based numbers of the topic's key points
    missed: list[int] = []
    improvement: str
    read_by_meaning: list[HeardAs] = []


class ModelReport(BaseModel):
    answers: list[ModelReview]
    strengths: list[str] = []
    improvements: list[str] = []


class Framework(BaseModel):
    key_points: list[str] = []
    red_flags: list[str] = []
    star: str = ""
    likely_followups: list[str] = []


class AnswerReview(BaseModel):
    """One graded answer as the browser shows it."""

    topic_id: str
    topic: str
    kind: str
    question: str
    answer: str  # as transcribed, after code's glossary corrections
    band: Band
    framework: Framework
    covered: list[str]
    missed: list[str]
    improvement: str
    gap: bool  # the topic is a job requirement the resume did not show
    corrected: list[HeardAs]  # terms code fixed before anyone read the answer
    read_by_meaning: list[HeardAs]  # terms the evaluator read by meaning; never penalised


class StageBand(BaseModel):
    kind: str
    band: Band


class Report(BaseModel):
    reviews: list[AnswerReview]
    stages: list[StageBand]
    strengths: list[str]
    improvements: list[str]
    gaps_touched: list[str]  # titles of gap topics the interview asked about


EMPTY_REPORT = Report(reviews=[], stages=[], strengths=[], improvements=[], gaps_touched=[])


def pick_points(numbers: list[int], key_points: list[str]) -> list[str]:
    """The key points with these 1-based numbers, in the framework's order, each once."""
    wanted = {n for n in numbers if 1 <= n <= len(key_points)}
    return [point for n, point in enumerate(key_points, start=1) if n in wanted]


def answer_review(review: ModelReview, answer: dict, topic: dict) -> AnswerReview:
    framework = Framework.model_validate(topic.get("framework") or {})
    covered = pick_points(review.covered, framework.key_points)
    missed = [p for p in pick_points(review.missed, framework.key_points) if p not in covered]
    corrected = [HeardAs(heard=heard, read_as=term) for heard, term in (answer.get("corrections") or {}).items()]
    return AnswerReview(
        topic_id=answer["topic_id"], topic=topic["title"], kind=topic["kind"], question=answer["question"],
        answer=answer["text"], band=review.band, framework=framework, covered=covered, missed=missed,
        improvement=review.improvement.strip(), gap=topic.get("source") == "gap", corrected=corrected,
        read_by_meaning=review.read_by_meaning,
    )


def stage_bands(reviews: list[AnswerReview]) -> list[StageBand]:
    """One band per stage, in the order the interview reached them."""
    by_kind: dict[str, list[int]] = {}
    for review in reviews:
        by_kind.setdefault(review.kind, []).append(BAND_VALUE[review.band])
    names = {value: band for band, value in BAND_VALUE.items()}
    return [StageBand(kind=kind, band=names[int(sum(values) / len(values) + 0.5)]) for kind, values in by_kind.items()]


def clean_items(items: list[str]) -> list[str]:
    return [item.strip() for item in items if item.strip()][:MAX_OVERALL_ITEMS]


def build_report(model_report: ModelReport, answers: list[dict], topics: dict[str, dict]) -> Report:
    """answers are the graded ones, in the order the model numbered them (from 1)."""
    reviews = [answer_review(r, answers[r.index - 1], topics[answers[r.index - 1]["topic_id"]])
               for r in sorted(model_report.answers, key=lambda r: r.index)]
    gaps = list(dict.fromkeys(r.topic for r in reviews if r.gap))
    return Report(reviews=reviews, stages=stage_bands(reviews), strengths=clean_items(model_report.strengths),
                  improvements=clean_items(model_report.improvements), gaps_touched=gaps)
