"""getProjectDetail: return a specific section from a project's index chunks.

Source: the loaded KB index chunks (filtered by project_id and section heading).
"""

from __future__ import annotations

from .schemas import Card, GetProjectDetailArgs, ProjectDetailResult, ToolError


def _normalize_section(s: str) -> str:
    return s.strip().lower()


def get_project_detail(
    args: GetProjectDetailArgs,
    *,
    projects: list[dict],
    chunks: list[dict],
) -> ProjectDetailResult | ToolError:
    """Return section text for a project, plus a card payload."""
    pid = args.project_id.lower()

    # Check project exists
    project = None
    for p in projects:
        if p["id"].lower() == pid:
            project = p
            break

    if project is None:
        known = [p["id"] for p in projects]
        return ToolError(
            error="unknown_project",
            tool="getProjectDetail",
            details=f"Project '{args.project_id}' not found. Known: {', '.join(known)}.",
        )

    # Find chunks for this project
    project_chunks = [
        c for c in chunks if (c.get("project_id") or "").lower() == pid
    ]

    # Build the set of available sections from chunk titles
    # Title format: "ProjectName > Section" or "ProjectName > Section > Sub"
    available: dict[str, str] = {}  # normalized -> original
    for c in project_chunks:
        title = c.get("title", "")
        parts = title.split(" > ", 1)
        if len(parts) > 1:
            sec = parts[1].strip()
            # Remove " (part N)" suffix for display
            clean = sec
            if " (part " in clean:
                clean = clean[: clean.index(" (part ")]
            available[_normalize_section(clean)] = clean

    section_norm = _normalize_section(args.section)
    available_list = sorted(set(available.values()))

    if section_norm not in available:
        return ToolError(
            error="unknown_section",
            tool="getProjectDetail",
            details=f"Section '{args.section}' not found for '{project['name']}'. "
            f"Available: {', '.join(available_list)}.",
        )

    # Collect content from matching chunks (may span multiple parts)
    section_content_parts = []
    for c in project_chunks:
        title = c.get("title", "")
        parts = title.split(" > ", 1)
        if len(parts) > 1:
            sec = parts[1].strip()
            clean = sec
            if " (part " in clean:
                clean = clean[: clean.index(" (part ")]
            if _normalize_section(clean) == section_norm:
                section_content_parts.append(c.get("content", ""))

    content = "\n\n".join(section_content_parts).strip()

    return ProjectDetailResult(
        project_id=project["id"],
        project_name=project["name"],
        section=available.get(section_norm, args.section),
        content=content,
        available_sections=available_list,
    )


def make_card(result: ProjectDetailResult) -> Card:
    """Build a card payload from a successful project detail result."""
    return Card(
        card_type="project_detail",
        data={
            "project_id": result.project_id,
            "project_name": result.project_name,
            "section": result.section,
            "content": result.content,
        },
    )

