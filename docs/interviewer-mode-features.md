# Interviewer Mode: Subtasks

Implementation plan for `docs/interviewer-mode-plan.md` on branch `interviewer-mode`.
One small subtask at a time: implement, test, then review by Arjun before the next one starts.

Defaults taken from the plan's checklist (§11), to confirm during review: separate interview graph,
`TurnTaker` in `pipeline/` for both modes, R1 fix also ships to recruiter mode, 10-minute cap,
at most 2 interviewer sentences, deterministic ladder, two personas (neutral and strict; strict has a male voice), end-of-session report
only, transcripts in memory only, a few Hinglish fillers ("matlab", "toh", "haan") in the cue lists.

Status: `done` = implemented, tested and approved in review. `review` = waiting for review. `deferred` = postponed by Arjun.

## Phase A: turn-taking (both modes)

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| A1 | STT `error` events reach the UI; `session.end` logs billed `audio_duration_s` | P0.1, R5 | `providers/stt.py`, `tests/test_stt.py` | done |
| A2 | `TurnTaker` as a standalone module: hold timers, generation token, text cues, re-open, nudge clock (not wired yet) | P1.1–P1.3 | `pipeline/turn_taking.py`, `tests/test_turn_taking.py` | done |
| A3 | Failing test for R1 (a short "okay" during playback cuts the answer), marked `xfail(strict)` until A4 | P0.4 | `tests/test_voice_conversation.py` | done |
| A4 | Wire `TurnTaker` into `connection.py` with the recruiter policy; A3 passes; existing timelines still pass | P1.4 | `server/connection.py`, `tests/test_voice_conversation.py` | done |
| A5 | `turn_state` message to the browser and a "take your time" indicator | §5.6 | `connection.py`, `+page.svelte`, `docs/langgraph-design.md` | done |
| A6 | Per-mode Sarvam `silence_duration_ms` in the STT URL (the connection starts using it in C1, when modes exist) | P1.5 | `config.py`, `providers/stt.py`, `tests/test_stt.py` | done |
| A7 | Stale-audio-frame guard after an interrupt | P1.6, R4 | `web/src/lib/playback.ts`, `playback.test.ts`, `+page.svelte` | done |
| A8 | Turn-log fields: `turn_decision`, `hold_ms`, `segments_merged`, `barge_in_ms`, `stt_audio_s` (`mode` and the interview fields come with C1 and B7) | §7.3 | `observability/timings.py`, `connection.py`, `turn_taking.py`, `voice_turn.py` | done |
| A9 | Stronger tests: fake clock with exact boundaries, table tests for the word lists, every untested path, T16/T17 through the connection. Fixes found on the way: a request for time only counts at the end of a final; a cough after "let me think" no longer cancels the wait; a card click drops held words | §7 | `tests/*`, `turn_taking.py`, `connection.py`, `playback.test.ts` | done |
| A10 | Refactor, no behaviour change: `turn_cues.py` out of `turn_taking.py`; speech timings, browser-message parsing (pydantic) and booking tasks out of `connection.py` | CLAUDE.md | `pipeline/`, `server/` | deferred |

## Phase B: interview brain (text mode first, no voice spend)

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| B1 | Extract the heard-history helper from `ingest.py` (no behaviour change) | P2.1 | `graph/nodes/ingest.py`, `tests/test_heard_history.py` | done |
| B2 | Topic plan from the KB projects | P2.2 | `interview/plan.py`, `tests/test_interview_plan.py` | done |
| B3 | Clarification intents (repeat, hint, rephrase, skip, end) | P2.3 | `interview/intents.py`, `tests/test_interview_intents.py` | done |
| B4 | Persona table (neutral and strict, strict with a male voice) and fixed templates | §6.5 | `interview/personas.py`, `tests/test_interview_personas.py` | done |
| B5 | Control-tag parser and stream buffer | §6.3 | `graph/interview/tag.py`, `tests/test_interview_tag.py` | done |
| B6 | Interview graph: state, ingest, interviewer node, `prompts/interviewer.md` (opening, answers, hint, rephrase, repeat without LLM) | P2.4 | `graph/interview/*`, `prompts/interviewer.md`, `tests/test_interview_graph.py` | done |
| B7 | `steer` and `advance` nodes: follow-up cap, ladder, topic moves, skip, end, strict hint refusal, 10-minute cap, closing | P3.1, P4.3 | `graph/interview/flow.py`, `config.py`, `tests/test_interview_flow.py` | done |
| B8 | `/internal/turn` interview mode for text-only testing; interview graph built at startup | P2.5 | `graph/api.py`, `graph/runner.py`, `server/main.py`, `tests/test_internal_turn.py`, README | done |
| B9 | Log the LLM tokens Groq reports per call (input, output, cached, reasoning) in the turn log and `/internal/turn` | §7.3, §8 | `observability/usage.py`, `rag/llm.py`, both model nodes, `voice_turn.py`, `runner.py`, `timings.py`, `tests/test_llm_usage.py` | done |

