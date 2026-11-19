"""pacing.py: how many questions the current topic may still take, and which decisions the model is
offered after an answer. Pure functions, no LLM, no clock (steer passes the seconds left).

Rules a reader would not guess:
- "asked" counts every question on the topic, its seed question included: 1 + followups_used.
- No decisions at all means the topic is done: code moves on without calling the model.
- Below the topic's min_q, "next" is not offered, so the model must ask about another aspect.
- Time allocation: a topic may go past its min_q only while the time left, less one more question,
  still covers the minimum questions of every later topic. Otherwise its cap drops to its min_q
  (or to what was already asked), so a strong candidate cannot use up the later stages' time.
"""

from __future__ import annotations

from backend.config import SECONDS_PER_QUESTION
from backend.interview.personas import Persona
from backend.interview.plan import Topic


def allowed_decisions(persona: Persona, level: int) -> list[str]:
    """The persona's decisions, without "challenge" below the level where this persona may challenge."""
    return [d for d in persona.allowed_decisions if d != "challenge" or level >= persona.challenge_from_level]


def questions_asked(state: dict) -> int:
    return 1 + state.get("followups_used", 0)


def question_cap(topic: Topic, asked: int, seconds_left: float, later_topics: list[Topic]) -> int:
    """How many questions this topic may reach, given the time later topics are owed."""
    owed = sum(t["min_q"] for t in later_topics) * SECONDS_PER_QUESTION
    if seconds_left - SECONDS_PER_QUESTION >= owed:
        return topic["max_q"]
    return max(topic["min_q"], asked)


def decisions_for_turn(state: dict, persona: Persona, seconds_left: float) -> list[str]:
    """What the model may choose after this answer; [] when the topic must move on now."""
    topics: list[Topic] = state["topics"]
    index = min(state.get("topic_index", 0), len(topics) - 1)
    asked = questions_asked(state)
    if asked >= question_cap(topics[index], asked, seconds_left, topics[index + 1:]):
        return []
    decisions = allowed_decisions(persona, state.get("level", 1))
    if asked < topics[index]["min_q"]:
        return [d for d in decisions if d != "next"]
    return decisions
