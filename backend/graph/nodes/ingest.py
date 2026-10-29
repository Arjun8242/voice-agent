"""ingest node: record the visitor's message, reset per-turn fields, update the topic."""
 
import re
 
 
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
        update: dict = {
            "query": query,
            "messages": [{"role": "user", "text": query}],
            "retrieved": {},
            "retrieval_status": "skipped",
            "final_text": "",
            "errors": [],
            "stage_ms": {},
        }
        mentioned = find_projects(query, aliases)
        if len(mentioned) == 1:
            update["topic"] = next(iter(mentioned))  # a project was named: switch to it
        elif len(mentioned) > 1:
            update["topic"] = None  # a comparison: do not restrict retrieval
        # nothing named: keep the previous topic (follow-up questions)
        return update
 
    return ingest_node