## Phase C: interview in voice and the report

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| C1 | `start_interview {persona}` message (instead of `session_start.mode`: a click lets the browser play the opening), interview graph per connection, interview `TurnPolicy` and STT silence, persona voice passed to TTS, a reconnect replays the last question | P2.6 | `server/connection.py`, `server/main.py`, `pipeline/voice_turn.py`, `providers/tts.py`, `graph/interview/flow.py`, `tests/test_interview_voice.py` | done |
| C2 | UI: mode switch, persona picker, Start and End buttons (`InterviewControls`); `end_interview` message; End forgets the session id so a reload starts a new interview | P2.6 | `web/src/lib/interview.ts`, `web/src/lib/components/InterviewControls.svelte`, `+page.svelte`, `server/connection.py`, `tests/test_interview_voice.py` | done |
| C3 | Silence nudges: after a question finishes playing, the persona's fixed lines at 15 s and 45 s; through the graph (no LLM, saved in history, `repeat` still replays the question); none for strict, in recruiter mode, or after the end | P5.1 | `server/connection.py`, `graph/interview/nodes.py`, `flow.py`, `graph.py`, `state.py`, `graph/runner.py`, `pipeline/voice_turn.py`, tests | done |
| C4 | End-of-session evaluator: one call when the interview ends (any way), quotes checked against the notes, one retry, `interview_report` pending/ready/failed, cancelled if the page closes | P4.1 | `interview/evaluate.py`, `prompts/evaluator.md`, `rag/llm.py` (max_tokens), `server/connection.py`, `server/main.py`, `tests/test_interview_report.py`, `tests/test_interview_voice.py` | done |
| C5 | Report card in the browser: pending, failed, empty, and ready (average, tips, per-answer score, quoted right/missed/wrong points, uncovered claims) | P4.1 | `web/src/lib/components/InterviewReport.svelte`, `web/src/lib/interview.ts`, `interview.test.ts`, `+page.svelte` | done |

## Phase D: wrap-up

| # | Subtask | Plan ref | Files | Status |
|---|---|---|---|---|
| D1 | README and docs: interview mode section, layout, known limits; design doc section 13; this file's final state | CLAUDE.md | `README.md`, `docs/langgraph-design.md`, `docs/interviewer-mode-features.md` | review |

Integration tests from the plan (T8–T10, T14–T17, T21, T22) are written inside the B and C subtasks they test.

## Not built (needs real keys or a microphone, or the plan ruled it out)

- P0.2 / P0.3 timing measurements with real audio. Until then the hold times, nudge times and STT silence are the plan's starting guesses.
- Interview eval set and evaluator calibration (P2.5 evals, P3.2, P4.2): they call Groq and need hand labels.
- Volume ducking (P5.2) and LLM-scored difficulty (P4.4): the plan defers these. Of the extra personas (P5.3), only "strict" was built.

## What remains

1. One real end-to-end interview by hand: Start, answer, interrupt once, stay silent for a nudge, End, read the report. Check the strict voice by ear.
2. The measurements above, then tune `INTERVIEW_POLICY` and `STT_INTERVIEW_SILENCE_MS` from them.
3. Interview evals in text through `/internal/turn` (`"mode": "interview"`), and calibrating the report against hand-scored answers.
4. A10, the refactor, when Arjun chooses.
5. Tests send LangSmith traces because `.env` turns tracing on; a test setup that turns it off would stop that.
