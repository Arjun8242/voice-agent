"""personas.py: how the interviewer behaves, as data, plus the fixed lines it speaks without the LLM.

A persona differs in behaviour rules, not adjectives (docs/interviewer-mode-plan.md §4.1 G):
how many follow-ups per topic, which follow-up decisions it may take, whether it gives hints, and
what it says when the candidate goes quiet, and which TTS voice speaks. Two personas: "neutral"
(the default) and "strict", which merges the plan's strict and challenging columns. Adding another
is a new entry in PERSONAS; the graph and the connection read only these fields.

Fixed lines (nudges, closing) never go through the LLM: they cost no tokens and can never say
anything odd. Keep each to one or two short sentences, since every character is paid TTS.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config import TTS_SPEAKER

Decision = str  # "probe", "example", "challenge", "next", "clarify_back"; the graph enforces the list
ALL_DECISIONS: tuple[Decision, ...] = ("probe", "example", "challenge", "next", "clarify_back")

CLOSING = "That's all the questions I have. Thank you for your time."
HINT_DECLINED = "No hints in this round. Let's go to the next question."  # personas without hints


@dataclass(frozen=True)
class Persona:
    name: str
    prompt_fragment: str  # added to the interviewer prompt: tone and follow-up style
    max_followups: int  # follow-up questions per topic before moving on
    allowed_decisions: tuple[Decision, ...]  # what the model may choose after an answer
    challenge_from_level: int  # "challenge" is allowed from this difficulty level (1-3) on
    gives_hints: bool  # False: a hint request gets "let's move on" instead
    nudges: tuple[str, ...]  # spoken in order after silence; () turns nudges off
    voice: str  # Sarvam bulbul:v3 speaker; same price per character for every voice


NEUTRAL = Persona(
    name="neutral",
    prompt_fragment=(
        "Tone: calm and neutral. Start with a brief acknowledgement that names one specific thing the "
        "candidate said, without praising or judging it. Prefer follow-ups that probe one level deeper "
        "into what they just said. Give a hint only when they ask for one."
    ),
    max_followups=2,
    allowed_decisions=ALL_DECISIONS,
    challenge_from_level=3,
    gives_hints=True,
    nudges=(
        "Take your time. Say hint if you'd like one.",
        "Would you like to move on to the next question?",
    ),
    voice=TTS_SPEAKER,
)

STRICT = Persona(
    name="strict",
    prompt_fragment=(
        "Tone: direct and exacting, never rude. Acknowledge in at most three words, without praise. "
        "Ask for precision: the exact mechanism, number or component. Question decisions: ask why "
        "they chose it over an alternative, but never claim the alternative is better. If an answer is "
        "vague, say so in a few words and ask for the specific part again."
    ),
    max_followups=2,
    allowed_decisions=("probe", "challenge", "next", "clarify_back"),  # no "give me an example" softeners
    challenge_from_level=1,
    gives_hints=False,
    nudges=(),  # silence is the candidate's to use
    voice="shubh",  # shortcut: Sarvam's docs give no genders for v3 voices; assumed male, confirm by listening before release
)

PERSONAS: dict[str, Persona] = {NEUTRAL.name: NEUTRAL, STRICT.name: STRICT}


def get_persona(name: str | None) -> Persona:
    """The named persona, or neutral when the name is missing or unknown (it comes from the browser)."""
    return PERSONAS.get(name or "", NEUTRAL)
