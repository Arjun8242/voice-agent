# Voice Career Agent: AI Engineering Design

Design document v0.1, 22 October 2026. Status: draft for review.

## 1. What we are building and why

**Product.** A browser-based voice agent that represents Arjun to recruiters and engineers. A visitor speaks or types. The agent answers about his projects, skills and technical decisions, opens cards (project detail, links) on screen, and books a 30-minute meeting. It says it is an AI, answers only from a verified knowledge base, and says 'I don't have that' when the knowledge base does not support an answer.

**Starting point (already built).** SvelteKit client, Python WebSocket backend, streaming speech-to-text and text-to-speech (Sarvam), Gemini as the LLM, RAG, and barge-in handling. The voice pipeline is kept. This document covers what is added on top.

**Additions and their purpose**

| Addition | Purpose |
| --- | --- |
| LangGraph | Explicit per-session state, a bounded tool loop, a deterministic booking path, checkpointed pause and resume |
| Autonomous tool calling | The model chooses among a fixed set of tools; code validates and executes every call |
| Knowledge base | Structured facts for exact answers, narrative docs for explanations, status tags so nothing unfinished is claimed as done |
| Booking workflow | One real, verifiable action with confirmation, idempotency and failure handling |
| LangSmith | Traces of every run, stage timings, datasets, and experiment comparison |
| Evals | Repeatable tests for retrieval, grounding, routing, booking and interruption behaviour |

**Goals.** Grounded answers. One safe real action. Measurable reliability. A demo a non-technical viewer understands in 30 seconds and an engineer can probe in depth.

**Non-goals.** Model training or fine-tuning, multi-agent teams, MCP, owner approval of each booking, analytics dashboards, production-scale traffic.

**Principles.** The model proposes and code decides. Grounding beats fluency. Measure before optimising. Reuse the working voice pipeline; rewrite nothing without a measured reason.

## 2. Architecture overview

```
Browser (SvelteKit)
  mic, speaker, UI cards, booking form
      |  WebSocket: audio + JSON events
      v
Python backend (asyncio)
  server: sessions, turn manager (turn IDs, barge-in)
  pipeline: STT in, TTS out     providers: Sarvam, Gemini
      |  in-process call per turn
      v
Agent graph (LangGraph)
  ingest -> retrieve -> agent <-> tools -> respond
                          '--> booking path (gate, execute)
      |               |                 |
      v               v                 v
 Knowledge store   Postgres + Redis   Calendar adapter
 (YAML + index)    (checkpoints,      (Google; fake in tests)
                    bookings, holds)

LangSmith <-- traces from every graph run
Eval runner --> POST /internal/turn (text mode, no voice)
```

**Decision D1: agent runtime language (settled).** The backend is Python, so the agent graph runs in the same process as the voice pipeline: no separate service and no extra network hop. The turn manager calls the graph directly. FastAPI is assumed in this document; confirm the actual framework when you audit the converted backend in Phase 0.

## 3. System design

### 3.1 One turn, end to end

1. The browser streams mic audio to the backend over WebSocket.
2. The voice pipeline runs STT. On the final transcript the turn manager assigns a `turn_id`, cancels any turn still running, and starts the agent graph in the same process.
3. The graph runs (section 4).
4. Tokens stream out of the graph. The turn manager sends complete sentences to TTS and plays audio as it arrives.
5. Cards travel as separate events and render at once.
6. On barge-in the turn manager stops audio, cancels the turn, and uses the reported playback position so history is trimmed to what was actually heard.

### 3.2 Browser to backend (WebSocket)

| Event | Direction | Key fields |
| --- | --- | --- |
| `session.start` / `session.ready` | both | timezone, locale / session\_id |
| audio frames | both | binary: mic up, TTS down |
| `transcript.partial` / `transcript.final` | server to client | turn\_id, text |
| `playback.progress` | client to server | turn\_id, played\_ms |
| `ui.card` / `ui.card.dismiss` | server to client | turn\_id, card\_id, type, data |
| `ui.action` | client to server | action (select\_slot, submit\_details, confirm, cancel), payload |
| `turn.cancelled` / `error` | server to client | turn\_id / code, message, retryable |

