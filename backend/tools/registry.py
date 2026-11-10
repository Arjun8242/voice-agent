"""Tool registry: the only way a model's tool call becomes code that runs.

Every call goes: look up by name -> validate args (pydantic) -> run with a
per-tool timeout -> result or structured error. A bad call never raises; the
model gets {"error": code, "details": ...} back and can correct itself.
Each handler gets the parsed args and ctx: what the session knows (session_id,
visitor_timezone) and the model must never supply. The booking tools are registered
only when booking is enabled in scheduling.yaml and a calendar (and, for startBooking
and cancelBooking, a booking store) is given. None of them can confirm or execute.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError

from .cancel_booking import cancel_booking
from .check_availability import check_availability
from .kb_data import KbData
from .links import get_links, links_args_model
from .project_detail import get_project_detail
from .schemas import (Args, CancelBookingArgs, CheckAvailabilityArgs, GetProjectDetailArgs, GetSkillsArgs, SearchProjectsArgs,
                      StartBookingArgs, ToolError)
from .start_booking import start_booking
from .search_projects import search_projects
from .skills import get_skills

DEFAULT_TIMEOUT_S = 2.0  # the read-only tools are in-memory lookups
CALENDAR_TIMEOUT_S = 8.0  # a calendar tool makes a network call
DESCRIPTIONS_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tool_descriptions.yaml"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[Args]
    handler: Callable[[Args, dict], tuple[dict, list[dict]]]  # (args, ctx) -> (result for the model, cards for the UI)
    timeout_s: float = DEFAULT_TIMEOUT_S


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def declarations(self) -> list[dict]:
        """Name, description and JSON-schema parameters of each tool, for the LLM layer."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.args_model.model_json_schema()}
            for t in self.tools.values()
        ]

    async def execute(self, name: str, args: dict, ctx: dict | None = None) -> dict:
        """Run one call. Returns {name, args, result, cards, ok, ms}; never raises (except cancellation)."""
        start = time.perf_counter()
        record = {"name": name, "args": args, "cards": [], "ok": False}
        tool = self.tools.get(name)
        try:
            if tool is None:
                raise ToolError("unknown_tool", f"No tool '{name}'. Tools: {', '.join(self.tools)}.")
            try:
                parsed = tool.args_model.model_validate(args)
            except ValidationError as err:
                raise ToolError("invalid_args", "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in err.errors()))
            try:
                result, cards = await asyncio.wait_for(asyncio.to_thread(tool.handler, parsed, ctx or {}), tool.timeout_s)
            except TimeoutError:  # the worker thread is not killed, but nobody waits for it
                raise ToolError("timeout", f"{name} took longer than {tool.timeout_s}s.")
            record.update(result=result, cards=cards, ok=True)
        except ToolError as err:
            record["result"] = {"error": err.code, "details": err.details}
        except Exception as err:  # a bug in a handler must not end the turn
            record["result"] = {"error": "tool_failed", "details": f"{type(err).__name__}: {err}"}
        record["ms"] = round((time.perf_counter() - start) * 1000, 1)
        return record


def load_descriptions(path: Path = DESCRIPTIONS_PATH) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: " ".join(text.split()) for name, text in data.items()}


def build_registry(kb: KbData, descriptions: dict[str, str] | None = None, calendar=None, scheduling=None, store=None) -> ToolRegistry:
    """The four read-only tools with the KB bound in, plus the booking tools when booking is enabled.
    Fails at startup if a description is missing."""
    descriptions = descriptions if descriptions is not None else load_descriptions()
    read_only = [
        ("searchProjects", SearchProjectsArgs, search_projects),
        ("getProjectDetail", GetProjectDetailArgs, get_project_detail),
        ("getSkills", GetSkillsArgs, get_skills),
        ("getLinks", links_args_model(kb), get_links),
    ]
    tools = [(name, model, lambda args, ctx, fn=fn: fn(args, kb=kb), DEFAULT_TIMEOUT_S) for name, model, fn in read_only]
    if calendar is not None and scheduling is not None and scheduling.enabled:
        handler = partial(check_availability, cal=calendar, sched=scheduling)
        tools.append(("checkAvailability", CheckAvailabilityArgs, handler, CALENDAR_TIMEOUT_S))
        if store is not None:
            tools.append(("startBooking", StartBookingArgs, partial(start_booking, cal=calendar, sched=scheduling, store=store), CALENDAR_TIMEOUT_S))
            tools.append(("cancelBooking", CancelBookingArgs, partial(cancel_booking, store=store), DEFAULT_TIMEOUT_S))
    missing = [name for name, _, _, _ in tools if not descriptions.get(name)]
    if missing:
        raise ValueError(f"tool_descriptions.yaml has no description for: {', '.join(missing)}")
    return ToolRegistry([Tool(name, descriptions[name], model, handler, timeout) for name, model, handler, timeout in tools])
