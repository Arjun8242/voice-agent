"""Load the knowledge files the tools read, once at startup.

Reuses the S3 schemas (kb.validate) and the S4 heading splitter (kb.ingest), so
tools see exactly the data that ingest validated and indexed. A file that fails
its schema stops startup instead of leaving a tool with partial data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from kb.ingest import split_sections
    from kb.loaders import read_text, split_front_matter
    from kb.validate import Experience, Link, Project, Skill, parse_list
except (ImportError, ModuleNotFoundError):
    from backend.kb.ingest import split_sections
    from backend.kb.loaders import read_text, split_front_matter
    from backend.kb.validate import Experience, Link, Project, Skill, parse_list


@dataclass
class KbData:
    projects: list[Project]
    skills: list[Skill]
    links: list[Link]
    experience: list[Experience]
    sections: dict[str, dict[str, str]]  # project_id -> {level-2 heading: text}


def project_sections(markdown: str) -> dict[str, str]:
    """Level-2 heading -> its text, with any ### subsections folded in under their heading."""
    sections: dict[str, list[str]] = {}
    for path, text in split_sections(markdown):
        if not path:  # text before the first ## heading (the # title)
            continue
        parts = sections.setdefault(path[0], [])
        if len(path) > 1:
            parts.append(path[1])
        if text:
            parts.append(text)
    return {heading: "\n\n".join(parts) for heading, parts in sections.items()}


def load_kb_data(kdir: Path) -> KbData:
    errors: list[str] = []
    s = kdir / "structured"
    projects, _ = parse_list(s / "projects.yaml", Project, errors)
    skills, _ = parse_list(s / "skills.yaml", Skill, errors)
    links, _ = parse_list(s / "links.yaml", Link, errors)
    experience, _ = parse_list(s / "experience.yaml", Experience, errors)
    if errors:
        raise ValueError("knowledge files failed validation: " + "; ".join(errors))

    sections = {}
    for p in projects:
        _, body = split_front_matter(read_text(kdir / "docs" / "projects" / f"{p.id}.md"))
        sections[p.id] = project_sections(body)
    return KbData(projects, skills, links, experience, sections)
