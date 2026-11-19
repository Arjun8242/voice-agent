"""plan.py: the shape of an interview plan: its stages, their question budgets, and its topics. No LLM.

An interview has stages in a fixed order (STAGES). Each topic belongs to one stage (its kind) and carries
that stage's budget: min_q and max_q count every question asked on the topic, its seed question
included; max_level caps the follow-up ladder. flow.py enforces them
(docs/Interviewer Mode v2 — Resume + JD Interview Design.md, "Interview structure").
A plan is built per session from the candidate's resume and job description (interview/assemble.py).

Rules a reader would not guess:
- The intro is a topic like any other (one question, no follow-ups); the wrap-up is not: it is the
  closing line flow.py speaks after the last topic.
"""

from __future__ import annotations

from typing import TypedDict

from backend.interview.personas import INTRO_QUESTION

# kind -> (min_q, max_q, max_level), in interview order. The design's stage table.
STAGES: dict[str, tuple[int, int, int]] = {
    "intro": (1, 1, 0),
    "deep_dive": (2, 4, 3),
    "technical": (2, 4, 3),
    "behavioral": (1, 2, 3),
    "achievement": (2, 2, 2),
}


class Topic(TypedDict):
    """One interview topic. A TypedDict, not a dataclass, so the graph checkpointer can store it as is."""

    topic_id: str  # stable id, e.g. "deep_dive:beacon"
    kind: str  # its stage: a key of STAGES
    source: str  # "resume", "jd" or "gap" (a JD requirement the resume does not show)
    title: str  # spoken name, e.g. "Beacon"
    text: str  # the only facts the interviewer may rely on
    seed_question: str  # the first question, spoken by code
    framework: dict  # key points, STAR outline, likely follow-ups; read only by the report
    min_q: int
    max_q: int
    max_level: int


class InterviewPlan(TypedDict):
    """What one session's interview is built from; sent into the graph's state with every turn."""

    topics: list[Topic]
    profile_summary: str  # a short summary of the resume, in every interviewer turn
    glossary: list[str]  # tech names from the resume and JD, for mis-heard terms (interview/glossary.py)


def make_topic(kind: str, ref: str, title: str, text: str, seed_question: str,
               source: str = "resume", framework: dict | None = None) -> Topic:
    """A topic with its stage's budget filled in. Raises KeyError for an unknown kind."""
    min_q, max_q, max_level = STAGES[kind]
    return Topic(topic_id=f"{kind}:{ref}", kind=kind, source=source, title=title, text=text,
                 seed_question=seed_question, framework=framework or {},
                 min_q=min_q, max_q=max_q, max_level=max_level)


def intro_topic() -> Topic:
    return make_topic("intro", "background", "your background", "", INTRO_QUESTION)


def order_plan(topics: list[Topic]) -> list[Topic]:
    """Topics in stage order; topics of one stage keep their given order."""
    order = list(STAGES)
    return sorted(topics, key=lambda topic: order.index(topic["kind"]))


def plan_preview(topics: list[Topic]) -> str:
    """The one line the candidate sees before starting, e.g. "We'll cover Beacon, SQL and teamwork." """
    titles = [topic["title"] for topic in topics if topic["kind"] != "intro"]
    if not titles:
        return "We'll talk about your background."
    listed = titles[0] if len(titles) == 1 else f"{', '.join(titles[:-1])} and {titles[-1]}"
    return f"We'll cover {listed}."


def live_stage(topics: list[Topic], topic_index: int, finished: bool) -> str | None:
    """The stage the candidate is in, for the page's stage chips: the current topic's kind, "wrap" once
    the closing line was spoken, or None before there is a plan."""
    if finished:
        return "wrap"
    if not topics:
        return None
    return topics[min(topic_index, len(topics) - 1)]["kind"]
