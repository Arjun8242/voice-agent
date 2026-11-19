"""behavioral.py: the fixed bank of behavioral questions. Every interview asks one, picked at random.

The questions and their frameworks are hand-written, so the report grades every behavioral answer
against the same reviewed points instead of a framework the model writes each time. The analysis call
does not plan this stage, with or without a job description.

A framework has key_points (what a strong answer contains) and red_flags (what a weak one shows).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TypedDict

from backend.interview.plan import Topic, make_topic


class BehavioralQuestion(TypedDict):
    ref: str
    question: str
    key_points: list[str]
    red_flags: list[str]


BEHAVIORAL_QUESTIONS: tuple[BehavioralQuestion, ...] = (
    BehavioralQuestion(
        ref="debugging",
        question="Tell me about a difficult bug you faced. How did you debug it?",
        key_points=["reproduced the bug first",
                    "isolated it with logs, metrics or a debugger, not guessing",
                    "found the root cause, not just the symptom",
                    "verified the fix and added a regression test",
                    "stated a reusable learning"],
        red_flags=["trial and error", "\"it started working\"", "a trivial bug", "no verification"],
    ),
    BehavioralQuestion(
        ref="trade-offs",
        question="Tell me about a technical decision where you chose between options. What trade-offs did you consider?",
        key_points=["at least two real options compared",
                    "downsides of the chosen option named",
                    "decision tied to constraints: scale, data criticality, deadline, team skills",
                    "says when they would revisit it"],
        red_flags=["\"it's popular\" or \"I already knew it\" as the only reason", "no downsides", "no constraints"],
    ),
    BehavioralQuestion(
        ref="learning",
        question="Tell me about a time you learned a new technology quickly to deliver something.",
        key_points=["started from docs or a working example",
                    "got a minimal end-to-end version early",
                    "went deep only where problems appeared",
                    "delivered a concrete outcome"],
        red_flags=["did a long course first", "no delivery outcome", "a vague \"I learned it\""],
    ),
    BehavioralQuestion(
        ref="feedback",
        question="Tell me about a time you received critical feedback on your code.",
        key_points=["no defensiveness",
                    "understood why it mattered",
                    "fixed it with a visible improvement",
                    "changed a habit or process going forward"],
        red_flags=["\"never got major feedback\"", "only formatting or naming feedback", "blaming the reviewer"],
    ),
    BehavioralQuestion(
        ref="unclear-requirements",
        question="Tell me about a time requirements were unclear. How did you handle it?",
        key_points=["noticed the ambiguity",
                    "asked specific questions",
                    "wrote down assumptions and got them confirmed",
                    "showed what clarifying saved"],
        red_flags=["built on silent assumptions", "waited passively", "vague questions"],
    ),
)


def behavioral_topic(work: list[str], choose: Callable = random.choice) -> Topic:
    """One bank question as a topic. work names the candidate's roles and projects, so follow-ups can
    tie the story to them. choose picks the question (random by default; tests pass a fixed pick)."""
    picked: BehavioralQuestion = choose(BEHAVIORAL_QUESTIONS)
    lines = [f"Behavioral question: {picked['question']}"]
    if work:
        lines.append(f"The candidate's own work, to link the story to: {', '.join(work)}")
    framework = {"key_points": picked["key_points"], "red_flags": picked["red_flags"],
                 "star": "situation, task, the candidate's own actions, result and learning"}
    return make_topic("behavioral", picked["ref"], "how you work through real situations", "\n".join(lines),
                      picked["question"], framework=framework)
