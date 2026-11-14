"""plan.py: the topics an interview covers, in order, built from the knowledge base. No LLM.

One topic per project, using the project's whole document as grounding text (about 2k tokens
each, small enough to send in full: docs/interviewer-mode-plan.md §4.1 E), plus one topic for the
first work experience. The interviewer may only ask about a topic's text or the candidate's own words.

Rules a reader would not guess:
- A project with no document sections is skipped: there is nothing grounded to ask about.
- The experience topic is kept even when there are more projects than slots, so an interview
  always covers work experience when the KB has any.
"""

from __future__ import annotations

from typing import TypedDict

from backend.kb.validate import Experience, Project
from backend.tools.kb_data import KbData

MAX_TOPICS = 4


class Topic(TypedDict):
    """One interview topic. A TypedDict, not a dataclass, so the graph checkpointer can store it as is."""

    topic_id: str  # project id, or "experience:<id>"
    title: str  # spoken name, e.g. "Beacon"
    text: str  # the only facts the interviewer may rely on


def project_topic(project: Project, sections: dict[str, str]) -> Topic:
    text = "\n\n".join(f"## {heading}\n{body}" for heading, body in sections.items())
    return Topic(topic_id=project.id, title=project.name, text=text)


def experience_topic(experience: Experience) -> Topic:
    lines = [f"{experience.role} at {experience.organization}. {experience.one_line}"]
    lines += [f"- {highlight.description}" for highlight in experience.highlights]
    return Topic(topic_id=f"experience:{experience.id}", title=experience.organization, text="\n".join(lines))


def build_plan(kb: KbData, max_topics: int = MAX_TOPICS) -> list[Topic]:
    """Projects in knowledge-base order, then the first experience; at most max_topics in all."""
    projects = [project_topic(p, kb.sections[p.id]) for p in kb.projects if kb.sections.get(p.id)]
    experience = [experience_topic(kb.experience[0])] if kb.experience else []
    project_slots = max(max_topics - len(experience), 0)
    return (projects[:project_slots] + experience)[:max_topics]
