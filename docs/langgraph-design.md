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
  pipeline: STT in, TTS out     providers: Sarvam, Groq
      |  in-process call per turn
      v
Agent graph (LangGraph)
  ingest -> retrieve -> agent <-> tools -> respond
                          '--> booking path (gate, execute)
      |               |                 |
      v               v                 v
 Knowledge store   SQLite             Calendar adapter
 (YAML + index)    (session ->        (Google API; fake in tests)
                    booking, event)

LangSmith <-- traces from every graph run
Eval runner --> POST /internal/turn (text mode, no voice)
```

**Decision D1: agent runtime language (settled).** The backend is Python, so the agent graph runs in the same process as the voice pipeline: no separate service and no extra network hop. The turn manager calls the graph directly. FastAPI is assumed in this document; confirm the actual framework when you audit the converted backend in Phase 0.

## 3. System design

### 3.1 One turn, end to end

1. The browser streams mic audio to the backend over WebSocket.
2. The voice pipeline runs STT. Final transcripts are held and merged by the end-of-turn controller (`pipeline/turn_taking.py`) until the visitor is done; a short acknowledgement over the answer is dropped. Then the turn manager assigns a `turn_id`, cancels any turn still running, and starts the agent graph in the same process.
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
| `ui.action` | client to server | action (select\_slot, submit\_details, confirm, cancel\_booking, confirm\_cancel, keep\_booking), payload |
| `booking.update` | server to client | booking\_id, status, card data; no turn\_id |
| `turn.state` | server to client | state: speaking, holding, thinking or idle (the end-of-turn controller in `pipeline/turn_taking.py`); no turn\_id |
| `turn.cancelled` / `error` | server to client | turn\_id / code, message, retryable |

Every turn event carries `turn_id`. The client drops events from turns at or before the last `turn.cancelled`, so a card from an interrupted request never appears late. Session-level events (`session.ready`, `booking.update`) carry no `turn_id` and always pass that guard: a booking result must reach the visitor even when the turn that started it was cut off. `booking.update` carries booking\_id and status, and the client renders it by booking\_id, so a repeat changes nothing.

### 3.3 Internal endpoints (evals and admin)

The voice path calls the graph in the same process, so there is no internal streaming API. These endpoints exist for evals and operations.

| Endpoint | Purpose |
| --- | --- |
| `POST /internal/turn` | Body: session\_id, turn\_id, input (speech text or ui\_action), visitor\_tz. Returns one JSON object: reply, tool calls, cards, stage timings. Runs the same graph as the voice path without STT or TTS; the eval runner uses it. API key only |
| `POST /internal/kb/reindex` | Rebuilds the index (also available as a CLI command) |
| `GET /health` | Liveness |

There is no public booking REST in this version. A recruiter can decline or remove the meeting from the Google invite.

### 3.4 Data stores

| Store | Holds |
| --- | --- |
| SQLite (`data/bookings.db`) | One table, `bookings`. No server and no extra service |
| In memory | LangGraph checkpoints (thread\_id = session\_id), as today (`InMemorySaver`) |
| Files | Knowledge files and the built index (vectors; BM25 only if adopted later), loaded into memory at startup; `data/turn_log.jsonl` |

`bookings`: booking\_id (`uuid4().hex`; it is also the Google event id), session\_id, slot\_start\_utc, visitor\_name, visitor\_email, meeting\_title, visitor\_tz, status, created\_at. Google is the calendar of record: it stores the event, emails the invite and shows the busy times. The table only remembers who booked what in this session. The slot is always 30 minutes, so there is no end column.

## 4. LangGraph design

### 4.1 State

One state object per session, checkpointed in memory after each step; the booking itself lives in SQLite.

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
| `booking` | booking\_id, status, slot\_id, name, email, or empty |
| `final_text`, `errors` | Output for TTS and any failures |

### 4.2 Nodes

| Node | Type | Does |
| --- | --- | --- |
| `ingest_turn` | code | Appends the input, resets per-turn fields, updates topic, picks the next node |
| `booking_gate` | code | Handles input while a booking is waiting: form submit, confirm, cancel, and the yes or no to a cancel request |
| `retrieve` | code | Topic-aware dense search with a relevance threshold (hybrid only if later tests justify it) |
| `agent` | LLM | One Groq call with tools bound; returns text or tool calls |
| `tools` | code | Validates and runs tool calls (read-only ones in parallel), adds cards |
| `booking_execute` | code, session-owned task | Starts the create (re-check, read event by id, create, read back) or the delete of a confirmed booking, and reports through `booking.update` (section 4.5) |
| `respond` | code | Chooses the model's text, or a template for booking outcomes; streams it |

### 4.3 Edges

| From | Condition | To |
| --- | --- | --- |
| START | always | `ingest_turn` |
| `ingest_turn` | booking is awaiting\_details, awaiting\_confirmation or awaiting\_cancel\_confirmation | `booking_gate` |
| `ingest_turn` | otherwise | `retrieve` |
| `booking_gate` | confirm (or confirm\_cancel) recognised | `booking_execute` |
| `booking_gate` | cancel before confirmation, keep\_booking, or details received | `respond` |
| `booking_gate` | anything else (the visitor asked something unrelated) | `retrieve`; the prompt notes a booking is pending |
| `retrieve` | always | `agent` |
| `agent` | tool calls and tool\_steps < 4 | `tools` |
| `agent` | text only, or step cap reached | `respond` |
| `tools` | always | `agent` |
| `booking_execute` | always | `respond` |
| `respond` | always | END |

### 4.4 Pause and resume

Waiting for the visitor does not suspend a run. The run ends with the booking status saved in SQLite, and the next input (a form submit, a click, or speech) starts a new run on the same `thread_id`, where `ingest_turn` routes to `booking_gate`. This keeps state inspectable and survives refreshes and reconnects. LangGraph's interrupt() is an alternative; verify its current behaviour in the docs before choosing it.

### 4.5 Streaming, cancellation, and guarantees

- Tokens from the agent node stream to the turn manager as produced; it cuts sentences for TTS. Verify LangGraph's current streaming modes in its docs.
- A cancel signal stops the run's async task. Events carry `turn_id`, so late output is discarded.
- Execution is a session-owned task, not part of the turn. `asyncio.shield` alone is not enough: it keeps the create-event call alive, but the stream consumer that would deliver the result is cancelled with the turn, and the client drops any event whose `turnId` is at or before the cancelled turn. So `booking_execute` hands the work to a task owned by the connection. When it finishes, the task sends `booking.update` through the connection's raw `send` with no `turn_id` (the way `session_ready` is sent). It runs to completion even if the visitor interrupts, because a half-finished booking is worse than a finished one. The barge-in timelines include a cut-in during `executing`.
- The model may start things but never confirm or execute them. `startBooking` and `cancelBooking` only move a booking to a waiting state. Confirmation reaches the graph only as a `ui_action` click or a transcript the turn manager matches against a strict confirm or cancel set.

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
| `startBooking` | slot\_id, topic? | booking\_id, status awaiting\_details; emits a form card | One pending row in SQLite; nothing external, and the slot is not reserved (section 7.1) |
| `cancelBooking` | none | status awaiting\_cancel\_confirmation, or released; emits a confirm card | Finds this session's booking by `session_id` in SQLite (not from graph state). Before confirmation it just drops the pending row. For a confirmed booking it only asks; the delete runs after the visitor's click |

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
meeting:
  title: <default title>  # used when the visitor does not type one
  duration_minutes: 30    # the only meeting; slots sit on a 30-minute grid
  description: <one line>
min_notice_hours: 12
max_days_ahead: 14
buffer_minutes: 30        # free time kept after every busy time
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

Google Calendar is the calendar. It stores the events, shows the busy times, emails the invite and the cancellation, and can add a Meet link. Our code does four small things: turn Google's busy times into bookable slots, run a confirm-before-book flow, call the Google API safely, and cancel. There is no Postgres, Redis, Docker, holds table or lock. A small SQLite table remembers which booking and which Google event belong to which session.

There is one meeting: 30 minutes. The rules live in `scheduling.yaml`: working days and hours, the 30-minute length, 12 hours of minimum notice, a 14-day horizon, and a 30-minute buffer kept free after every busy time. Slots sit on a 30-minute grid, shown in the visitor's timezone (`compute_slots` in `backend/booking/availability.py`, a pure function). If a rule is `null`, `compute_slots` raises an error instead of guessing a default. The meeting title is not fixed in advance: the visitor may type one in the details form, and `meeting.title` is only the default used when they leave it blank.

States: `awaiting_details`, `awaiting_confirmation`, `executing`, `confirmed`, `awaiting_cancel_confirmation`. Exits: `cancelled`, `failed`. `slots_offered` lives only in graph state (`offered_slots`); no row exists until `startBooking`. A pending booking (`awaiting_details`, `awaiting_confirmation`) reserves nothing, so abandoning it needs no cleanup: `startBooking` replaces the session's pending row. `executing` (create) is the point of no return. A delete is safe to repeat, because Google treats an already-deleted event as success, so it needs no marker state: delete first, then mark `cancelled`. From `awaiting_cancel_confirmation` the booking returns to `confirmed` on keep\_booking or on any unrelated input.

| Step | Visitor | System |
| --- | --- | --- |
| 1 | 'Can we meet next week?' | `checkAvailability`: Google free/busy turned into slots, shown in the visitor's timezone as a card |
| 2 | Taps a slot or says it; speech must match an offered slot | `startBooking`: the slot must be in `offered_slots` and still free; one SQLite row, status `awaiting_details`. Nothing external, nothing reserved |
| 3 | Types name, email and an optional meeting title in a form | Validate and store (typed, because speech recognition mangles emails). The title is trimmed, capped at 80 characters and stripped of line breaks, because it goes into the calendar invite; blank means the default |
| 4 | Sees the summary card: day, time with timezone, duration, invite email | Status `awaiting_confirmation`; nothing has happened yet |
| 5 | Taps Confirm or says yes | `booking_execute` (section 7.1): re-check the slot, read the event by its id, create it if absent, read it back |
| 6 | Sees the confirmed card | Status `confirmed`; Google sends the invite; the spoken line is a template filled from stored data, sent only after Google confirms |
| 7 | 'Cancel my meeting' | `cancelBooking` finds this session's booking and moves it to `awaiting_cancel_confirmation`. The visitor taps Confirm cancel; `booking_execute` deletes the event, status `cancelled` |

Components: `backend/gcal/` (the calendar adapter: `adapter.py` interface, `fake.py` for tests with failure injection, `google.py` using httpx and an OAuth refresh token from `.env`; `CALENDAR_BACKEND=fake|google` picks one), `backend/booking/availability.py` (slots), the booking flow (state machine, gate, execute, templates) and `store.py` (the SQLite table).

### 7.1 Safe confirm and idempotency

- **The status change is the guard.** Confirm runs `UPDATE bookings SET status = 'executing' WHERE booking_id = :id AND status = 'awaiting_confirmation'`. SQLite applies it atomically; if no row changed, this booking was already confirmed or is being confirmed, and the stored result is returned. A double click or a reconnect replay therefore creates one event.
- **Re-check at confirm.** Fresh free/busy goes through `compute_slots` again. If the slot is gone, the visitor is told it was just taken and is offered fresh slots.
- **Our own event id.** The booking id is `uuid4().hex` and is also the Google event id. It is valid as is: lowercase a to v and 0 to 9, 5 to 1024 characters. Google does not guarantee that an id collision is detected at creation, so never depend on a 409. Every attempt calls `get_event(id)` first and creates only if it is absent.
- **A timeout is not a failure.** Never retry blindly: read the event by its id. If it exists the booking is confirmed; if not, retry once, then `failed` with a plain message that points to the contact link.
- **Known limit (a shortcut).** There is no hold or lock, so two visitors who confirm the same slot within the same few milliseconds could both pass the re-check. Normally the second confirm sees the first visitor's event in free/busy and is told the slot was taken. Upgrade if it ever matters: a unique index on the slot start for live rows in `bookings`.

### 7.2 Cancellation

- The agent can cancel only the booking for the current session, found in SQLite by `session_id`, not from graph state. The session id is a random value the browser stores; treat it as a bearer secret.
- It is two steps. `cancelBooking` only moves the booking to `awaiting_cancel_confirmation` and emits a confirm card. A click (`confirm_cancel`) or a strict spoken yes runs the delete. A misheard word cannot delete a meeting.
- A pending booking (before confirm) is just dropped; there is no calendar call.
- A confirmed booking is deleted through the adapter (Google emails the cancellation). A 404 or 410 from Google counts as success. A second cancel returns 'already cancelled'.
- A booking from an earlier session cannot be cancelled through the agent in this version. The recruiter can decline or remove it from the Google invite.

### 7.3 Execution outlives the turn

`booking_execute` runs as a task owned by the connection and reports with `booking.update` (section 4.5). If the visitor interrupts during `executing`, the create still finishes and the confirmed card still appears.

Edge cases:

| Problem | Handling |
| --- | --- |
| Ambiguous time or timezone | Timezone from the browser; the backend echoes resolved ISO dates; the agent reads them back; bookings use slot ids, not free text |
| Slot taken between offer and confirm | Re-checked at `startBooking` and again at confirm; offer fresh slots |
| Double yes, retry, reconnect replay | The status change (7.1) lets one through; the others get the stored result; `get_event(id)` runs before any create |
| Barge-in during `executing` | The session-owned task finishes and sends `booking.update` with no `turn_id`; before confirmation, barge-in only stops speech |
| Calendar timeout, outcome unknown | Read the event by its id; if it exists it is confirmed, otherwise retry once, then `failed` |
| Calendar down | `failed`, a plain message, and the contact link |
| Model claims success without a booking | Success wording comes only from templates driven by booking status |
| Abandoned or refreshed session | A pending row reserves nothing, so there is nothing to release; a reconnect resumes the session's row |
| Bots and spam | Rate limits per IP and session; one pending booking per session |
| Prompt injection | The model may start things (`startBooking`, `cancelBooking`) but never confirm or execute; every call is validated; the state machine rejects out-of-order actions |
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
| Barge-in | Scripted timelines: speech start, tool begins, interrupt arrives, interrupt during `executing` (the confirmed card must still arrive) | 6 to 8 |

```yaml
- id: book-014
  fake_calendar: {timeout_after_create: true}
  turns:
    - user: Book the first slot
    - ui: {action: submit_details, name: Test, email: t@example.com}
    - ui: {action: confirm}
  expect: {final_state: confirmed, calendar_events: 1}
