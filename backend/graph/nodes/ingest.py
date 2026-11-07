"""ingest node: record the visitor's message, reset per-turn fields, update the topic."""
 
import re

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
 
 
def find_projects(query: str, aliases: dict[str, str]) -> set[str]:
    """Project ids whose spoken name appears in the query (whole words only)."""
    q = query.lower()
    found = set()
    for alias, project_id in aliases.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q):
            found.add(project_id)
    return found

def create_ingest_node(aliases: dict[str, str]):
    async def ingest_node(state: dict) -> dict:
        query = (state.get("query") or "").strip()
        messages = []
        heard = (state.get("interrupted_reply") or "").strip()
        if heard:  # the visitor cut the last answer off: keep only what they heard, ahead of the new question
            history = state.get("messages") or []
            if history and isinstance(history[-1], AIMessage):
                # the full answer was already saved (the cut came while it was still being spoken): replace it
                messages.append(RemoveMessage(id=history[-1].id))
            messages.append(AIMessage(heard))
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