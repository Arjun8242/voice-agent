"""api.py: POST /internal/turn, the same graph as the voice path without STT or TTS.
 
For evals and manual testing. Protected by the INTERNAL_API_KEY environment
variable (sent as the api-key header). If the variable is not set, the
endpoint is disabled. server/main.py includes this router.
"""

import asyncio
import os 
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
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
    session_id: str = Field(min_length = 1, max_length = 100)
    input: TurnInput


@router.post("/turn")
async def turn(body: TurnRequest, request: Request, API_KEY: str | None = Header(default= None)) -> dict:
    internal_api_key = os.environ.get("INTERNAL_API_KEY", "")

    if not internal_api_key:
        raise HTTPException(503, "internal endpoints are disabled (INTERNAL_API_KEY is not set)")

    if not API_KEY or not secrets.compare_digest(API_KEY.encode(), internal_api_key.encode()):
        raise HTTPException(401, "invalid api key")
    
    graph = getattr(request.app.state, "graph", None)

    if graph is None:
        raise HTTPException(503, "graph is not initialised")
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