```

Graders: code checks (tool, arguments, state, event count; exact), an LLM judge for groundedness (calibrated against about 20 answers you label yourself before it is trusted), and manual review of failures. Each LLM case runs 3 times, and the pass rate is reported per category. Results are stored per git commit so regressions are visible. Deterministic evals run on every change; judged evals run on demand or nightly. Thresholds are set by you in `backend/evals/thresholds.yaml`, and only measured numbers go into the README or resume.

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
    providers/         existing: Sarvam and Groq clients
    rag/               existing: current RAG retriever and services
    kb/                existing: loaders, validate, ingest
    graph/             state.py, builder.py, nodes/
    prompts/           system.md, tool_descriptions.yaml
    booking/           availability.py, store.py (SQLite table and the allowed status changes), gate.py, execute.py (create and cancel), templates.py
    tools/             registry.py, schemas.py, search_projects.py, project_detail.py, skills.py, links.py, check_availability.py, start_booking.py, cancel_booking.py, ...
    gcal/              adapter.py, fake.py, google.py (named gcal so it cannot shadow Python's calendar module)
    observability/     tracing.py, redact.py, timings.py
    tests/             one file per workflow or section: helpers.py (shared fakes), test_booking.py, test_agent.py, test_spoken_answer.py, test_voice_conversation.py (barge-in and session start), test_knowledge_base.py, test_google_calendar.py, test_observability.py
    evals/             real LLM, fake calendar. Cases: routing.yaml (right tool and arguments), unanswerable.yaml (refusals, boundaries, invented projects), grounded.yaml (facts from the knowledge base), booking.yaml (multi-turn and the whole flow), smoke.yaml (retrieval only)
                       Runners: run_questions.py (routing, unanswerable, grounded), run_booking.py, run_smoke.py, run_all.py (every suite, writes the report). Targets: thresholds.yaml
                       A judge for groundedness is planned (judge.py) and not built; the grounded and unanswerable suites use code checks until then
  data/            existing data files (confirm contents in the Phase 0 audit)
  knowledge_base/  structured/, docs/ (section 6)
  reports/         one file per run_all run, named by git sha (-dirty when uncommitted)
  .env.example
```

