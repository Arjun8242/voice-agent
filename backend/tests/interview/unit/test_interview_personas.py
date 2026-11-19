"""Personas: each persona's rules, the fallback for unknown names, voices, and the fixed spoken lines."""

from __future__ import annotations

import re

import pytest

from backend.interview.personas import ALL_DECISIONS, CLOSING, HINT_DECLINED, NEUTRAL, PERSONAS, STRICT, get_persona
from backend.pipeline.turn_taking import INTERVIEW_POLICY

# Sarvam's bulbul:v3 speakers, from https://docs.sarvam.ai/api-reference-docs/text-to-speech/convert (2026-11-14).
# Names are case-sensitive; a name not on this list fails every TTS request of that persona.
BULBUL_V3_SPEAKERS = {
    "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran", "kavya", "amit", "dev",
    "ishita", "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan", "ashutosh", "advait",
    "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha",
    "rehan", "soham", "rupali",
}


def test_neutral_follows_the_plan_table():
    # docs/interviewer-mode-plan.md §4.1 G, "Neutral" column
    assert (NEUTRAL.max_followups, NEUTRAL.gives_hints, NEUTRAL.challenge_from_level) == (2, True, 3)
    assert NEUTRAL.allowed_decisions == ALL_DECISIONS and len(NEUTRAL.nudges) == 2


def test_strict_follows_the_plans_strict_and_challenging_columns():
    assert (STRICT.max_followups, STRICT.gives_hints, STRICT.nudges) == (2, False, ())
    assert STRICT.challenge_from_level == 1  # challenges from the first question, not only at level 3
    assert "challenge" in STRICT.allowed_decisions and "example" not in STRICT.allowed_decisions


def test_strict_speaks_with_a_different_voice_than_neutral():
    assert STRICT.voice == "shubh" and STRICT.voice != NEUTRAL.voice


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=lambda p: p.name)
def test_every_persona_voice_is_a_bulbul_v3_speaker(persona):
    assert persona.voice in BULBUL_V3_SPEAKERS


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=lambda p: p.name)
def test_every_persona_uses_only_known_decisions_and_can_always_move_on(persona):
    assert set(persona.allowed_decisions) <= set(ALL_DECISIONS)
    assert "next" in persona.allowed_decisions  # otherwise a topic could never end except by the cap
    assert 1 <= persona.challenge_from_level <= 3


@pytest.mark.parametrize("name, persona", [("neutral", NEUTRAL), ("strict", STRICT)])
def test_a_known_name_returns_its_persona(name, persona):
    assert get_persona(name) is persona


@pytest.mark.parametrize("name", [None, "", "tough", "../../etc/passwd", "friendly", "NEUTRAL", "Strict"])
def test_a_missing_or_unknown_name_falls_back_to_neutral(name):
    assert get_persona(name) is NEUTRAL


@pytest.mark.parametrize("persona", PERSONAS.values(), ids=lambda p: p.name)
def test_a_persona_with_nudges_has_one_line_per_interview_nudge_time(persona):
    # the TurnTaker fires one nudge per entry in nudge_ms; a missing line would be an index error at runtime
    assert persona.nudges == () or len(persona.nudges) == len(INTERVIEW_POLICY.nudge_ms)


@pytest.mark.parametrize("line", [CLOSING, HINT_DECLINED, *NEUTRAL.nudges])
def test_fixed_lines_are_short_and_plain(line):
    sentences = [s for s in re.split(r"[.?!]", line) if s.strip()]
    assert 1 <= len(sentences) <= 2 and len(line) <= 80  # paid TTS characters, and the sentence splitter cuts at . ! ?
    assert not re.search(r"[{}<>\[\]*_#]", line)  # no template holes or markdown read aloud
