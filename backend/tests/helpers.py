"""Shared fakes for the test files: a scheduling config, a scripted model, a small knowledge base,
a fake graph stream, and a driver for the whole booking flow. No network anywhere."""

import asyncio
import importlib
from datetime import datetime, timezone

from backend.booking.execute import BookingExecutor
from backend.booking.store import BookingStore
from backend.gcal import FakeCalendar
from backend.graph.graph import build_graph
from backend.graph.nodes.booking_gate import create_booking_gate_node
from backend.graph.runner import run_turn
from backend.kb.validate import Experience, Link, Project, Scheduling, Skill
from backend.tools.kb_data import KbData

# the package re-exports the function voice_turn, which hides the module of the same name
vt = importlib.import_module("backend.pipeline.voice_turn")

UTC = timezone.utc
# 2026-11-06 is a Friday, so the first working day after it is Monday 2026-11-09; 10:00 IST there is 04:30 UTC
FRIDAY_NOON = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
FIRST_SLOT = "2026-11-09T04:30Z"


def sched(host="Asia/Kolkata", **availability):
    return Scheduling.model_validate({
        "enabled": True,
        "calendar": {"provider": "google_calendar", "calendar_id": "primary", "timezone": host},
        "meeting": {"title": "Technical Discussion", "duration_minutes": 30, "description": "Talk"},
        "availability": {"working_days": ["mon", "tue", "wed", "thu", "fri"], "start_time": "10:00", "end_time": "17:00",
                         "booking_horizon_days": 14, "min_notice_hours": 12, "buffer_minutes": 30, **availability},
        "booking": {"require_name": True, "require_email": True, "require_explicit_confirmation": True,
                    "recheck_availability": True, "prevent_duplicate_bookings": True},
        "ui": {"show_timezone": True, "show_confirmation": True},
    })


# --- the model and the retriever ---------------------------------------------

async def no_retrieval(query, top_k=4, topic=None):
    return {"query": query, "chunks": [], "status": "none_relevant", "combinedContext": ""}


class ScriptedModel:
    """Each agent call takes the next script entry: a list of pieces (str = text, dict = tool call)."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, prompt, system_instruction, tools=None, tool_calls=None):
        self.calls.append({"prompt": prompt, "tools": tools, "tool_calls": tool_calls})
        pieces = self.script.pop(0) if self.script else ["fallback answer"]

        async def gen():
            for p in pieces:
                yield p
        return gen()


def call(name, **args):
    return {"name": name, "args": args}


# --- a small knowledge base ----------------------------------------------------

DESCRIPTIONS = {n: f"{n} description" for n in ("searchProjects", "getProjectDetail", "getSkills", "getLinks")}


def project(pid, name, tech, status="shipped"):
    return Project.model_validate({
        "id": pid, "name": name, "one_line": f"{name} is a test project.", "status": status, "tech": tech,
        "role": "Built it.", "links": {"repo": f"https://example.com/{pid}"}, "highlights": ["h"], "updated": "2026-10-01",
    })


def make_kb() -> KbData:
    return KbData(
        projects=[project("beacon", "Beacon", ["TypeScript", "Redis"]),
                  project("valyrian", "Valyrian", ["Java"], status="runnable_not_deployed")],
        skills=[Skill(id="redis", skill="Redis", category="backend", evidence=["beacon", "acme"]),
                Skill(id="java", skill="Java", category="language", evidence=["valyrian"]),
                Skill(id="pg", skill="PostgreSQL", category="database", evidence=["beacon"]),
                Skill(id="gem", skill="Gemini AI Integration", category="ai", evidence=["beacon"])],
        links=[Link(id="gh", label="GitHub", type="github_profile", url="https://github.com/x", description="Code"),
               Link(id="li", label="LinkedIn", type="professional_profile", url="https://linkedin.com/x", description="Profile")],
        experience=[Experience.model_validate({
            "id": "acme", "organization": "Acme", "role": "Intern", "type": "internship", "start_date": "2025-01",
            "end_date": "2025-06", "current": False, "location": "Remote", "tech": ["Redis"], "one_line": "Intern.",
            "highlights": [{"id": "h1", "description": "Did work."}], "updated": "2026-10-01"})],
        sections={"beacon": {"Overview": "Beacon monitors sites.", "Limitations and Future Work": "No SSO."},
                  "valyrian": {"Overview": "An interpreter."}},
    )


# --- the graph's stream, faked ---------------------------------------------------

class FakeGraph:
    """Stands in for the compiled graph: astream yields (mode, event) like LangGraph does."""

    def __init__(self, events=(), fail=None, hang_after_events=False):
        self.events, self.fail, self.hang = list(events), fail, hang_after_events

    async def astream(self, inputs, config, stream_mode):
        self.inputs, self.config = inputs, config
        for mode, event in self.events:
            yield mode, event
        if self.fail:
            raise self.fail
        if self.hang:
            await asyncio.sleep(10)


# --- the booking flow -------------------------------------------------------------

class Flow:
    """Real graph and gate, the fake calendar, a temp SQLite file, and the executor the connection runs after a confirm.
    Every step is a click on a card, as in the browser; the model is never called."""

    def __init__(self, tmp_path):
        self.store, self.calendar = BookingStore(tmp_path / "bookings.db"), FakeCalendar()
        clock = lambda: FRIDAY_NOON
        gate = create_booking_gate_node(self.store, self.calendar, sched(), clock=clock)
        self.model = ScriptedModel()
        self.graph = build_graph(no_retrieval, self.model, aliases={}, gate=gate)
        self.executor = BookingExecutor(self.store, self.calendar, sched(), clock=clock)
        self.booking_id = None

    def click(self, action, session="s1", **payload):
        out = asyncio.run(run_turn(self.graph, session_id=session, text="", ui_action={"action": action, "payload": payload}))
        handoff = out["booking_execute"]
        out["update"] = asyncio.run(self.executor.run(handoff["booking_id"], handoff["kind"])) if handoff else None
        return out

    def pick(self, slot_id=FIRST_SLOT):
        out = self.click("select_slot", slot_id=slot_id)
        booking = self.store.for_session("s1")
        self.booking_id = booking["booking_id"] if booking else None
        return out

    def to_summary(self, **details):
        self.pick()
        return self.click("submit_details", booking_id=self.booking_id,
                          **({"name": "Priya Shah", "email": "priya@example.com", "title": "Intro"} | details))

    def book(self):
        self.to_summary()
        return self.click("confirm", booking_id=self.booking_id)

    def status(self):
        return self.store.get(self.booking_id)["status"]
