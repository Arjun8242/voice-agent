"""interview_upload.py: POST /interview/upload, the resume (and optional job description) an interview
is planned from. One analysis LLM call; the plan is kept in memory under the session id until the
WebSocket session ends (server/connection.py sends it into the interview graph with every turn).

Body (JSON, so no multipart dependency): session_id, resume_pdf (base64), job_description (optional).
Returns the one-line plan preview the page shows before Start (v2 design, "User flow" step 4).

Rules a reader would not guess:
- Input checks run before any LLM call: a bad PDF or a scan costs nothing (resume.py).
- When the analysis fails twice the session still gets an interview: the fallback plan.
- Neither the resume text nor the plan is logged.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.interview.analyze import analyze
from backend.interview.assemble import assemble_plan, fallback_plan
from backend.interview.plan import plan_preview
from backend.interview.resume import ResumeError, clean_job_description, clean_resume

MAX_PDF_BASE64_CHARS = 7_000_000  # about 5 MB of PDF
MAX_JD_INPUT_CHARS = 50_000  # cut to resume.MAX_JD_CHARS after the checks

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


@router.post("/upload")
async def upload(body: UploadRequest, request: Request) -> dict:
    try:
        resume = clean_resume(decode_pdf(body.resume_pdf))
    except ResumeError as err:
        raise HTTPException(422, {"code": err.code, "message": str(err)}) from err
    analysis = await analyze(resume, clean_job_description(body.job_description), request.app.state.analyzer)
    plan = assemble_plan(analysis) if analysis is not None else fallback_plan(resume)
    request.app.state.interview_plans[body.session_id] = plan
    return {"preview": plan_preview(plan["topics"]), "topics": [t["title"] for t in plan["topics"]],
            "fallback": analysis is None}