Every server event carries `turn_id`. The client drops events from turns at or before the last `turn.cancelled`, so a card from an interrupted request never appears late.

### 3.3 Internal endpoints (evals and admin)

The voice path calls the graph in the same process, so there is no internal streaming API. These endpoints exist for evals and operations.

| Endpoint | Purpose |
| --- | --- |
| `POST /internal/turn` | Body: session\_id, turn\_id, input (speech text or ui\_action), visitor\_tz. Returns one JSON object: reply, tool calls, cards, stage timings. Runs the same graph as the voice path without STT or TTS; the eval runner uses it. API key only |
| `POST /internal/kb/reindex` | Rebuilds the index (also available as a CLI command) |
| `GET /health` | Liveness |

Public REST (linked from the calendar invite): `GET /api/bookings/{id}?token=` for status, `POST /api/bookings/{id}/cancel?token=` to cancel.

### 3.4 Data stores

| Store | Holds |
| --- | --- |
| Postgres | LangGraph checkpoints (thread\_id = session\_id); tables bookings, fallback\_messages, turn\_log |
| Redis | Slot holds (`SET hold:<slot_start> <booking_id> NX EX 600`), rate-limit counters, embedding cache |
| Files | Knowledge files and the built index (vectors; BM25 only if adopted later), loaded into memory at startup |

`bookings`: id, session\_id, slot\_start\_utc, slot\_end\_utc, visitor\_name, visitor\_email, visitor\_tz, status, idempotency\_key (unique), calendar\_event\_id, failure\_reason, created\_at, confirmed\_at. `turn_log`: session\_id, turn\_id, route, tools, stage\_ms (JSON), created\_at.

## 4. LangGraph design

### 4.1 State

One state object per session, checkpointed to Postgres after each step.

| Field | Meaning |
| --- | --- |
| `session_id`, `turn_id`, `visitor_tz` | Identity and the visitor's IANA timezone |
| `messages` | Conversation history (trimmed to what was heard after a barge-in) |
| `user_input` | kind (speech or ui\_action) plus text, or action and payload |
| `topic` | Current project\_id and section, used to make retrieval and follow-ups topic-aware |
| `retrieved` | Chunks with id, text, score, metadata |
| `retrieval_status` | ok, none\_relevant, or skipped |
| `tool_steps` | Tool calls used this turn (cap 4) |
| `cards` | Cards to emit this turn |
| `offered_slots` | Slots shown to this visitor; only these can be started |
| `booking` | id, status, slot\_id, name, email, hold\_expires\_at, or empty |
| `final_text`, `errors` | Output for TTS and any failures |

### 4.2 Nodes

| Node | Type | Does |
| --- | --- | --- |
| `ingest_turn` | code | Appends the input, resets per-turn fields, updates topic, picks the next node |
| `booking_gate` | code | Handles input while a booking is waiting: form submit, confirm, cancel |
| `retrieve` | code | Topic-aware dense search with a relevance threshold (hybrid only if later tests justify it) |
| `agent` | LLM | One Gemini call with tools bound; returns text or tool calls |
| `tools` | code | Validates and runs tool calls (read-only ones in parallel), adds cards |
| `booking_execute` | code, shielded | Re-checks the slot, creates the event, reads it back |
| `respond` | code | Chooses the model's text, or a template for booking outcomes; streams it |

### 4.3 Edges

| From | Condition | To |
| --- | --- | --- |
| START | always | `ingest_turn` |
| `ingest_turn` | booking is awaiting\_details or awaiting\_confirmation | `booking_gate` |
| `ingest_turn` | otherwise | `retrieve` |
| `booking_gate` | confirm recognised | `booking_execute` |
| `booking_gate` | cancel, or details received | `respond` |
| `booking_gate` | anything else (the visitor asked something unrelated) | `retrieve`; the prompt notes a booking is pending |
| `retrieve` | always | `agent` |
| `agent` | tool calls and tool\_steps < 4 | `tools` |
| `agent` | text only, or step cap reached | `respond` |
| `tools` | always | `agent` |
| `booking_execute` | always | `respond` |
| `respond` | always | END |

