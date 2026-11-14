"""prompt.py: the interviewer's system prompt and the per-turn message built from the interview state.

Pure functions: state, topic and persona in, text out. The node in nodes.py streams the model call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.interview.personas import Persona
from backend.interview.plan import Topic

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "interviewer.md"
HISTORY_ITEMS = 6

# What the interviewer should do this turn, by mode (graph/interview/flow.py chooses it).
MODE_INSTRUCTIONS = {
    "start": "Open the interview: in one short sentence say you will ask about their projects, "
             "then ask your first question about {title}. Ask them to explain what it does or how it is built.",
    "new_topic": "Move to a new topic: ask them to explain what {title} does or how it is built. "
                 "Do not mention the previous topic.",
    "skip": "The candidate chose to skip. Say that is fine in a few words, then ask them to explain "
            "what {title} does or how it is built.",
    "hint": "The candidate asked for a hint. Give one small hint drawn from the notes, without giving the "
            "answer away, then ask your last question again in fewer words.",
    "rephrase": "The candidate did not understand your last question. Ask the same question again in "
                "simpler words. Do not ask anything new.",
    "answer": "Respond to the candidate's latest message, then ask your next question.",
}
NEXT_TOPIC = "If you choose next, acknowledge their answer in a few words, then ask them to explain what {title} does."
LAST_TOPIC = "If you choose next, thank them in a few words and ask nothing more: the interview ends after this."
CAP_REACHED = "You have asked enough about this topic: choose next."
LEVEL_NAMES = {1: "explain (what it does, how it works)", 2: "justify (why this design)",
               3: "stress (what breaks, at scale or on failure)"}


@lru_cache(maxsize=1)
def load_interviewer_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def allowed_decisions(persona: Persona, level: int) -> list[str]:
    """The persona's decisions, without "challenge" below the level where this persona may challenge."""
    return [d for d in persona.allowed_decisions if d != "challenge" or level >= persona.challenge_from_level]


def decisions_for_turn(state: dict, persona: Persona) -> list[str]:
    """What the model may choose this turn: only "next" once the topic's follow-ups are used up."""
    if state.get("followups_used", 0) >= persona.max_followups:
        return ["next"]
    return allowed_decisions(persona, state.get("level", 1))


def history_lines(messages: list) -> str:
    """The last few turns before the current one, as "Interviewer:" / "Candidate:" lines."""
    lines = [f"{'Candidate' if m.type == 'human' else 'Interviewer'}: {m.content}" for m in messages[-HISTORY_ITEMS:]]
    return "\n".join(lines)


def mode_instruction(mode: str, decisions: list[str], topic: Topic, next_title: str | None) -> str:
    """The closing instruction of the turn message. An answer also learns what "next" means here."""
    lines = [MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["answer"]).format(title=topic["title"])]
    if mode == "answer":
        lines.append(NEXT_TOPIC.format(title=next_title) if next_title else LAST_TOPIC)
        if decisions == ["next"]:
            lines.append(CAP_REACHED)
    return " ".join(lines)


def build_turn_message(state: dict, topic: Topic, persona: Persona, next_title: str | None = None) -> str:
    """Everything the model needs for this turn, in the order it should read it.

    next_title is the following topic's title, or None on the last topic.
    """
    mode = state.get("mode", "answer")
    level = state.get("level", 1)
    decisions = decisions_for_turn(state, persona)
    messages = state.get("messages", [])
    earlier = messages[:-1] if mode != "start" else messages  # the last message is the candidate's turn
    parts = [
        persona.prompt_fragment,
        f"Topic: {topic['title']}\nReference notes (the only facts you may rely on):\n{topic['text']}",
        f"Difficulty: level {level}, {LEVEL_NAMES.get(level, LEVEL_NAMES[1])}.",
        "Decisions allowed this turn: " + ", ".join(decisions) + ".",
    ]
    if earlier:
        parts.append("Conversation so far:\n" + history_lines(earlier))
    if state.get("last_question"):
        parts.append(f"Your last question: {state['last_question']}")
    if mode != "start":
        parts.append(f"Candidate's latest message: {state.get('query', '')}")
    parts.append(mode_instruction(mode, decisions, topic, next_title))
    return "\n\n".join(parts)
