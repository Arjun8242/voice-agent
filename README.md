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

### Booking safety

- Google Calendar is the calendar of record. SQLite (`data/bookings.db`) holds booking state, which moves through atomic status transitions.
- Before creating an event the executor looks it up by id, so a retry after a timeout cannot create a second one. It retries once, then reads the event back.
- The model can never say "booked" or "cancelled". A confirmation appears only when the calendar call really succeeded.
- Rules (one 30-minute meeting, Monday to Friday 10:00 to 17:00 Asia/Kolkata, 12 hours minimum notice, 14-day horizon, 30 minutes kept free after busy time) live in `knowledge_base/structured/scheduling.yaml`. Times are shown in the visitor's timezone.

## Interview mode

Open `/app` (the landing page at `/` links to it). Stay on **interviewer**, press **upload résumé** and pick your resume (PDF), add a job description if you have one, press **analyse résumé** and check the one-line preview of what the interview will cover, then pick an interviewer with the arrows (Sapwa, calm and gives hints, or Sheru Bhai, strict) and press **let's go**. The stage chips above the interviewer follow the interview: after each interview turn the server sends `interview_stage` (the current topic's stage, or `wrap` once the closing line is spoken; no `turnId`, like `interview_report`). The interview runs in stages: an intro, then deep-dives, technical, behavioural and achievement questions when the plan has them, and you answer out loud. Each session's plan is built from the candidate's resume PDF and an optional job description, uploaded before the interview starts.

```
START -> ingest -> steer --> interviewer (one Groq call) -> advance --> response -> END
                       |---> move (next topic's first question, spoken by code) '
                       |---> repeat ("can you repeat that", no LLM) --'
                       |---> nudge (you stayed silent, no LLM) -------'
                       '---> close (end, time cap, last topic, no LLM) '
```

