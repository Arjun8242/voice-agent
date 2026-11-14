"""timings.py: one JSON line per spoken turn, and a p50/p95 report over them (design doc section 8).

Each line holds the stages of one turn, in milliseconds:
    stt_ms             end of the visitor's speech -> final transcript
    hold_ms            final transcript -> turn start: the end-of-turn hold (pipeline/turn_taking.py)
    wait_ms            waiting for a cut-off answer's playback report (0 almost always)
    rag_ms             retrieval
    first_token_ms     turn start -> first answer token (includes any tool round)
    first_sentence_ms  turn start -> first full sentence handed to TTS
    first_audio_ms     turn start -> first audio chunk sent to the browser
    speech_end_to_first_audio_ms   stt + hold + wait + first_audio: what the visitor waits for
    total_ms           turn start -> done (empty for an interrupted turn: it is not a real total)
    interrupted        the visitor cut in before the server finished the turn
    cut_off_ms         turn start -> the cut-in (interrupted turns only)
    barge_in_ms        the visitor's speech start -> the interrupt, server side (barge-in turns only)
    turn_decision      why the turn was taken: base_hold, long_hold, think, done_phrase or reopened
    segments_merged    how many final transcripts were merged into the turn
    llm_calls, input_tokens, output_tokens, cached_tokens, reasoning_tokens
                       tokens Groq reported, summed over the turn's LLM calls (observability/usage.py)
A line with "type": "stt_session" is not a turn: it holds stt_audio_s, the audio seconds Sarvam
billed for one STT socket (sent when Sarvam ends the session). The report skips these lines.
Interrupted turns stay in the log: dropping them would hide the slow turns visitors gave up on.
Browser-side time (network, audio buffering) is not included.

    python -m backend.observability.timings          # report over data/turn_log.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "turn_log.jsonl"
FIELDS = ["stt_ms", "hold_ms", "wait_ms", "rag_ms", "first_token_ms", "first_sentence_ms",
          "first_audio_ms", "speech_end_to_first_audio_ms", "total_ms"]
TOKEN_FIELDS = ["input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"]
MIN_TURNS = 100  # design doc: p95 needs at least 100 turns to mean anything


def append_turn_log(record: dict, path: Path = LOG_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as err:  # a full disk must not break the voice turn
        print(f"[timings] could not write the turn log: {err}")


def turn_records(records: list[dict]) -> list[dict]:
    """Only the per-turn lines; session lines (stt_session) have no stage times."""
    return [r for r in records if "type" not in r]


def report(records: list[dict]) -> str:
    lines = [f"{len(records)} turns" + (f" (fewer than {MIN_TURNS}: p95 is not reliable yet)" if len(records) < MIN_TURNS else "")]
    lines.append(f"{'stage':<30} {'n':>5} {'p50':>8} {'p95':>8}")
    for field in FIELDS + TOKEN_FIELDS:  # ms per stage, then tokens per turn
        values = sorted(r[field] for r in records if r.get(field) is not None)
        if not values:
            lines.append(f"{field:<30} {0:>5} {'-':>8} {'-':>8}")
            continue
        p95 = statistics.quantiles(values, n=20)[18] if len(values) >= 2 else values[0]
        lines.append(f"{field:<30} {len(values):>5} {statistics.median(values):>8.0f} {p95:>8.0f}")
    cut = [r for r in records if r.get("interrupted")]
    before_audio = [r for r in cut if r.get("first_audio_ms") is None]
    lines.append(f"interrupted: {len(cut)} of {len(records)} turns; {len(before_audio)} of them before any audio played")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="p50/p95 per stage from the turn log.")
    p.add_argument("--log", type=Path, default=LOG_PATH)
    args = p.parse_args(argv)
    if not args.log.exists():
        print(f"No turn log yet at {args.log}: talk to the agent first.")
        return 1
    records = [json.loads(line) for line in args.log.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(report(turn_records(records)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
