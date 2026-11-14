# Voice Career Agent

A voice assistant that speaks about Arjun, a backend developer, to recruiters and engineers. A visitor talks to it in the browser. It answers out loud from a verified knowledge base, shows project and link cards on screen, and can book a 30-minute meeting on Arjun's Google Calendar.

It also has a **mock interview mode**: a spoken technical interviewer that asks about the same projects, grounded in the same documents, and ends with a scored report.

It is built to be honest about what it does not know: it answers only from the knowledge base, says "he does not list that skill" when a skill is missing, and never claims a meeting is booked until the calendar says so.

## What it does

- **Waits for you to finish.** A short pause, a trailing "and…" or "let me think" does not end your turn, and an "okay" while the agent talks does not cut it off (see [Interview mode](#interview-mode)).
- **Talk or interrupt.** Speech goes in through Sarvam speech-to-text and comes back through Sarvam text-to-speech, sentence by sentence. If the visitor cuts in, the running turn is cancelled and the agent remembers only what was actually heard.
- **Answers from evidence.** Questions about projects, decisions and limitations are answered from retrieved excerpts. Questions about skills, project lists and links go through tools, so a missing skill is stated plainly and a project's status (shipped, runs locally, in progress) is reported exactly.
- **Shows cards.** Project details, profile links and available meeting times appear on screen next to the spoken answer.
- **Books meetings.** The visitor picks a time, types their name and email in an on-screen form, and confirms on screen. The agent can also start a cancellation, which the visitor confirms the same way.
- **Respects boundaries.** Salary, phone number, academic details, other offers and similar topics follow written rules in `knowledge_base/docs/boundaries.md`. The agent never states a number for them and refers the visitor to Arjun.
- **Resists prompt injection.** It does not read out its own instructions, treat pasted "tool results" or "system" text as real, or confirm a booking from spoken words alone.

## How a turn works

```
browser mic -> WebSocket -> Sarvam STT -> LangGraph -> sentences -> Sarvam TTS -> browser
                                              |
   START -> ingest -> retrieve -> agent <-> tools -> response -> END
                  \-> booking_gate (card clicks) -> response
```

- `ingest` records the message and works out which project the visitor is talking about.
- `retrieve` finds the best excerpts from the knowledge base (local `BAAI/bge-small-en-v1.5` embeddings).
- `agent` is one Groq call (`openai/gpt-oss-120b`) with the tools attached. If it asks for tools, they run and their results go back to the model as proper tool messages, up to 4 calls per turn. After that it must answer.
- `booking_gate` handles card clicks (pick a time, submit details, confirm, cancel) in plain code. The model is not involved, and the confirmation words come from fixed templates.

The design is written up in [docs/langgraph-design.md](docs/langgraph-design.md).

### Booking safety

- Google Calendar is the calendar of record. SQLite (`data/bookings.db`) holds booking state, which moves through atomic status transitions.
- Before creating an event the executor looks it up by id, so a retry after a timeout cannot create a second one. It retries once, then reads the event back.
- The model can never say "booked" or "cancelled". A confirmation appears only when the calendar call really succeeded.
- Rules (one 30-minute meeting, Monday to Friday 10:00 to 17:00 Asia/Kolkata, 12 hours minimum notice, 14-day horizon, 30 minutes kept free after busy time) live in `knowledge_base/structured/scheduling.yaml`. Times are shown in the visitor's timezone.

## Interview mode

Pick **Mock interview** in the page, choose an interviewer and press **Start interview**. The interviewer asks about each project in turn, then the internship, and you answer out loud.

```
START -> ingest -> steer --> interviewer (one Groq call) -> advance --> response -> END
                       |---> repeat ("can you repeat that", no LLM) --'
                       |---> nudge (you stayed silent, no LLM) -------'
                       '---> close (end, time cap, last topic, no LLM) '
```

- **Grounded.** Each topic is a whole project document from `knowledge_base/docs/projects/` (or the internship from `experience.yaml`). The interviewer may ask only about those notes or about what you said, and never states a fact outside them (`backend/prompts/interviewer.md`).
- **The model proposes, code decides.** The model starts each reply with a control line such as `[[decision=probe]]`, which is never spoken. Code in `backend/graph/interview/flow.py` caps follow-ups per topic, climbs a difficulty ladder (explain, then justify, then stress), moves between topics and ends the interview after 10 minutes (`INTERVIEW_MAX_SECONDS`).
- **Clarifications are free.** "Repeat that", "can I get a hint", "what do you mean", "skip" and "let's end the interview" are recognised by fixed phrases (`backend/interview/intents.py`). Repeat needs no LLM call, and none of them is graded.
- **Two interviewers** (`backend/interview/personas.py`): *neutral* (calm, hints on request, gentle nudges after 15 s and 45 s of silence) and *strict* (exacting, challenges choices, no hints or nudges, a different voice).
- **Turn-taking.** `backend/pipeline/turn_taking.py` holds each final transcript before taking the turn: 1.2 s after a complete sentence, 2.5 s after a trailing "and" or "um", 20 s after "let me think". Any new speech cancels the wait. Recruiter mode uses the same controller with shorter holds (300 ms and 800 ms).
- **Report.** When the interview ends, one more Groq call scores each answer from 1 to 5 against the notes. It lists what you got right, missed or got wrong, each with a quote from the notes, plus three tips. Code drops any point whose quote is not really in the notes (`backend/interview/evaluate.py`).
- **Try it in text first.** `POST /internal/turn` with `"mode": "interview"` runs the same interviewer with no speech cost (see [Observability](#observability)).

The audit and design are in [docs/interviewer-mode-plan.md](docs/interviewer-mode-plan.md); what was built, step by step, is in [docs/interviewer-mode-features.md](docs/interviewer-mode-features.md).

## Stack

| Part | Choice |
|---|---|
| Client | SvelteKit, Svelte 5, Tailwind (`web/`) |
| Server | Python 3.12, FastAPI, WebSocket (`backend/`) |
| Agent | LangGraph, in-memory checkpointer |
| LLM | Groq, `openai/gpt-oss-120b` |
| Speech | Sarvam STT and TTS |
| Retrieval | sentence-transformers, bge-small, vectors stored in `data/kb_index.json` |
| Calendar | Google Calendar API over httpx; an in-memory fake for tests and evals |
| Storage | SQLite for bookings, a JSON-lines turn log for timings |

## Repository layout

```
backend/
  server/      WebSocket endpoint, connection and session handling
  pipeline/    voice turn, sentence splitting, barge-in, turn-taking
  graph/       the LangGraph agent: nodes, state, runner, internal API
    interview/ the interview graph: state, nodes, flow (caps, ladder, topics), prompt, control tag
  interview/   interview topics, intents, personas and the end-of-interview evaluator
  tools/       searchProjects, getProjectDetail, getSkills, getLinks, checkAvailability, startBooking, cancelBooking
  booking/     availability, booking store, executor
  gcal/        Google Calendar adapter and the fake
  rag/         retriever and the Groq client
  kb/          knowledge-base validation and index building
  providers/   Sarvam STT and TTS clients
  prompts/     system prompt, tool descriptions, interviewer and evaluator prompts
  observability/  turn timings, LangSmith redaction
  evals/       eval suites and runners
  tests/       pytest suite
web/           SvelteKit client
knowledge_base/  structured YAML (projects, skills, links, experience, scheduling) and markdown docs
docs/          design documents
```

## Setup

You need Python 3.12 or newer, Node.js, a [Groq](https://console.groq.com) API key and a [Sarvam](https://www.sarvam.ai) API key.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e "backend[dev]"      # [dev] adds pytest
cp .env.example .env              # then fill in the keys
```

Check the knowledge base and build its search index (the first run downloads the embedding model):

```bash
python -m backend.kb.validate knowledge_base
python -m backend.kb.ingest knowledge_base --out data/kb_index.json
```

Run the server and the client in two terminals:

```bash
python -m uvicorn backend.server.main:app --port 3001
```

```bash
cd web
npm install
npm run dev
```

Open the address Vite prints and allow the microphone. The page connects to `ws://localhost:3001` (set in `web/src/routes/+page.svelte`).

`.env.example` lists every setting. By default `CALENDAR_BACKEND=fake`, so bookings are kept in memory and no invite is sent. To use your real calendar, set `CALENDAR_BACKEND=google` and provide `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN`.

## Editing the knowledge base

Facts live in `knowledge_base/`. After changing anything there, run the validator and rebuild the index (the two commands above). The validator checks the YAML, the project documents and their headings, and warns about first-person wording.

## Tests

```bash
python -m pytest backend/tests -q
cd web && npm test
```

The suite uses a scripted model, a fake calendar and a mocked Google transport, so it needs no network and no keys.

## Evals

Evals call the real model, so they need a Groq key. All case files are in `backend/evals/` and are checked by code, not by a judge model.

| Suite | What it checks |
|---|---|
| `routing.yaml` | the right tool with the right arguments, or no tool |
| `unanswerable.yaml` | refusals, false premises, boundary rules, prompt injection |
| `grounded.yaml` | facts that must come from the knowledge base |
| `booking.yaml` | multi-turn booking, fault injection, timezones, injection |
| `smoke.yaml` | retrieval only: is the right chunk in the top results (no model, no Groq tokens) |

```bash
python -m backend.evals.run_questions --suite routing --runs 3
python -m backend.evals.run_booking --runs 3
python -m backend.evals.run_all --runs 3        # all four, saved to reports/<git sha>.json
python -m backend.evals.run_smoke               # retrieval only
```

Pass-rate targets are in `backend/evals/thresholds.yaml`. A turn that errors always fails its case.

Groq's free tier allows about 200,000 tokens a day, which is roughly 80 model calls. A full eval run can use it up, and runs after that fail with rate-limit errors. Run one suite at a time or use a paid tier.

## Observability

Every spoken turn appends one JSON line (STT, the end-of-turn hold and why the turn was taken, retrieval, first token, first audio, total, barge-in latency, tools used, and the LLM tokens Groq reported: input, output, cached and reasoning) to `data/turn_log.jsonl`. `/internal/turn` returns the same token counts as `usage`. When Sarvam ends an STT session, one more line records the audio seconds it billed. The visitor's words are not stored. A p50/p95 report:

```bash
python -m backend.observability.timings
```

Optional LangSmith tracing is switched on with the `LANGSMITH_*` settings. Names, emails and meeting titles are masked before anything is sent.

`POST /internal/turn` runs the same agent from text alone, for testing without speech. It is disabled unless `INTERNAL_API_KEY` is set.

With `"mode": "interview"` it runs the mock interviewer instead, so it can be tried with no Sarvam spend (each turn still calls Groq). Leave out `answer` to get the opening question; `persona` (`neutral` or `strict`) is read on the first turn. The reply includes the flow state: topic, level, follow-ups used, the control-tag decision and the recorded answers.

```bash
curl -s localhost:3001/internal/turn -H "api-key: $INTERNAL_API_KEY" -H "content-type: application/json"   -d '{"session_id": "iv1", "mode": "interview", "persona": "strict"}'
curl -s localhost:3001/internal/turn -H "api-key: $INTERNAL_API_KEY" -H "content-type: application/json"   -d '{"session_id": "iv1", "mode": "interview", "answer": "It schedules checks with a Postgres lock."}'
```

## Measured so far

- **Latency** (183 logged turns; some used an earlier Gemini setup, so treat it as indicative): first token p50 1.4 s and p95 4.9 s, end of turn p50 2.7 s and p95 6.6 s.
- **Evals** (9 November 2026, 3 runs per case): routing 50/54, unanswerable 24/27, grounded 12/15 (below its 83% target), booking 33/33. The case sets have been revised since, and several new cases have not yet produced valid results because of the Groq daily limit.

## Known limits

- The visitor types name and email in an on-screen form. Spoken name, email and yes/no for booking are not built.
- Conversation memory lives in the running server process and is lost on restart.
- Misheard project names can fail: "bacon" for Beacon sends the agent to search instead of opening the project.
- Retrieval misses some phrasings. "Has he implemented an interpreter from scratch?" does not surface the Valyrian project text.
- Groundedness is checked with word and phrase matching, not a judge model, so a correct answer worded unexpectedly can fail.
- Evals use the fake calendar, so the Google adapter is covered only by mocked unit tests.
- Interview mode has not yet been run against real Groq and Sarvam end to end. Its hold times, nudge times and STT silence (`STT_INTERVIEW_SILENCE_MS`) are starting guesses from the plan, not measurements.
- The turn-taking word lists are English with a few Hinglish fillers. A phrase they miss is treated as a normal answer.
- The strict interviewer's voice (`shubh`) is assumed to be male: Sarvam's docs do not give voice genders.
- The interview report is not yet calibrated against hand-scored answers, and interviews have no eval suite yet.
- If you speak before pressing Start, speech-to-text keeps the recruiter's shorter end-of-speech silence until the page is reloaded.

## What is next

Improving retrieval is the last planned phase: a labelled benchmark, comparison of strategies and before/after measurements. The plan is in [docs/retrieval-design.md](docs/retrieval-design.md).
