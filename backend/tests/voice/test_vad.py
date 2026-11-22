"""SpeechGate: where speech starts and ends, given Silero's probability for each 32 ms frame. No model."""

from __future__ import annotations

from backend.config import VAD_INTERVIEW_SILENCE_MS, VAD_SILENCE_MS
from backend.pipeline.vad import FRAME_BYTES, SpeechGate, frames_for


def run(gate: SpeechGate, probs: list[float]) -> list[tuple[str, int]]:
    """Feed one silent frame per probability: (kind, frames of audio) for each event."""
    frame = bytes(FRAME_BYTES)
    return [(e.kind, len(e.audio) // FRAME_BYTES) for prob in probs for e in gate.step(prob, frame)]


def test_a_short_noise_burst_never_starts_speech():
    assert run(SpeechGate(), [0.0] * 5 + [0.9] * 7 + [0.0] * 30) == []  # 7 frames = 224 ms, under 250


def test_steady_background_noise_below_the_threshold_never_starts_speech():
    assert run(SpeechGate(), [0.4] * 200) == []


def test_speech_starts_with_the_audio_held_before_it():
    events = run(SpeechGate(), [0.0] * 30 + [0.9] * 10)
    # 8 frames confirm speech (250 ms); the 10 frames (300 ms) before them are sent too
    assert events[0] == ("start", 18)
    assert events[1:] == [("audio", 1), ("audio", 1)]


def test_a_soft_syllable_mid_sentence_does_not_end_speech():
    probs = [0.9] * 8 + [0.4] * 40 + [0.1] * (frames_for(VAD_SILENCE_MS) - 1) + [0.9] * 3
    assert all(kind != "end" for kind, _ in run(SpeechGate(), probs))


def test_a_murmur_after_speech_stops_does_not_hold_the_end_back():
    silence = frames_for(VAD_SILENCE_MS)
    events = run(SpeechGate(), [0.9] * 8 + [0.1] * 3 + [0.4] * (silence - 4) + [0.1])
    assert events[-1] == ("end", 0)


def test_speech_ends_after_the_recruiter_silence():
    events = run(SpeechGate(), [0.9] * 8 + [0.1] * frames_for(VAD_SILENCE_MS))
    assert events[-1] == ("end", 0)


def test_interview_silence_waits_longer_before_ending():
    gate = SpeechGate(silence_ms=VAD_INTERVIEW_SILENCE_MS)
    assert ("end", 0) not in run(gate, [0.9] * 8 + [0.1] * frames_for(VAD_SILENCE_MS))
    assert run(gate, [0.1] * frames_for(VAD_INTERVIEW_SILENCE_MS))[-1] == ("end", 0)
