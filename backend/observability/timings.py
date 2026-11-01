"""timings.py: one JSON line per spoken turn, and a p50/p95 report over them (design doc section 8).

Each line holds the stages of one turn, in milliseconds:
    stt_ms             end of the visitor's speech -> final transcript
    wait_ms            waiting for a cut-off answer's playback report (0 almost always)
    rag_ms             retrieval
    first_token_ms     turn start -> first answer token (includes any tool round)
    first_sentence_ms  turn start -> first full sentence handed to TTS
    first_audio_ms     turn start -> first audio chunk sent to the browser
    speech_end_to_first_audio_ms   stt + wait + first_audio: what the visitor waits for
    total_ms           turn start -> done (empty for an interrupted turn: it is not a real total)
    interrupted        the visitor cut in before the server finished the turn
    cut_off_ms         turn start -> the cut-in (interrupted turns only)
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
FIELDS = ["stt_ms", "wait_ms", "rag_ms", "first_token_ms", "first_sentence_ms",
          "first_audio_ms", "speech_end_to_first_audio_ms", "total_ms"]
MIN_TURNS = 100  # design doc: p95 needs at least 100 turns to mean anything


def append_turn_log(record: dict, path: Path = LOG_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as err:  # a full disk must not break the voice turn
        print(f"[timings] could not write the turn log: {err}")


def report(records: list[dict]) -> str:
    lines = [f"{len(records)} turns" + (f" (fewer than {MIN_TURNS}: p95 is not reliable yet)" if len(records) < MIN_TURNS else "")]
    lines.append(f"{'stage':<30} {'n':>5} {'p50':>8} {'p95':>8}")
    for field in FIELDS:
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
    print(report(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
