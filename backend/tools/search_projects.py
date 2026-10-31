"""searchProjects: find projects by free-text query and/or tech filter.

Source: projects.yaml (loaded at startup, passed in via the registry).
"""

from __future__ import annotations

from .schemas import ProjectSummary, SearchProjectsArgs, SearchProjectsResult


def search_projects(
    args: SearchProjectsArgs,
    *,
    projects: list[dict],
) -> SearchProjectsResult:
    """Return projects matching the query and/or tech filter."""
    matches = list(projects)

    if args.tech:
        tech_lower = args.tech.lower()
        matches = [
            p
            for p in matches
            if any(t.lower() == tech_lower for t in p.get("tech", []))
        ]

    if args.query:
        q = args.query.lower()
        matches = [
            p
            for p in matches
            if q in p.get("name", "").lower()
            or q in p.get("one_line", "").lower()
        ]

    return SearchProjectsResult(
        projects=[
            ProjectSummary(
                id=p["id"],
                name=p["name"],
                one_line=p["one_line"],
                status=p["status"],
            )
            for p in matches
        ]
    )