- **Planned from the resume, checked by code.** `POST /interview/upload` rejects a scan or a file that is not a PDF before any LLM call, strips contact details (`backend/interview/resume.py`), then makes one Groq call that reads the resume and JD (`backend/interview/analyze.py`, `backend/prompts/analyzer.md`). Every claim it returns must quote the resume; code drops any claim whose quote is not really there. Code then builds one topic per stage from what is left (`backend/interview/assemble.py`), and falls back to a plan about the resume as a whole if the call fails twice. Resume and JD text are wrapped as data, never instructions.
- **Grounded.** Each topic's notes hold only verified claims and the JD requirement. The interviewer may ask only about those notes or about what you said, and never states a fact outside them (`backend/prompts/interviewer.md`).
- **Code owns the pacing.** Code asks every first question: the opening, each topic's seed question and a bridge line between stages. The model only writes follow-ups, starting each reply with a control line such as `[[decision=probe]]`, which is never spoken. Each topic has a minimum and maximum number of questions and a top rung on its follow-up ladder, set by its stage (`backend/interview/plan.py`); `backend/graph/interview/pacing.py` offers the model only the decisions that fit, and stops a topic early when later stages need the time for their minimums. The interview ends after 15 minutes (`INTERVIEW_MAX_SECONDS`).
- **Mis-heard terms.** Before anything else, code puts tech names the speech-to-text split or mis-heard back together from the session's glossary ("post gress" -> "PostgreSQL", `backend/interview/glossary.py`) and keeps the corrections with the answer.
- **Clarifications are free.** "Repeat that", "can I get a hint", "what do you mean", "skip" and "let's end the interview" are recognised by fixed phrases (`backend/interview/intents.py`). Repeat needs no LLM call, and none of them is graded. A request for help in other words ("I want some level of hint now") is labelled `hint_request` by the model in its control tag; code then gives or declines the hint by the persona's rule, and nothing the model wrote after the label is spoken.
- **Two interviewers** (`backend/interview/personas.py`): *neutral* (calm, hints on request, gentle nudges after 15 s and 45 s of silence) and *strict* (exacting, challenges choices, no hints or nudges, a different voice).
- **Turn-taking.** `backend/pipeline/turn_taking.py` holds each final transcript before taking the turn: 1.2 s after a complete sentence, 2.5 s after a trailing "and" or "um", 20 s after "let me think". Any new speech cancels the wait. Recruiter mode uses the same controller with shorter holds (300 ms and 800 ms). While the agent's audio plays, only words cut it off (`backend/pipeline/barge_in.py`): an "okay", "mm" or a cough does not.
- **Report.** When the interview ends, one more Groq call reviews each answer (not the intro) against its stage's rubric and gives a band, strong, ok or weak, instead of a score. It names the topic's key points the answer covered and missed by number, so the report shows the framework's own words, never the model's; plus one improvement per answer and three strengths and three things to work on overall (`backend/interview/evaluate.py`, `backend/prompts/evaluator.md`). Code adds the question and transcript, the answer framework, a JD-gap flag, a band per stage, and every term speech recognition got wrong, which never counts against the answer (`backend/interview/report.py`).
- **Less Sarvam spend.** Every fixed line the interviewer speaks (opening, intro, bridges, nudges, closing and the five behavioral questions) is synthesised once per voice and then played from `data/tts_cache/` (`backend/pipeline/fixed_audio.py`); nothing the model writes or the candidate says is stored. When the interview ends, the server closes the speech-to-text socket, which is billed per open minute, and drops any audio still arriving; the page stops the mic.
- **Try it in text first.** `POST /internal/turn` with `"mode": "interview"` runs the same interviewer with no speech cost (see [Observability](#observability)).

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
  server/      WebSocket endpoint, connection and session handling, the interview resume upload
  pipeline/    voice turn, sentence splitting, barge-in, turn-taking
  graph/       the LangGraph agent: nodes, state, runner, internal API
    interview/ the interview graph: state, nodes, flow (topic moves, the end), pacing (budgets, time), prompt, control tag
  interview/   resume checks, the analysis call, plan assembly and stage budgets, intents, personas and fixed lines, glossary, the evaluator
  tools/       searchProjects, getProjectDetail, getSkills, getLinks, checkAvailability, startBooking, cancelBooking
  booking/     availability, booking store, executor
  gcal/        Google Calendar adapter and the fake
  rag/         retriever and the Groq client
  kb/          knowledge-base validation and index building
  providers/   Sarvam STT and TTS clients
  prompts/     system prompt, tool descriptions, interviewer and evaluator prompts
  observability/  turn timings, LangSmith redaction
  evals/       eval suites and runners
  tests/       pytest suite, by area: voice/, recruiter/, shared/, interview/unit/, interview/workflow/; helpers.py holds the shared fakes
web/           SvelteKit client
knowledge_base/  structured YAML (projects, skills, links, experience, scheduling) and markdown docs
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

Open the address Vite prints: `/` is the landing page and `/app` is the talk screen. Allow the microphone there. The talk screen connects to `ws://localhost:3001` and sends the résumé upload through the Vite proxy; `web/.env.example` shows how to point both at a deployed server (`VITE_WS_URL`, `VITE_API_URL`, read in `web/src/lib/backend.ts`). When the page and the server are on different domains, list the page's origin in the server's `CORS_ORIGINS`. The upload is limited to 5 per address per 10 minutes (behind a reverse proxy, run uvicorn with `--proxy-headers` so the limit sees real addresses). A finished interview's topics and answers are dropped from server memory when the visitor leaves; an unfinished one is kept so a reload can resume it. The characters are drawn in `web/src/lib/characters.ts` and animated by `Character.svelte`, which pauses off screen, in hidden tabs and under reduced motion.

`.env.example` lists every setting. By default `CALENDAR_BACKEND=fake`, so bookings are kept in memory and no invite is sent. To use your real calendar, set `CALENDAR_BACKEND=google` and provide `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN`. To get the refresh token, put your OAuth client file at `scripts/client_secret.json` (git-ignored) and run `python scripts/google_auth.py`.

## Editing the knowledge base

Facts live in `knowledge_base/`. After changing anything there, run the validator and rebuild the index (the two commands above). The validator checks the YAML, the project documents and their headings, and warns about first-person wording.

## Tests

```bash
python -m pytest backend/tests -q
cd web && npm test
```

The suite uses a scripted model, a fake calendar and a mocked Google transport, so it needs no network and no keys.

## Evals

Evals call the real model, so they need a Groq key, except `run_smoke` and `run_pacing`. All case files are in `backend/evals/` and are checked by code; only the interview follow-up eval adds a judge model.

| Suite | What it checks |
|---|---|
| `routing.yaml` | the right tool with the right arguments, or no tool |
| `unanswerable.yaml` | refusals, false premises, boundary rules, prompt injection |
| `grounded.yaml` | facts that must come from the knowledge base |
| `booking.yaml` | multi-turn booking, fault injection, timezones, injection |
| `smoke.yaml` | retrieval only: is the right chunk in the top results (no model, no Groq tokens) |
| `plans.yaml` | interview: résumé + job description to plan. Valid JSON, the expected stages, a sensible deep dive, a gap as the technical topic, injected text kept out, and the share of the model's claims found in the résumé |
| `followups.yaml` | interview: the follow-up to a scripted answer. Code checks (no control tag, no injected text) plus an LLM judge (`followup_judge.md`): refers to the answer, invents nothing, asks one question. The judge is a different model from the interviewer (`GROQ_JUDGE_MODEL`, default `llama-3.3-70b-versatile`), at temperature 0 in JSON mode |
| `run_pacing.py` | interview pacing over three plan shapes, two candidates and answers of 30 s to 2 min (no model, no tokens) |

```bash
python -m backend.evals.run_questions --suite routing --runs 3
python -m backend.evals.run_booking --runs 3
python -m backend.evals.run_all --runs 3        # all four, saved to reports/<git sha>.json
python -m backend.evals.run_smoke               # retrieval only
python -m backend.evals.run_pacing              # interview pacing, no tokens
python -m backend.evals.run_plans               # interview plans: 1-2 analysis calls per case
python -m backend.evals.run_followups           # interview follow-ups: 8 cases, 2 calls each
```

Real résumés for the plan eval go in `data/eval_resumes.yaml` (git-ignored, like the PDFs it points to), with the same keys as `plans.yaml` plus `pdf`, `optional_stages` and `rejected`; `run_plans` adds them when the file exists, and reads each PDF the way the upload does.

Pass-rate targets are in `backend/evals/thresholds.yaml`. A turn that errors always fails its case.

Groq's free tier allows about 200,000 tokens a day, which is roughly 80 model calls. A full eval run can use it up, and runs after that fail with rate-limit errors. Run one suite at a time or use a paid tier.

## Observability

Every spoken turn appends one JSON line (STT, the end-of-turn hold and why the turn was taken, retrieval, first token, first audio, total, barge-in latency, tools used, and the LLM tokens Groq reported: input, output, cached and reasoning) to `data/turn_log.jsonl`. `/internal/turn` returns the same token counts as `usage`. When Sarvam ends an STT session, one more line records the audio seconds it billed. The visitor's words are not stored. A p50/p95 report:

```bash
python -m backend.observability.timings
```

Optional LangSmith tracing is switched on with the `LANGSMITH_*` settings. Names, emails and meeting titles are masked before anything is sent.

`POST /internal/turn` runs the same agent from text alone, for testing without speech. It is disabled unless `INTERNAL_API_KEY` is set.

With `"mode": "interview"` it runs the mock interviewer instead, so it can be tried with no Sarvam spend (follow-up turns still call Groq; first questions are spoken by code). Upload a resume for the session first (`session_id` must be 32 hex characters); leave out `answer` to get the opening question; `persona` (`neutral` or `strict`) is read on the first turn. The reply includes the flow state: topic, level, follow-ups used, the control-tag decision and the recorded answers.

```bash
SID=0123456789abcdef0123456789abcdef
curl -s localhost:3001/interview/upload -H "content-type: application/json" -d "{\"session_id\": \"$SID\", \"resume_pdf\": \"$(base64 -w0 resume.pdf)\", \"job_description\": \"Backend engineer, Java\"}"
curl -s localhost:3001/internal/turn -H "api-key: $INTERNAL_API_KEY" -H "content-type: application/json" -d "{\"session_id\": \"$SID\", \"mode\": \"interview\", \"persona\": \"strict\"}"
curl -s localhost:3001/internal/turn -H "api-key: $INTERNAL_API_KEY" -H "content-type: application/json" -d "{\"session_id\": \"$SID\", \"mode\": \"interview\", \"answer\": \"I'm a final-year student.\"}"
```

The upload costs one Groq call and no Sarvam. The plan is kept in memory until the session's WebSocket closes.

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
- Both interviewers have male voices set in `backend/interview/personas.py`: Sapwa (neutral) `aditya`, meant to be the lighter one, and Sheru Bhai (strict) `shubh`, meant to be the deeper one. Sarvam labels Shubh male but documents no gender or depth for the other voices, so confirm both by ear in the Sarvam playground and swap the name if needed. A new voice gets its own folder in `data/tts_cache/`.
- The interview report is not yet calibrated against hand-scored answers, and interviews have no eval suite yet.
- If you speak before pressing Start, speech-to-text keeps the recruiter's shorter end-of-speech silence until the page is reloaded.

## What is next

Improving retrieval is the last planned phase: a labelled benchmark, comparison of strategies and before/after measurements.
