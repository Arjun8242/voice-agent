"""fixed_audio.py: the interviewer's fixed lines, recorded once per voice and played from disk after that.

Code speaks the same sentences in every interview (the opening, intro, bridges, nudges, closing and the
behavioral bank's questions). Their audio is saved the first time Sarvam speaks them in full, so each
later interview spends no TTS characters on them (v2 design, "LLM and Sarvam usage", reduction 2).

Rules a reader would not guess:
- Only sentences in FIXED_SENTENCES are ever saved: model replies and anything about the candidate
  never reach the disk.
- A sentence is saved only when its synthesis finished; a barge-in mid-sentence saves nothing.
- Lines are split into sentences the way voice_turn splits them, since TTS is called per sentence.
- CACHE_DIR is read at call time so tests can point it at a temporary folder.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from backend.config import TTS_CACHE_DIR, TTS_SPEAKER
from backend.interview.behavioral import BEHAVIORAL_QUESTIONS
from backend.interview.personas import (BRIDGES, CLOSING, HINT_DECLINED, INTRO_QUESTION, OPENING, PERSONAS, SKIP_ACK,
                                        THANKS)
from backend.pipeline.sentence import extract_next_sentence

CACHE_DIR: Path = TTS_CACHE_DIR


def sentences_of(line: str) -> list[str]:
    """The sentences voice_turn would send to TTS for this line."""
    found, rest = [], line
    while (split := extract_next_sentence(rest)) is not None:
        found.append(split["sentence"])
        rest = split["remaining"]
    return found + ([rest.strip()] if rest.strip() else [])


FIXED_LINES = [OPENING, INTRO_QUESTION, THANKS, SKIP_ACK, CLOSING, HINT_DECLINED, *BRIDGES.values(),
               *(line for persona in PERSONAS.values() for line in persona.nudges),
               *(question["question"] for question in BEHAVIORAL_QUESTIONS)]
FIXED_SENTENCES: frozenset[str] = frozenset(s for line in FIXED_LINES for s in sentences_of(line))


def audio_path(sentence: str, speaker: str) -> Path:
    digest = hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / (speaker or TTS_SPEAKER) / f"{digest}.mp3"


def recorded_audio(sentence: str, speaker: str) -> bytes | None:
    """The saved audio of a fixed sentence in this voice, or None (not fixed, or not recorded yet)."""
    if sentence not in FIXED_SENTENCES:
        return None
    path = audio_path(sentence, speaker)
    return path.read_bytes() if path.is_file() else None


def save_audio(sentence: str, speaker: str, audio: bytes) -> None:
    """Keep a fixed sentence's complete audio; anything else is ignored."""
    if sentence not in FIXED_SENTENCES or not audio:
        return
    path = audio_path(sentence, speaker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
