"""The turn-log report: p50/p95 per stage, and a warning while there are too few turns."""

from backend.observability.timings import append_turn_log, report


def test_report_gives_p50_and_p95_per_stage_and_warns_below_100_turns():
    records = [{"first_audio_ms": float(ms), "stt_ms": None} for ms in range(1, 11)]
    text = report(records)
    assert "10 turns (fewer than 100" in text
    row = next(line for line in text.splitlines() if line.startswith("first_audio_ms"))
    assert row.split()[1:] == ["10", "6", "10"]  # n, p50 (5.5 rounds to 6), p95
    assert next(line for line in text.splitlines() if line.startswith("stt_ms")).split()[1:] == ["0", "-", "-"]


def test_append_writes_one_json_line_per_turn(tmp_path):
    log = tmp_path / "sub" / "turn_log.jsonl"
    append_turn_log({"turn_id": 1}, log)
    append_turn_log({"turn_id": 2}, log)
    assert log.read_text(encoding="utf-8").splitlines() == ['{"turn_id": 1}', '{"turn_id": 2}']


def test_report_counts_interrupted_turns_and_keeps_their_total_out():
    records = [{"total_ms": 900.0, "interrupted": False, "first_audio_ms": 400.0},
               {"total_ms": None, "interrupted": True, "first_audio_ms": 1500.0},
               {"total_ms": None, "interrupted": True, "first_audio_ms": None}]
    text = report(records)
    assert next(line for line in text.splitlines() if line.startswith("total_ms")).split()[1] == "1"  # finished turns only
    assert next(line for line in text.splitlines() if line.startswith("first_audio_ms")).split()[1] == "2"  # cut-off audio still counts
    assert text.splitlines()[-1] == "interrupted: 2 of 3 turns; 1 of them before any audio played"
