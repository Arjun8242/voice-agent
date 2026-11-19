"""plan.py: the topics an interview covers, in order, and the question budget of each. No LLM.

An interview has stages in a fixed order (STAGES). Each topic belongs to one stage (its kind) and carries
that stage's budget: min_q and max_q count every question asked on the topic, its seed question
included; max_level caps the follow-up ladder. flow.py enforces them
(docs/Interviewer Mode v2 — Resume + JD Interview Design.md, "Interview structure").

Rules a reader would not guess:
- A stage with no material simply has no topic: order_plan never invents one.
- The intro is a topic like any other (one question, no follow-ups); the wrap-up is not: it is the
  closing line flow.py speaks after the last topic.
- build_plan (the knowledge-base plan) is temporary: every session gets Arjun's projects until the
  resume upload builds a plan per candidate (phase 3).
"""

from __future__ import annotations

from typing import TypedDict

from backend.interview.personas import INTRO_QUESTION
from backend.kb.validate import Experience, Project
from backend.tools.kb_data import KbData

MAX_TOPICS = 4

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


def project_topic(project: Project, sections: dict[str, str]) -> Topic:
    text = "\n\n".join(f"## {heading}\n{body}" for heading, body in sections.items())
    seed = f"Let's talk about {project.name}. What does it do, and which part did you build?"
    return make_topic("deep_dive", project.id, project.name, text, seed)


def experience_topic(experience: Experience) -> Topic:
    lines = [f"{experience.role} at {experience.organization}. {experience.one_line}"]
    lines += [f"- {highlight.description}" for highlight in experience.highlights]
    seed = f"Tell me about your work at {experience.organization}. What did you work on?"
    return make_topic("deep_dive", experience.id, experience.organization, "\n".join(lines), seed)


def build_plan(kb: KbData, max_topics: int = MAX_TOPICS) -> list[Topic]:
    """The intro, then projects in knowledge-base order, then the first experience; at most max_topics
    after the intro. The experience is kept even when there are more projects than slots."""
    projects = [project_topic(p, kb.sections[p.id]) for p in kb.projects if kb.sections.get(p.id)]
    experience = [experience_topic(kb.experience[0])] if kb.experience else []
    project_slots = max(max_topics - len(experience), 0)
    return [intro_topic(), *(projects[:project_slots] + experience)[:max_topics]]
