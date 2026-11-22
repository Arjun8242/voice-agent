"""vad.py: Silero voice activity detection, which decides where speech starts and ends.

Rules a reader would not guess:
- Speech starts only after VAD_MIN_SPEECH_MS of voiced frames, so a click, cough or bang in the
  background never opens a turn. Those frames and VAD_PREROLL_MS before them are sent first, so the
  first word is not cut off.
- Start and end use two thresholds (end = start - 0.15, Silero's own convention): a soft syllable in
  the middle of a sentence neither ends the speech nor resets the count towards a start.
- Speech ends after silence_ms, counted as Silero's VADIterator does: from the first frame below the
  end threshold, and only a frame at or above the start threshold resets it. It ends on a frame below
  the end threshold. The STT client sets silence_ms per mode.

SpeechGate holds the decisions and takes one probability per frame, so it is tested with plain numbers.
SileroVad cuts the browser's audio into frames and asks the model.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

from backend.config import VAD_MIN_SPEECH_MS, VAD_PREROLL_MS, VAD_SILENCE_MS, VAD_THRESHOLD

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # the frame size Silero takes at 16 kHz
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 PCM
FRAME_MS = FRAME_SAMPLES * 1000 / SAMPLE_RATE  # 32 ms


def frames_for(ms: float) -> int:
    return math.ceil(ms / FRAME_MS)


@dataclass(frozen=True)
class GateEvent:
    """start carries the held audio (pre-roll and the frames that confirmed speech); audio carries speech."""

    kind: Literal["start", "audio", "end"]
    audio: bytes = b""


class SpeechGate:
    """One per connection. step() is called once per frame with Silero's speech probability."""

    def __init__(self, silence_ms: float = VAD_SILENCE_MS, threshold: float = VAD_THRESHOLD) -> None:
        self.silence_ms = silence_ms
        self.threshold = threshold
        self.speaking = False
        self._min_speech = frames_for(VAD_MIN_SPEECH_MS)
        self._held: deque[bytes] = deque(maxlen=frames_for(VAD_PREROLL_MS) + self._min_speech)
        self._voiced = 0
        self._silent = 0

    def step(self, prob: float, frame: bytes) -> list[GateEvent]:
        if self.speaking:
            return self._step_speaking(prob, frame)
        self._held.append(frame)
        if prob >= self.threshold:
            self._voiced += 1
        elif prob < self.threshold - 0.15:
            self._voiced = 0
        if self._voiced < self._min_speech:
            return []
        self.speaking, self._voiced, self._silent = True, 0, 0
        held = b"".join(self._held)
        self._held.clear()
        return [GateEvent("start", held)]

    def _step_speaking(self, prob: float, frame: bytes) -> list[GateEvent]:
        quiet = prob < self.threshold - 0.15
        if prob >= self.threshold:
            self._silent = 0
        elif quiet or self._silent:
            self._silent += 1
        events = [GateEvent("audio", frame)]
        if quiet and self._silent >= frames_for(self.silence_ms):
            self.speaking = False
            events.append(GateEvent("end"))
        return events


class SileroVad:
    """The Silero model for one connection (it keeps state between frames, so it is never shared)."""

    def __init__(self, gate: SpeechGate) -> None:
        # Imported here, not at the top: torch is slow to import and tests never run the model.
        from silero_vad import load_silero_vad

        self.gate = gate
        self._model = load_silero_vad()
        self._rest = b""  # bytes left over when a chunk is not a whole number of frames

    def feed(self, pcm: bytes) -> list[GateEvent]:
        """Run the browser's chunk through the gate. Speech frames in one chunk are merged into one audio event."""
        data = self._rest + pcm
        whole = len(data) - len(data) % FRAME_BYTES
        self._rest = data[whole:]
        events: list[GateEvent] = []
        for i in range(0, whole, FRAME_BYTES):
            frame = data[i:i + FRAME_BYTES]
            for event in self.gate.step(self._speech_prob(frame), frame):
                if event.kind == "audio" and events and events[-1].kind in ("start", "audio"):
                    events[-1] = GateEvent(events[-1].kind, events[-1].audio + event.audio)
                else:
                    events.append(event)
        return events

    def _speech_prob(self, frame: bytes) -> float:
        import torch

        samples = torch.frombuffer(bytearray(frame), dtype=torch.int16).float() / 32768
        with torch.no_grad():  # inference only, as Silero's VADIterator runs it
            return float(self._model(samples, SAMPLE_RATE).item())