### 4.4 Pause and resume

Waiting for the visitor does not suspend a run. The run ends with the booking status saved in the checkpoint, and the next input (a form submit, a click, or speech) starts a new run on the same `thread_id`, where `ingest_turn` routes to `booking_gate`. This keeps state inspectable and survives refreshes and reconnects. LangGraph's interrupt() is an alternative; verify its current behaviour in the docs before choosing it.

### 4.5 Streaming, cancellation, and guarantees

- Tokens from the agent node stream to the turn manager as produced; it cuts sentences for TTS. Verify LangGraph's current streaming modes in its docs.
- A cancel signal stops the run's async task. Events carry `turn_id`, so late output is discarded.
- `booking_execute` is shielded: after confirmation it runs to completion even if the visitor interrupts, because a half-finished booking is worse than a finished one. The result appears as a card.
- The model cannot confirm a booking. Confirmation reaches the graph only as a `ui_action` click or a transcript the turn manager matches against a strict confirm or cancel set.

### 4.6 Where LangGraph earns its place

The answer-or-tool loop alone is about 100 lines of plain code. LangGraph is justified by checkpointed per-session state, the separate deterministic booking path, step caps, and built-in tracing hooks. If it adds latency or complexity without those benefits, the fallback is the plain loop plus a small state machine.

## 5. Autonomous tool calling

'Autonomous' means the model picks the tool and the arguments. Code bounds that choice.

| Tool | Arguments | Returns | Side effect |
| --- | --- | --- | --- |
| `searchProjects` | query?, tech? | id, name, one\_line, status list | none |
| `getProjectDetail` | project\_id, section | Section text and media URLs; emits a card | none |
| `getSkills` | skill? | All skills, or the evidence for one | none |
| `getLinks` | type (portfolio, github, coding, resume) | URL; emits a card | none |
| `checkAvailability` | date\_from, date\_to | Up to 5 slots in the visitor's timezone | none |
| `startBooking` | slot\_id, topic? | booking\_id, status awaiting\_details; emits a form card | Pending booking and a 10-minute hold; nothing external |

Execution pipeline for every call: look up in the registry, validate arguments against the schema (pydantic), check preconditions (the slot\_id must be in `offered_slots`), run with a per-tool timeout, return a result or a structured error to the model, count the step. The tool list the model sees changes with state. Read-only calls may run in parallel. The visitor's timezone and today's date come from the session and system prompt, never from model arithmetic. Each description names both when to use the tool and which neighbouring tool to use instead.

Routing rules live in the system prompt, in order: meeting request, show or open, question about Arjun, boundary topic, off-topic, unclear. Anything that must never fail is enforced in code, not in the prompt.

## 6. Knowledge base

### 6.1 Two stores

Structured facts (YAML, hand-edited, schema-validated) are read by tools for exact answers, lists and 'no evidence' results. Narrative docs (Markdown) are chunked and retrieved for why, how and what-was-hard questions. YAML is used so entries can carry comments; it is validated at ingest.

### 6.2 Layout

```
knowledge/
  structured/
    projects.yaml      scheduling.yaml    skills.yaml
    experience.yaml    links.yaml
  docs/
    bio.md   faq.md   boundaries.md
    projects/<project_id>.md
```

### 6.3 Structured schemas (examples with placeholders)

```yaml
# projects.yaml
- id: example-project
  name: <name>
  one_line: <one factual sentence>
  status: shipped            # shipped | in_progress | idea
  featured: false            # exactly one project is true
  tech: [<tech>]
  role: <what Arjun did>
  links: {repo: <url>, live: <url or null>, video: <url or null>}
  assets: {architecture_image: <path>}
  highlights: [<verifiable fact>]
  measured: [{claim: <number>, how: <how it was measured>}]
  updated: 2026-10-22

# skills.yaml
- skill: <name>
  category: backend
  evidence: [<project_id or experience_id>]   # at least one required

# scheduling.yaml
timezone: <IANA timezone>
working_hours: {mon-fri: ['10:00', '18:00']}
duration_min: 30
buffer_min: 15
min_notice_hours: 12
max_days_ahead: 14
```

