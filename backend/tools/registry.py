"""Tool registry: validation, dispatch, timeouts, structured errors.

The registry is built at startup with the KB data injected. Each tool is
registered with its name, Args model, handler function, and optional
post-handler for card generation.

Design rules:
- Unknown tool names → ToolError (never an exception).
- Invalid args → ToolError with pydantic details.
- Handler timeout → ToolError.
- Booking tools (checkAvailability, startBooking) are NOT registered; the model
  cannot call them.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .schemas import Card, GetLinksArgs, GetProjectDetailArgs, GetSkillsArgs, SearchProjectsArgs, ToolError
from .search_projects import search_projects
from .project_detail import get_project_detail, make_card as project_card
from .skills import get_skills
from .links import get_links, make_card as link_card


DEFAULT_TIMEOUT = 2.0  # seconds; read-only tools should be instant


@dataclass
class RegisteredTool:
    name: str
    args_model: type[BaseModel]
    handler: Callable[..., Any]
    card_fn: Callable[..., Card | list[Card] | None] | None = None
    timeout: float = DEFAULT_TIMEOUT


@dataclass
class ToolCallResult:
    tool: str
    result: dict
    cards: list[Card] = field(default_factory=list)
    duration_ms: float = 0.0
    is_error: bool = False


class ToolRegistry:
    """Holds the registered tools and executes validated calls."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.name] = tool

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools

    def validate_args(self, name: str, raw_args: dict) -> BaseModel | ToolError:
        """Parse and validate arguments. Returns the model or a ToolError."""
        if name not in self._tools:
            return ToolError(
                error="unknown_tool",
                tool=name,
                details=f"Tool '{name}' is not registered. Available: {', '.join(self.names)}.",
            )

        tool = self._tools[name]
        try:
            return tool.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return ToolError(
                error="invalid_args",
                tool=name,
                details=str(exc),
            )

    async def execute(self, name: str, raw_args: dict) -> ToolCallResult:
        """Validate, run with timeout, and return a structured result."""
        start = time.perf_counter()

        # Validate
        validated = self.validate_args(name, raw_args)
        if isinstance(validated, ToolError):
            return ToolCallResult(
                tool=name,
                result=validated.model_dump(),
                is_error=True,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )

        tool = self._tools[name]

        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(tool.handler, validated),
                timeout=tool.timeout,
            )
        except asyncio.TimeoutError:
            err = ToolError(
                error="timeout",
                tool=name,
                details=f"Tool '{name}' exceeded {tool.timeout}s timeout.",
            )
            return ToolCallResult(
                tool=name,
                result=err.model_dump(),
                is_error=True,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
        except Exception as exc:
            err = ToolError(
                error="execution_error",
                tool=name,
                details=str(exc),
            )
            return ToolCallResult(
                tool=name,
                result=err.model_dump(),
                is_error=True,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )

        # Handle ToolError returned by the handler itself
        if isinstance(result, ToolError):
            return ToolCallResult(
                tool=name,
                result=result.model_dump(),
                is_error=True,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )

        # Build cards if applicable
        cards: list[Card] = []
        if tool.card_fn is not None:
            try:
                card_result = tool.card_fn(result)
                if card_result is not None:
                    if isinstance(card_result, list):
                        cards.extend(card_result)
                    else:
                        cards.append(card_result)
            except Exception:
                pass  # Card generation failure is non-fatal

        result_dict = result.model_dump() if isinstance(result, BaseModel) else result

        return ToolCallResult(
            tool=name,
            result=result_dict,
            cards=cards,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )


def _project_detail_card_fn(result: Any) -> Card | None:
    """Only produce a card for successful project detail lookups."""
    from .schemas import ToolError as TE
    if isinstance(result, TE):
        return None
    return project_card(result)


def _link_cards_fn(result: Any) -> list[Card] | None:
    """Produce a card for each returned link."""
    from .schemas import ToolError as TE
    if isinstance(result, TE) or not result.found:
        return None
    return [link_card(li) for li in result.links]


def build_registry(
    *,
    projects: list[dict],
    skills: list[dict],
    links: list[dict],
    chunks: list[dict],
    project_names: dict[str, str],
) -> ToolRegistry:
    """Build the tool registry with KB data bound into each handler."""
    registry = ToolRegistry()

    registry.register(
        RegisteredTool(
            name="searchProjects",
            args_model=SearchProjectsArgs,
            handler=partial(search_projects, projects=projects),
        )
    )

    registry.register(
        RegisteredTool(
            name="getProjectDetail",
            args_model=GetProjectDetailArgs,
            handler=partial(
                get_project_detail, projects=projects, chunks=chunks
            ),
            card_fn=_project_detail_card_fn,
        )
    )

    registry.register(
        RegisteredTool(
            name="getSkills",
            args_model=GetSkillsArgs,
            handler=partial(
                get_skills, skills=skills, project_names=project_names
            ),
        )
    )

    registry.register(
        RegisteredTool(
            name="getLinks",
            args_model=GetLinksArgs,
            handler=partial(get_links, links=links),
            card_fn=_link_cards_fn,
        )
    )

    return registry

