"""session.py: Conversation state and turn lifecycle helpers.

Corresponds to src/server/session.ts.
"""
import asyncio
from typing import Any


class Conversation:
    def __init__(self):
        self.history: list[dict] = []
        self.sentence_counter: int = 0
        self.agent_speaking: bool = False
        self.current: asyncio.Task | None = None


def new_conversation() -> Conversation:
    return Conversation()


def start_turn(c: Conversation, task: asyncio.Task) -> asyncio.Task:
    """Cancel any in-flight turn, store the new task, reset agent_speaking."""
    if c.current is not None:
        c.current.cancel()
    c.current = task
    c.agent_speaking = False
    return task


def interrupt_turn(c: Conversation) -> None:
    """Cancel and clear the current turn (barge-in or connection close)."""
    if c.current is not None:
        c.current.cancel()
    c.current = None
    c.agent_speaking = False


def finish_turn(c: Conversation, task: asyncio.Task) -> None:
    """Clear current only if this task is still the active one."""
    if c.current is task:
        c.current = None


def is_answering(c: Conversation) -> bool:
    return c.current is not None
