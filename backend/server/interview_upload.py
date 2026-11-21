"""interview_upload.py: POST /interview/upload, the resume (and optional job description) an interview
is planned from. One analysis LLM call; the plan is kept in memory under the session id until the
WebSocket session ends (server/connection.py sends it into the interview graph with every turn).

Body (JSON, so no multipart dependency): session_id, resume_pdf (base64), job_description (optional).
Returns the one-line plan preview the page shows before Start (v2 design, "User flow" step 4).

Rules a reader would not guess:
- Input checks run before any LLM call: a bad PDF or a scan costs nothing (resume.py).
- When the analysis fails twice the session still gets an interview: the fallback plan.
- Neither the resume text nor the plan is logged.
- It is public and calls a paid model: each address gets UPLOADS_PER_WINDOW uploads per UPLOAD_WINDOW_SECONDS,
  checked before the PDF is read, and at most MAX_KEPT_PLANS plans are kept (the oldest go first).
- Only page origins listed in CORS_ORIGINS may call it from another origin (allow_page_origins).
"""

from __future__ import annotations

import base64
import binascii
import time

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.interview.analyze import analyze
from backend.interview.assemble import assemble_plan, fallback_plan
from backend.interview.plan import plan_preview
from backend.interview.resume import ResumeError, clean_job_description, clean_resume

MAX_PDF_BASE64_CHARS = 7_000_000  # about 5 MB of PDF
MAX_JD_INPUT_CHARS = 50_000  # cut to resume.MAX_JD_CHARS after the checks
UPLOADS_PER_WINDOW = 5
UPLOAD_WINDOW_SECONDS = 600
MAX_KEPT_PLANS = 200  # plans whose page never opened its WebSocket would otherwise stay forever

router = APIRouter(prefix="/interview")


class UploadRequest(BaseModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")  # the id the WebSocket gave the page
    resume_pdf: str = Field(min_length=1, max_length=MAX_PDF_BASE64_CHARS)
    job_description: str = Field(default="", max_length=MAX_JD_INPUT_CHARS)


def decode_pdf(resume_pdf: str) -> bytes:
    try:
        return base64.b64decode(resume_pdf, validate=True)
    except (binascii.Error, ValueError) as err:
        raise HTTPException(422, {"code": "not_base64", "message": "The resume upload was damaged. Try again."}) from err


def allow_upload(history: dict[str, list[float]], client: str, now: float) -> bool:
    """Record an upload from client at now; False when it already made UPLOADS_PER_WINDOW in the window.
    Addresses with no upload in the window are forgotten, so history stays small."""
    cutoff = now - UPLOAD_WINDOW_SECONDS
    for stale in [address for address, times in history.items() if times[-1] <= cutoff]:
        del history[stale]
    recent = [t for t in history.get(client, []) if t > cutoff]
    if len(recent) >= UPLOADS_PER_WINDOW:
        return False
    history[client] = [*recent, now]
    return True


def keep_plan(plans: dict, session_id: str, plan: dict) -> None:
    """Keep the session's plan; when full, the oldest goes first (its page most likely never connected)."""
    plans.pop(session_id, None)
    while len(plans) >= MAX_KEPT_PLANS:
        plans.pop(next(iter(plans)))
    plans[session_id] = plan


def allow_page_origins(app: FastAPI, origins: list[str]) -> None:
    """Let a page served from these origins call the upload (web VITE_API_URL). None by default: browsers then
    refuse every cross-origin call, which is right while the page reaches the API through its own origin."""
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["POST"], allow_headers=["content-type"])


@router.post("/upload")
async def upload(body: UploadRequest, request: Request) -> dict:
    # shortcut: the limit is per server process and keyed on the connecting address; behind a reverse proxy every
    # visitor shares the proxy's address, so run uvicorn with --proxy-headers there
    client = request.client.host if request.client else "unknown"
    if not allow_upload(request.app.state.upload_history, client, time.monotonic()):
        raise HTTPException(429, {"code": "too_many_uploads", "message": "Too many uploads. Wait a few minutes and try again."})
    try:
        resume = clean_resume(decode_pdf(body.resume_pdf))
    except ResumeError as err:
        raise HTTPException(422, {"code": err.code, "message": str(err)}) from err
    analysis = await analyze(resume, clean_job_description(body.job_description), request.app.state.analyzer)
    plan = assemble_plan(analysis) if analysis is not None else fallback_plan(resume)
    keep_plan(request.app.state.interview_plans, body.session_id, plan)
    return {"preview": plan_preview(plan["topics"]), "topics": [t["title"] for t in plan["topics"]],
            "fallback": analysis is None}
