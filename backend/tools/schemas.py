"""Pydantic schemas for tool arguments and results.

Each tool has an Args model (validated before execution) and a Result model
(returned to the agent node). Structured errors use ToolError.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


# ── Structured error returned to the model instead of an exception ──────────


class ToolError(BaseModel):
    error: str
    tool: str
    details: str | None = None


# ── searchProjects ──────────────────────────────────────────────────────────


class SearchProjectsArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Free-text search term (matched against name and one_line).",
    )
    tech: str | None = Field(
        default=None,
        description="Technology name to filter by (e.g. 'Redis', 'React').",
    )


class ProjectSummary(BaseModel):
    id: str
    name: str
    one_line: str
    status: str


class SearchProjectsResult(BaseModel):
    projects: list[ProjectSummary]


# ── getProjectDetail ────────────────────────────────────────────────────────


class GetProjectDetailArgs(BaseModel):
    project_id: str = Field(description="Project id (e.g. 'beacon').")
    section: str = Field(
        description="Section heading (e.g. 'Architecture', 'Overview').",
    )


class ProjectDetailResult(BaseModel):
    project_id: str
    project_name: str
    section: str
    content: str
    available_sections: list[str]


# ── getSkills ───────────────────────────────────────────────────────────────


class GetSkillsArgs(BaseModel):
    skill: str | None = Field(
        default=None,
        description="Skill name to look up (e.g. 'Redis', 'Python'). "
        "Omit to list all skills.",
    )


class SkillInfo(BaseModel):
    skill: str
    category: str
    evidence: list[str]


class GetSkillsResult(BaseModel):
    found: bool = True
    skills: list[SkillInfo]
    message: str | None = None


# ── getLinks ────────────────────────────────────────────────────────────────


class GetLinksArgs(BaseModel):
    type: str = Field(
        description="Link type: portfolio, resume, github_profile, "
        "professional_profile, or coding_profile.",
    )


class LinkInfo(BaseModel):
    id: str
    label: str
    type: str
    url: str
    description: str


class GetLinksResult(BaseModel):
    found: bool = True
    links: list[LinkInfo]
    available_types: list[str]
    message: str | None = None


# ── Card payloads ───────────────────────────────────────────────────────────


class Card(BaseModel):
    """A card for the UI (S10 will render these; for now they travel in state)."""

    card_type: str  # "project_detail" | "link"
    data: dict[str, Any]

