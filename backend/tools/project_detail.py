"""getProjectDetail: one section of a project doc, plus a project_detail card.

The three docs do not use identical headings ('Limitations and Future Work' vs
'Scope and Limitations'), so the model may ask for a short section name and it
is mapped to whichever accepted heading that doc uses. The accepted headings are
the ones kb/validate.py already checks for, so they live in one place.
"""

from .kb_data import KbData
from .match import norm
from .schemas import GetProjectDetailArgs, ToolError

try:
    from kb.validate import RECOMMENDED_SECTIONS, REQUIRED_SECTIONS
except (ImportError, ModuleNotFoundError):
    from backend.kb.validate import RECOMMENDED_SECTIONS, REQUIRED_SECTIONS

# short name the model may use -> headings that count as that section
SECTION_NAMES = {
    "overview": REQUIRED_SECTIONS["Overview"],
    "architecture": REQUIRED_SECTIONS["Architecture"],
    "limitations": REQUIRED_SECTIONS["Limitations"],
    "key decisions": RECOMMENDED_SECTIONS["Key decisions"],
    "testing": RECOMMENDED_SECTIONS["Testing / status"],
}


def find_section(requested: str, sections: dict[str, str]) -> str | None:
    """The doc heading for a requested section: exact heading first, then a short name."""
    by_norm = {norm(h): h for h in sections}
    wanted = norm(requested)
    if wanted in by_norm:
        return by_norm[wanted]
    for accepted in SECTION_NAMES.get(wanted, []):
        if norm(accepted) in by_norm:
            return by_norm[norm(accepted)]
    return None


def get_project_detail(args: GetProjectDetailArgs, kb: KbData) -> tuple[dict, list[dict]]:
    project = next((p for p in kb.projects if p.id == norm(args.project_id)), None)
    if project is None:
        raise ToolError("unknown_project", f"No project '{args.project_id}'. Known ids: {', '.join(p.id for p in kb.projects)}.")

    sections = kb.sections[project.id]
    heading = find_section(args.section, sections)
    if heading is None:
        raise ToolError("unknown_section", f"{project.name} has no section '{args.section}'. Sections: {', '.join(sections)}.")

    links = project.links.model_dump()  # repo, live, video (null when absent)
    result = {
        "project_id": project.id,
        "name": project.name,
        "status": project.status,
        "section": heading,
        "text": sections[heading],
        "links": links,
    }
    card = {
        "card_id": f"project_detail:{project.id}:{heading}",
        "type": "project_detail",
        "data": {"project_id": project.id, "name": project.name, "status": project.status,
                 "section": heading, "text": sections[heading], "links": links},
    }
    return result, [card]