### 6.4 Project doc template

```markdown
---
project_id: <id>
status: shipped
---
# <Project name>
## Overview
## Architecture
## Key decisions
### <Decision title>
Chosen: ... Considered: ... Why: ...
## Challenges and how they were solved
## Limitations and not yet done
## Status and what is tested
```

### 6.5 Writing rules

- Write in third person ('Arjun built...'). The agent is an AI describing him, not him.
- Every project and feature carries a status. 'Built' may only be said for shipped.
- State limitations explicitly; this is what makes correct refusals possible.
- Numbers only if measured, with how.
- One fact per paragraph; identical headings in every project doc, since chunking splits on headings.
- A skill appears only with at least one evidence id.

### 6.6 Ingest (offline, once per change)

Validate schemas and evidence links, then split docs by heading into chunks of roughly 150 to 400 tokens with the heading path prepended, generate text chunks from the YAML (skills, experience), embed all chunks, and write the index to disk with a content hash (a BM25 index is added only if the final retrieval phase adopts it). The hash is recorded as `kb_version` on every trace.

Chunk metadata: id (source file plus heading path, not a running number), type (project\_doc, skill, experience, faq, boundary, bio), project\_id, section, status, source.

### 6.7 Retrieval strategy

1. Query = latest user text plus the current topic from state.
2. Version 1: dense search with your existing retriever, top 4 kept. BM25 and reciprocal rank fusion are tested in the final retrieval improvement phase, not assumed. Apply a metadata filter when the topic is known; force type=boundary for boundary questions.
3. If no chunk passes the similarity threshold, set `retrieval_status = none_relevant` and tell the model explicitly.
4. A reranker is added only if evals show correct chunks retrieved but ranked too low.
5. Skip retrieval for turns that are clearly tool-only.

Retrieval is evaluated and tuned under the separate retrieval engineering plan, which runs last, after the rest of the agent works. Its benchmark labels each query with the evidence it needs (source file, heading, and the fact), not chunk ids, so the same labels keep working when chunking changes. Queries include follow-ups with their topic, speech-recognition-noisy phrasings, and unanswerable and boundary questions. Report recall@4 (the number of chunks the model actually receives), MRR, and false passes. Compare configurations per query and report counts as well as percentages, because the benchmark is small. RAG versus putting the whole knowledge base in the prompt is decided by one comparison run, not assumed.

## 7. Booking workflow

States: `slots_offered`, `slot_held`, `awaiting_details`, `awaiting_confirmation`, `executing`, `confirmed`. Exits: `expired`, `cancelled`, `failed`. Until `executing` the visitor can back out. After confirmation, `executing` is the point of no return.

| Step | Visitor | System |
| --- | --- | --- |
| 1 | 'Can we meet next week?' | `checkAvailability`: free/busy minus buffers and non-working hours, shown in the visitor's timezone as a card |
| 2 | Taps a slot or says it; speech must match an offered slot | `startBooking`: re-check, pending booking, Redis hold (10 min) |
| 3 | Types name and email in a form | Validate and store (typed, because speech recognition mangles emails) |
| 4 | Sees the summary card: day, time with timezone, duration, invite email | Status `awaiting_confirmation`; nothing has happened yet |
| 5 | Taps Confirm or says yes | `booking_execute`: re-verify hold and free/busy, create the event with a deterministic id, read it back |
| 6 | Sees the confirmed card | Status `confirmed`; the invite goes out; the spoken line is a template filled from stored data |

Components: booking service (owns the state machine, the only code that touches the calendar), availability (`scheduling.yaml` plus free/busy), calendar adapter (`freeBusy`, `createEvent`, `getEvent`, `deleteEvent`; a Google implementation plus an in-memory fake for tests), Postgres `bookings`, Redis holds.

Edge cases:

