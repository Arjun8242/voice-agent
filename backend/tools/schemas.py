"""Argument schemas for the read-only tools, and the structured tool error.

The registry validates the model's arguments against these models, and the
function declarations sent to Gemini are generated from them, so the schema the
model sees and the schema code enforces cannot drift apart. getLinks has no
model here: its allowed types come from links.yaml (see links.py).
"""

from pydantic import BaseModel, ConfigDict, Field


class ToolError(Exception):
    """Raised by a handler; the registry turns it into {"error": code, "details": ...}."""

    def __init__(self, code: str, details: str):
        super().__init__(details)
        self.code = code
        self.details = details


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an invented argument is an error, not ignored


class SearchProjectsArgs(Args):
    query: str | None = Field(default=None, description="Words to match against project names, summaries and technologies.")
    tech: str | None = Field(default=None, description="One technology name, for example 'Redis'.")


class GetProjectDetailArgs(Args):
    project_id: str = Field(description="Project id as returned by searchProjects.")
    section: str = Field(
        description="One of: Overview, Architecture, Key decisions, Limitations, Testing; or an exact section heading."
    )


class GetSkillsArgs(Args):
    skill: str | None = Field(
        default=None,
        description="The skill or technology the visitor named. Omit only when the visitor asks for all skills.",
    )