## 11. Sub-problems and build order

| ID | Sub-problem | Done when |
| --- | --- | --- |
| S1 | Scaffold the new modules and env (no extra services) | The converted backend's voice flow passes a smoke test |
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
| S14 | Booking state machine, SQLite store and gate, including the cancel states | Every transition is tested, including exits and a double confirm |
| S15 | Confirm and cancel against the fake, then Google; a session-owned task | Fault-injection runs (timeouts, conflicts) show zero duplicates and zero false 'booked'; a cut-in during `executing` still delivers the confirmed card |
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
| Cancellation races | `turn_id` guard on turn events; execute and cancel run as a session-owned task that reports through `booking.update` with no `turn_id` |
| Visitor data in traces | Redaction before send |
| Scope creep | Hold to the non-goals; add a second agent or a reranker only when evals show a failure |
| Content work underestimated | Treat S2 and S17 as first-class tasks |

Settled: D1, the backend is Python. Open decisions: D3 RAG versus a full-context prompt, decided by one eval run. D4 index storage: in-memory files by default, pgvector only if needed. D5 reranker or output verifier: only on evidence.

Terms: idempotency means repeating a request leaves one result. A checkpoint is the saved graph state. recall@k is how often a relevant chunk is in the top k. MRR is the average of 1 over the rank of the first relevant chunk. p50 and p95 are the median and 95th-percentile latency. Reciprocal rank fusion merges two ranked lists by position.
