# Interviewer Mode: Subtasks

Implementation plan for `docs/interviewer-mode-plan.md` on branch `interviewer-mode`.
One small subtask at a time: implement, test, then review by Arjun before the next one starts.

Defaults taken from the plan's checklist (§11), to confirm during review: separate interview graph,
`TurnTaker` in `pipeline/` for both modes, R1 fix also ships to recruiter mode, 10-minute cap,
at most 2 interviewer sentences, deterministic ladder, one persona (neutral), end-of-session report
only, transcripts in memory only, a few Hinglish fillers ("matlab", "toh", "haan") in the cue lists.

Status: `review` = implemented and tested, waiting for review. `todo` = not started.

## Phase A: turn-taking (both modes)

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| A1 | STT `error` events reach the UI; `session.end` logs billed `audio_duration_s` | P0.1, R5 | `providers/stt.py`, `tests/test_stt.py` | review |
| A2 | `TurnTaker` as a standalone module: hold timers, generation token, text cues, re-open, nudge clock (not wired yet) | P1.1–P1.3 | `pipeline/turn_taking.py`, `tests/test_turn_taking.py` | review |
| A3 | Failing test for R1 (a short "okay" during playback cuts the answer), marked `xfail(strict)` until A4 | P0.4 | `tests/test_voice_conversation.py` | review |
| A4 | Wire `TurnTaker` into `connection.py` with the recruiter policy; A3 passes; existing timelines still pass | P1.4 | `server/connection.py`, `tests/test_voice_conversation.py` | review |
| A5 | `turn_state` message to the browser and a "take your time" indicator | §5.6 | `connection.py`, `+page.svelte`, `docs/langgraph-design.md` | review |
| A6 | Per-mode Sarvam `silence_duration_ms` in the STT URL (the connection starts using it in C1, when modes exist) | P1.5 | `config.py`, `providers/stt.py`, `tests/test_stt.py` | review |
| A7 | Stale-audio-frame guard after an interrupt | P1.6, R4 | `web/src/lib/playback.ts`, `playback.test.ts`, `+page.svelte` | review |
| A8 | Turn-log fields: `turn_decision`, `hold_ms`, `segments_merged`, `barge_in_ms`, `stt_audio_s` (`mode` and the interview fields come with C1 and B7) | §7.3 | `observability/timings.py`, `connection.py`, `turn_taking.py`, `voice_turn.py` | review |
| A9 | Stronger tests: fake clock with exact boundaries, table tests for the word lists, every untested path, T16/T17 through the connection. Fixes found on the way: a request for time only counts at the end of a final; a cough after "let me think" no longer cancels the wait; a card click drops held words | §7 | `tests/*`, `turn_taking.py`, `connection.py`, `playback.test.ts` | review |
| A10 | Refactor, no behaviour change: `turn_cues.py` out of `turn_taking.py`; speech timings, browser-message parsing (pydantic) and booking tasks out of `connection.py` | CLAUDE.md | `pipeline/`, `server/` | todo |

## Phase B: interview brain (text mode first, no voice spend)

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| B1 | Extract the heard-history helper from `ingest.py` (no behaviour change) | P2.1 | `graph/nodes/ingest.py` | todo |
| B2 | Topic plan from the KB projects | P2.2 | `interview/plan.py` | todo |
| B3 | Clarification intents (repeat, hint, rephrase, skip, done) | P2.3 | `interview/intents.py` | todo |
| B4 | Persona table (neutral only) and fixed templates | §6.5 | `interview/personas.py` | todo |
| B5 | Control-tag parser and stream buffer | §6.3 | `graph/interview/tag.py` | todo |
| B6 | Interview graph: state, ingest, interviewer node, `prompts/interviewer.md` | P2.4 | `graph/interview/*` | todo |
| B7 | `advance` node: follow-up cap, ladder, time cap, closing | P3.1, P4.3 | `graph/interview/*` | todo |
| B8 | `/internal/turn` interview mode for text-only testing | P2.5 | `graph/api.py` | todo |

## Phase C: interview in voice and the report

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| C1 | `session_start.mode`, graph per connection, interview `TurnPolicy` | P2.6 | `server/connection.py`, `server/main.py` | todo |
| C2 | UI: mode picker and End button | P2.6 | `+page.svelte` | todo |
| C3 | Silence nudges wired to TTS | P5.1 | `server/connection.py` | todo |
| C4 | End-of-session evaluator | P4.1 | `interview/evaluate.py`, `prompts/evaluator.md` | todo |
| C5 | Report card in the browser | P4.1 | `InterviewReport.svelte` | todo |

## Phase D: wrap-up

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| D1 | README and docs: interview mode setup, commands, new WebSocket messages | CLAUDE.md | `README.md`, `docs/` | todo |

Integration tests from the plan (T8–T10, T14–T17, T21, T22) are written inside the B and C subtasks they test.

## Not planned (needs real keys or a microphone, or the plan ruled it out)

- P0.2 / P0.3 timing measurements with real audio. Until then the policy numbers are the plan's starting guesses.
- Interview eval set and evaluator calibration (P2.5 evals, P3.2, P4.2): they call Groq and need hand labels.
- Volume ducking (P5.2), extra personas (P5.3), LLM-scored difficulty (P4.4): the plan defers these.
