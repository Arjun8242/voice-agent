"""ingest node: record the visitor's message, reset per-turn fields, update the topic."""
 
import re

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
 
 
def find_projects(query: str, aliases: dict[str, str]) -> set[str]:
    """Project ids whose spoken name appears in the query (whole words only)."""
    q = query.lower()
    found = set()
    for alias, project_id in aliases.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q):
            found.add(project_id)
    return found

def heard_history(history: list[AnyMessage], interrupted_reply: str) -> list[AnyMessage]:
    """Messages that record only what the visitor heard of a cut-off answer, ahead of the new message.

    If the full answer was already saved (the cut came while it was still being spoken), it is
    removed first, so the history never holds both versions. Returns [] when nothing was cut off.
    Shared by every graph whose turns can be interrupted.
    """
    heard = interrupted_reply.strip()
    if not heard:
        return []
    updates: list[AnyMessage] = []
    if history and isinstance(history[-1], AIMessage):
        updates.append(RemoveMessage(id=history[-1].id))
    updates.append(AIMessage(heard))
    return updates


def create_ingest_node(aliases: dict[str, str]):
    async def ingest_node(state: dict) -> dict:
        query = (state.get("query") or "").strip()
        messages = heard_history(state.get("messages") or [], state.get("interrupted_reply") or "")
        click = state.get("ui_action")
        # a click is recorded by its action only, so the form's name and email never enter the history.
        # They are in ui_action for this one turn; observability/redact.py masks them in traces.
        messages.append(HumanMessage(f"(The visitor clicked {click.get('action')} on the booking card.)" if click else query))
        update: dict = {
            "query": query,
            "messages": messages,
            "interrupted_reply": "",  # one-shot input: must not be added again next turn
            "retrieved": {},
            "retrieval_status": "skipped",
            "final_text": "",
            "errors": [],
            "stage_ms": {},
            "tool_steps": 0,
            "tool_calls": [],
            "pending_tool_calls": [],
            "cards": [],
            "booking_execute": None,
        }
        mentioned = find_projects(query, aliases)
        if len(mentioned) == 1:
            update["topic"] = next(iter(mentioned))  # a project was named: switch to it
        elif len(mentioned) > 1:
            update["topic"] = None  # a comparison: do not restrict retrieval
        # nothing named: keep the previous topic (follow-up questions)
        return update
 
    return ingest_node