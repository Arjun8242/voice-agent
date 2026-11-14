"""api.py: POST /internal/turn, the same graph as the voice path without STT or TTS.
 
For evals and manual testing. mode "recruiter" (default) runs the recruiter graph; mode "interview"
runs the interview graph, so the interviewer can be developed in text with no Sarvam spend. An
interview request without an answer asks for the opening question. Protected by the INTERNAL_API_KEY environment
variable (sent as the api-key header). If the variable is not set, the
endpoint is disabled. server/main.py includes this router.
"""

import asyncio
import os 
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from .runner import run_turn


TURN_TIMEOUT = 30

router = APIRouter(prefix="/internal")

class UiAction(BaseModel):
    action: str = Field(min_length = 1, max_length = 40)
    payload: dict = {}


class TurnInput(BaseModel):
    """Speech text, or a click on a booking card: exactly one."""
    text: str | None = Field(default = None, min_length = 1, max_length = 200)
    ui_action: UiAction | None = None

    @model_validator(mode = "after")
    def one_kind(self):
        if (self.text is None) == (self.ui_action is None):
            raise ValueError("give exactly one of text or ui_action")
        return self


class TurnRequest(BaseModel):
    """Recruiter mode needs input. Interview mode takes answer instead (none = the opening question)."""
    session_id: str = Field(min_length = 1, max_length = 100)
    mode: Literal["recruiter", "interview"] = "recruiter"
    input: TurnInput | None = None
    answer: str | None = Field(default = None, max_length = 2000)  # spoken answers run longer than questions
    persona: str = Field(default = "", max_length = 20)  # interview only; unknown names get neutral

    @model_validator(mode = "after")
    def fits_mode(self):
        if self.mode == "recruiter" and (self.input is None or self.answer is not None):
            raise ValueError("recruiter mode takes input, not answer")
        if self.mode == "interview" and self.input is not None:
            raise ValueError("interview mode takes answer, not input")
        return self


# What an interview turn returns besides the reply: enough to check the flow without reading the graph.
INTERVIEW_FIELDS = ("intent", "mode", "decision", "tag_ok", "topic_index", "level", "followups_used", "finished", "answers")


async def run_interview_turn(graph, body: TurnRequest) -> dict:
    result = await run_turn(graph, session_id=body.session_id, text=body.answer or "", persona=body.persona)
    state = (await graph.aget_state({"configurable": {"thread_id": body.session_id}})).values
    timings = {key: result[key] for key in ("errors", "first_token_ms", "total_ms", "usage")}
    return {"reply": result["reply"], **timings, **{key: state.get(key) for key in INTERVIEW_FIELDS}}


@router.post("/turn")
async def turn(body: TurnRequest, request: Request, API_KEY: str | None = Header(default= None)) -> dict:
    internal_api_key = os.environ.get("INTERNAL_API_KEY", "")

    if not internal_api_key:
        raise HTTPException(503, "internal endpoints are disabled (INTERNAL_API_KEY is not set)")

    if not API_KEY or not secrets.compare_digest(API_KEY.encode(), internal_api_key.encode()):
        raise HTTPException(401, "invalid api key")
    
    graph = getattr(request.app.state, "interview_graph" if body.mode == "interview" else "graph", None)

    if graph is None:
        raise HTTPException(503, "graph is not initialised")
    if body.mode == "interview":
        try:
            return await asyncio.wait_for(run_interview_turn(graph, body), TURN_TIMEOUT)
        except asyncio.TimeoutError:
            raise HTTPException(504, f"turn exceeded {TURN_TIMEOUT}s")
    try:
        click = body.input.ui_action.model_dump() if body.input.ui_action else None
        result = await asyncio.wait_for(run_turn(graph, session_id=body.session_id, text=body.input.text or "", ui_action=click), TURN_TIMEOUT)
        executor = getattr(request.app.state, "executor", None)
        if result["booking_execute"] and executor is not None:  # no voice here: run the calendar call inline, so evals see the outcome
            handoff = result["booking_execute"]
            result["booking_update"] = await asyncio.wait_for(executor.run(handoff["booking_id"], handoff["kind"]), TURN_TIMEOUT)
        return result

    except asyncio.TimeoutError:
        raise HTTPException(504, f"turn exceeded {TURN_TIMEOUT}s")