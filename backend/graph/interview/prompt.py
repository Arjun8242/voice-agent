"""prompt.py: the interviewer's system prompt and the per-turn message built from the interview state.

Pure functions: state, topic and persona in, text out. The node in nodes.py streams the model call.
The model only ever writes follow-ups, hints and rephrasings: code asks every first question (flow.py).

Rules a reader would not guess:
- "next" means the same everywhere: acknowledge in a few words and ask nothing; code asks the next
  question. The system prompt (prompts/interviewer.md) says so too.
- Topic notes and the profile summary come from the candidate's resume and JD: they are wrapped in
  tags and the system prompt says they are data, never instructions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.graph.interview.tag import HINT_REQUEST
from backend.interview.personas import Persona
from backend.interview.plan import Topic

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "interviewer.md"
HISTORY_ITEMS = 6

# What the interviewer model does this turn, by mode (graph/interview/flow.py chooses it).
MODE_INSTRUCTIONS = {
    "hint": "The candidate asked for a hint. Give one small hint drawn from the notes, without giving the "
            "answer away, then ask your last question again in fewer words.",
    "rephrase": "The candidate did not understand your last question. Ask the same question again in "
                "simpler words. Do not ask anything new.",
    "answer": "Respond to the candidate's latest message, then ask your next question.",
}
NEXT_MEANS = "If you choose next, acknowledge their answer in a few words and ask nothing: the next question comes from the plan."
DIFFERENT_ASPECT = "Ask about a different aspect of this topic that has not been covered yet."

# The follow-up ladder of each kind of topic: level -> what a follow-up at that level asks about.
LADDERS: dict[str, dict[int, str]] = {
    "deep_dive": {1: "what they did", 2: "their method and why they chose it",
                  3: "the challenges, the team, and what they would change"},
    "technical": {1: "explain the concept", 2: "justify it and its trade-offs", 3: "how it fails or scales"},
    "behavioral": {1: "the situation and their task", 2: "the actions they took themselves",
                   3: "the result and what they learned"},
    "achievement": {1: "what they did", 2: "their own contribution and its impact"},
}
KIND_NOTES = {
    "behavioral": "This is a behavioural question: guide the candidate through situation, task, action and result.",
    "technical": "This is a technical question: check understanding, not memorised definitions.",
}


@lru_cache(maxsize=1)
def load_interviewer_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def history_lines(messages: list) -> str:
    """The last few turns before the current one, as "Interviewer:" / "Candidate:" lines."""
    lines = [f"{'Candidate' if m.type == 'human' else 'Interviewer'}: {m.content}" for m in messages[-HISTORY_ITEMS:]]
    return "\n".join(lines)


def ladder_line(topic: Topic, level: int) -> str:
    ladder = LADDERS.get(topic["kind"], LADDERS["deep_dive"])
    step = ladder.get(level, ladder[max(ladder)])
    return f"Follow-up level {level}: ask about {step}."


def mode_instruction(mode: str, decisions: list[str]) -> str:
    """The closing instruction of the turn message. An answer also learns what "next" means here."""
    lines = [MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["answer"])]
    if mode == "answer":
        lines.append(NEXT_MEANS if "next" in decisions else DIFFERENT_ASPECT)
    return " ".join(lines)


def topic_parts(state: dict, topic: Topic) -> list[str]:
    """What the model may rely on: the profile summary, then the topic and its notes."""
    parts = []
    if state.get("profile_summary"):
        parts.append(f"Candidate profile:\n<profile>\n{state['profile_summary']}\n</profile>")
    parts.append(f"Topic: {topic['title']}\nReference notes (the only facts you may rely on):\n"
                 f"<notes>\n{topic['text']}\n</notes>")
    if topic["kind"] in KIND_NOTES:
        parts.append(KIND_NOTES[topic["kind"]])
    return parts


def build_turn_message(state: dict, topic: Topic, persona: Persona) -> str:
    """Everything the model needs for this turn, in the order it should read it."""
    mode = state.get("mode", "answer")
    decisions = state.get("decisions") or []
    messages = state.get("messages", [])
    parts = [persona.prompt_fragment, *topic_parts(state, topic), ladder_line(topic, state.get("level", 1))]
    if mode == "answer":
        parts.append("Decisions allowed this turn: " + ", ".join([*decisions, HINT_REQUEST]) + ".")
    if messages[:-1]:  # the last message is the candidate's turn
        parts.append("Conversation so far:\n" + history_lines(messages[:-1]))
    if state.get("last_question"):
        parts.append(f"Your last question: {state['last_question']}")
    parts.append(f"Candidate's latest message: {state.get('query', '')}")
    parts.append(mode_instruction(mode, decisions))
    return "\n\n".join(parts)
