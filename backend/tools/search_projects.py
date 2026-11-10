"""searchProjects: list projects, filtered by free text and/or a technology."""

from .kb_data import KbData
from .match import has_word
from .schemas import SearchProjectsArgs


def search_projects(args: SearchProjectsArgs, kb: KbData) -> tuple[dict, list[dict]]:
    found = []
    for p in kb.projects:
        if args.tech and not any(has_word(args.tech, t) for t in p.tech):
            continue
        if args.query and not any(has_word(args.query, text) for text in (p.id, p.name, p.one_line, *p.tech)):
            continue
        found.append({"id": p.id, "name": p.name, "one_line": p.one_line, "status": p.status})
    return {"projects": found}, []
