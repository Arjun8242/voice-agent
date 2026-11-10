"""redact.py: mask the visitor's name, email and meeting title before a trace leaves the process.

Masked: email, visitor_email, visitor_name and meeting_title anywhere; name and title only inside
booking data (a ui_action payload or a booking_* card), because elsewhere those keys hold tool names
and link titles; and any email address inside free text, such as a spoken one.
"""

from __future__ import annotations

import re
from functools import lru_cache

MASK = "[redacted]"
ALWAYS = {"email", "visitor_email", "visitor_name", "meeting_title"}
IN_BOOKING = {"name", "title"}
EMAIL_IN_TEXT = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def redact(value, booking: bool = False):
    if isinstance(value, str):
        return EMAIL_IN_TEXT.sub(MASK, value)
    if isinstance(value, (list, tuple)):
        return [redact(item, booking) for item in value]
    if not isinstance(value, dict):
        return value
    # a booking card ({type: booking_*, data}) or a click ({action, payload}): its children are booking data
    children_booking = booking or str(value.get("type", "")).startswith("booking_") or {"action", "payload"} <= value.keys()
    return {key: MASK if key in ALWAYS or (booking and key in IN_BOOKING) else redact(item, children_booking)
            for key, item in value.items()}


@lru_cache(maxsize=1)
def _tracer():
    from langchain_core.tracers import LangChainTracer
    from langsmith import Client

    return LangChainTracer(client=Client(hide_inputs=redact, hide_outputs=redact))


def tracing_callbacks() -> list:
    """[the masked tracer] when tracing is on, else []: nothing is sent while tracing is off."""
    from langsmith.utils import tracing_is_enabled

    return [_tracer()] if tracing_is_enabled() else []
