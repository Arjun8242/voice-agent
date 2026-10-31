"""api.py: POST /internal/turn, the same graph as the voice path without STT or TTS.
 
For evals and manual testing. Protected by the INTERNAL_API_KEY environment
variable (sent as the api-key header). If the variable is not set, the
endpoint is disabled. server/main.py includes this router.
"""

import asyncio
import os 
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from .runner import run_turn


TURN_TIMEOUT = 30

router = APIRouter(prefix="/internal")

class TurnInput(BaseModel):
    text: str = Field(min_length = 1, max_length = 200)


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
        return await asyncio.wait_for(run_turn(graph, session_id=body.session_id, text=body.input.text), TURN_TIMEOUT)

    except asyncio.TimeoutError:
        raise HTTPException(504, f"turn exceeded {TURN_TIMEOUT}s")