| Problem | Handling |
| --- | --- |
| Ambiguous time or timezone | Timezone from the browser; backend echoes resolved ISO dates; the agent reads them back; bookings use slot ids, not free text |
| Slot taken between offer and confirm | Re-check at `startBooking` and at execution; offer fresh slots |
| Two visitors, one slot | Redis NX hold plus a unique constraint on slot start |
| Double yes, retry, reconnect replay | Deterministic event id plus unique `idempotency_key`; the second attempt returns the existing booking |
| Barge-in during `executing` | Execution is shielded and finishes; before confirmation, barge-in only stops speech |
| Calendar timeout, outcome unknown | Never retry blindly: look up the event by its id; if it exists it is confirmed, otherwise retry once, then `failed` |
| Calendar down | `failed`, a plain message, and a fallback 'leave a message' saved to `fallback_messages` |
| Model claims success without a booking | Success wording comes only from templates driven by booking status |
| Abandoned or refreshed session | The hold expires and frees the slot; a reconnect resumes from the checkpoint or reports expiry |
| Bots and spam | Rate limits per IP and session, a cap on open holds, a daily limit per email, optional captcha |
| Prompt injection | The model has no booking tool beyond `startBooking`; every call is validated; the state machine rejects out-of-order actions |
| Calendar privacy | Only free/busy is read; event titles never reach the model |

## 8. Observability with LangSmith

- Tracing is on for every graph run: one trace per turn, one span per node. Metadata on each trace: `turn_id`, git sha, `prompt_version`, `kb_version`, route. It is enabled through the SDK's environment variables; check the current docs for names.
- Privacy: mask visitor names and emails before they leave the process. Booking form fields are never sent in clear.
- Stage timings (query embedding, search, LLM first token, tool, TTS) are recorded in state and in `turn_log`. p50 and p95 per stage are computed from eval runs of at least 100 turns, because live traffic is too small for a stable p95.
- Datasets and experiments: eval cases live in the repo (the source of truth) and sync to LangSmith datasets, so prompt, retrieval and model variants can be compared on the same cases.
- Failure-to-case loop: bad live traces become new eval cases.
- Lock-in guard: a local JSONL turn log means evals run without LangSmith. Confirm that the SDK sends traces in the background so tracing adds no visible latency.

## 9. Evals

| Category | Checks | Start with |
| --- | --- | --- |
| Retrieval | recall@k, MRR, false passes | 15 to 25 queries |
| Grounding and unanswerable | Every claim supported; unsupported questions refused; boundary questions handled | 15 |
| Routing and tool arguments | Right route and tool; ambiguous cases ask | 15 to 40 |
| Multi-turn | Follow-ups keep the topic | 10 |
| Booking | Final state, event count, no duplicates, honest failure; calendar fakes inject timeouts and conflicts | 12 to 15 |
| Barge-in | Scripted timelines: speech start, tool begins, interrupt arrives | 6 to 8 |

```yaml
- id: book-014
  fake_calendar: {timeout_after_create: true}
  turns:
    - user: Book the first slot
    - ui: {action: submit_details, name: Test, email: t@example.com}
    - ui: {action: confirm}
  expect: {final_state: confirmed, calendar_events: 1}
```

Graders: code checks (tool, arguments, state, event count; exact), an LLM judge for groundedness (calibrated against about 20 answers you label yourself before it is trusted), and manual review of failures. Each LLM case runs 3 times, and the pass rate is reported per category. Results are stored per git commit so regressions are visible. Deterministic evals run on every change; judged evals run on demand or nightly. Thresholds are set by you in `evals/thresholds.yaml`, and only measured numbers go into the README or resume.

## 10. Repository tree

```
voice-agent/
  README.md
  docs/            design.md, retrieval-plan.md, decisions/ (one short ADR per decision)
  apps/web/        SvelteKit client
  backend/         Python backend
    pyproject.toml
    config.py
    server/            existing: WebSocket handling, sessions, turn manager (turn IDs, barge-in)
    pipeline/          existing: STT, turn handling, TTS streaming
    providers/         existing: Sarvam and Gemini clients
    rag/               existing: current RAG retriever and services
    kb/                existing: loaders, validate, ingest
    graph/             state.py, builder.py, nodes/
    prompts/           system.md, tool_descriptions.yaml
    booking/           state_machine.py, gate.py, execute.py, availability.py, holds.py, templates.py
    tools/             registry.py, schemas.py, search_projects.py, project_detail.py, skills.py, links.py, ...
    calendar/          adapter.py, google.py, fake.py
    observability/     tracing.py, redact.py, timings.py
    tests/
  data/            existing data files (confirm contents in the Phase 0 audit)
  knowledge/       structured/, docs/ (section 6)
  evals/
    cases/         retrieval/ grounding/ routing/ multiturn/ booking/ bargein/
    runner.py judge.py report.py thresholds.yaml
    reports/       one file per run, named by git sha
  infra/           docker-compose.yml (postgres, redis, backend), .env.example
```

