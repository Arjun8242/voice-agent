"""respond node: finalise the reply and record it in the conversation history."""
 
from .agent import ERROR_REPLY
 
 
async def respond_node(state: dict) -> dict:
    text = (state.get("final_text") or "").strip()
    errors = list(state.get("errors", []))
    if not text:  # the model returned nothing
        text = ERROR_REPLY
        errors.append("agent: empty reply")
    return {
        "final_text": text,
        "errors": errors,
        "messages": [{"role": "assistant", "text": text}],
    }
 