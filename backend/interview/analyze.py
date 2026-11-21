"""analyze.py: the one LLM call that reads a resume and job description, and the code that checks it.

The model returns JSON (v2 design, "Analysis output"); pydantic validates it, and code then keeps only
the claims it can find in the resume (W1). Plan assembly is in interview/plan.py.

Rules a reader would not guess (the model proposes, code decides):
- Every claim carries source_quote, a span copied from the resume. A claim whose quote is not in the
  resume text (compared as lower-case words, so punctuation and line breaks do not matter) is dropped.
- A project or role left with no verified claim is dropped too: there is nothing grounded to ask.
- Invalid JSON or a failed call gets one more try; then None, and the caller uses the fallback plan.
- Resume and JD text are wrapped in tags; the system prompt says they are data, never instructions.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "analyzer.md"
MAX_ATTEMPTS = 2
ANALYSIS_MAX_TOKENS = 4096
MIN_QUOTE_WORDS = 2


class Claim(BaseModel):
    text: str
    source_quote: str


class Item(Claim):
    """An achievement or open-source contribution, with an id topics refer to."""

    id: str


class Project(BaseModel):
    id: str
    name: str
    one_line: str = ""
    tech: list[str] = []
    claims: list[Claim] = []


class Experience(BaseModel):
    id: str
    role: str
    organization: str
    claims: list[Claim] = []


class JdRequirements(BaseModel):
    technical: list[str] = []
    seniority: str = ""


class Gap(BaseModel):
    requirement: str
    resume_evidence: str = ""


class Framework(BaseModel):
    key_points: list[str] = []
    star: str = ""
    likely_followups: list[str] = []


class PlannedTopic(BaseModel):
    kind: Literal["deep_dive", "technical", "behavioral", "achievement"]  # behavioral is ignored: it comes from the bank
    ref: str  # a project, experience, achievement or oss id; a requirement name for technical
    source: Literal["resume", "jd", "gap"] = "resume"
    seed_question: str
    framework: Framework = Framework()


class Analysis(BaseModel):
    profile_summary: str
    projects: list[Project] = []
    experience: list[Experience] = []
    skills: list[str] = []
    achievements: list[Item] = []
    oss_contributions: list[Item] = []
    jd_requirements: JdRequirements = JdRequirements()
    gaps: list[Gap] = []
    topics: list[PlannedTopic] = []


@lru_cache(maxsize=1)
def load_analyzer_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_analysis_message(resume: str, job_description: str) -> str:
    jd = job_description or "(none given: plan from the resume alone)"
    return f"<resume>\n{resume}\n</resume>\n\n<job_description>\n{jd}\n</job_description>"


def parse_analysis(text: str) -> Analysis | None:
    """The model's JSON as an Analysis, or None if it is not valid."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return Analysis.model_validate(json.loads(text[start:end + 1]))
    except (ValueError, ValidationError):  # json.JSONDecodeError is a ValueError
        return None


def plain_words(text: str) -> str:
    return " ".join(re.sub(r"[^\w']+", " ", text.lower()).split())


def in_resume(quote: str, resume_words: str) -> bool:
    words = plain_words(quote)
    return len(words.split()) >= MIN_QUOTE_WORDS and f" {words} " in f" {resume_words} "


def verify(analysis: Analysis, resume: str) -> Analysis:
    """The analysis with every claim not found in the resume removed, and emptied projects and roles."""
    words = plain_words(resume)
    def kept(claims):
        return [claim for claim in claims if in_resume(claim.source_quote, words)]
    projects = [p.model_copy(update={"claims": kept(p.claims)}) for p in analysis.projects]
    experience = [e.model_copy(update={"claims": kept(e.claims)}) for e in analysis.experience]
    return analysis.model_copy(update={
        "projects": [p for p in projects if p.claims],
        "experience": [e for e in experience if e.claims],
        "achievements": kept(analysis.achievements),
        "oss_contributions": kept(analysis.oss_contributions),
    })


async def collect_text(pieces: AsyncIterator) -> str:
    """The model's text; its LlmUsage piece is not part of the JSON."""
    return "".join([piece async for piece in pieces if isinstance(piece, str)])


async def analyze(resume: str, job_description: str, generate_fn: Callable) -> Analysis | None:
    """generate_fn(prompt, system_instruction) -> async iterator of text pieces (rag/llm.py stream_text,
    given ANALYSIS_MAX_TOKENS). The verified analysis, or None after MAX_ATTEMPTS bad tries."""
    message = build_analysis_message(resume, job_description)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = await collect_text(generate_fn(message, load_analyzer_prompt()))
        except Exception as err:  # noqa: BLE001 - a failed call is retried like a bad reply; CancelledError passes
            print(f"[analysis] attempt {attempt}: {type(err).__name__}")
            continue
        parsed = parse_analysis(text)
        if parsed is not None:
            return verify(parsed, resume)
        print(f"[analysis] attempt {attempt}: the reply was not valid JSON for the schema")
    return None