## 11. Sub-problems and build order

| ID | Sub-problem | Done when |
| --- | --- | --- |
| S1 | Scaffold the new modules, docker-compose (Postgres, Redis), env | Services start; the converted backend's voice flow passes a smoke test |
| S2 | Author the knowledge files | Every project has a doc and a status; skills have evidence |
| S3 | Validate the knowledge files | Ingest fails on a missing status or evidence id |
| S4 | Ingest: chunk, embed, BM25, persist | The index builds reproducibly; `kb_version` is recorded |
| S5 | Retrieval v1: existing dense search, topic-aware query, threshold | Smoke set questions retrieve the right chunk; unanswerable ones fail the threshold |
| S6 | Smoke set: 10 to 15 questions with the fact each needs | One command shows which questions retrieved the right chunk |
| S7 | Graph skeleton and state, text mode | `/internal/turn` returns grounded answers |
| S8 | System prompt and grounding rules | The unanswerable set passes your threshold |
| S9 | Tool registry and read-only tools | Routing evals meet your target |
| S10 | Cards and UI events | Cards appear while the agent speaks |
| S11 | Turn manager to graph integration, in-process streaming to TTS | Speech in, streamed speech out |
| S12 | Cancellation and barge-in safety | Interrupt timelines show no stale cards or duplicate actions |
| S13 | Availability and calendar adapter plus fake | Slots are computed correctly across timezones |
| S14 | Booking state machine and gate | Every transition is tested, including exits |
| S15 | Idempotent, verified execute plus fallback | Fault-injection runs show zero duplicates and zero false 'booked' |
| S16 | Tracing, redaction, timings | Every run is traced; the p50 and p95 report works |
| S17 | Eval harness, judge calibration, regression history | One command; the judge agrees with your labels |
| S18 | Demo video, README, write-up | A stranger understands it in 90 seconds |

Order: Phase 0 (S1). Phase 1, knowledge base and retrieval v1 (S2 to S6). Phase 2, agent in text mode with tracing (S7, S8, S16). Phase 3, tools (S9, S10). Phase 4, voice integration (S11, S12). Phase 5, booking (S13 to S15). Phase 6, eval harness and polish (S17). Phase 7, retrieval improvement (the retrieval engineering plan, the last build phase). Phase 8, demo (S18). Knowledge and eval authoring take more time than the code, so start both early. Until Phase 7, retrieval stays at v1: your existing dense retriever, a relevance threshold, and a small smoke set of questions.

## 12. Risks and open decisions

| Risk | Mitigation |
| --- | --- |
| Graph overhead adds latency | Time every stage; compare against a plain loop |
| The judge model is unreliable | Calibrate on hand-labelled answers; prefer code checks |
| The agent invents or overclaims | Status tags, similarity threshold, unanswerable evals |
| Cancellation races | `turn_id` guard everywhere; shielded execute |
| Visitor data in traces | Redaction before send |
| Scope creep | Hold to the non-goals; add a second agent or a reranker only when evals show a failure |
| Content work underestimated | Treat S2 and S17 as first-class tasks |

Settled: D1, the backend is Python. Open decisions: D3 RAG versus a full-context prompt, decided by one eval run. D4 index storage: in-memory files by default, pgvector only if needed. D5 reranker or output verifier: only on evidence.

Terms: idempotency means repeating a request leaves one result. A checkpoint is the saved graph state. recall@k is how often a relevant chunk is in the top k. MRR is the average of 1 over the rank of the first relevant chunk. p50 and p95 are the median and 95th-percentile latency. Reciprocal rank fusion merges two ranked lists by position.
