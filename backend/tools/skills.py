"""getSkills: all skills, or one skill with its evidence, or an explicit 'not listed'.

A skill matches by its exact name, a whole word of it ('Gemini' -> 'Gemini AI
Integration'), or a spelling in ALIASES. When nothing matches, projects whose
tech list names the technology are still returned, so 'not a listed skill' is
not mistaken for 'never used it'.
"""

from .kb_data import KbData
from .match import has_word, norm
from .schemas import GetSkillsArgs

# spoken or short spellings that share no whole word with the skill name
ALIASES = {"postgres": "postgresql", "js": "javascript", "ts": "typescript", "react.js": "react", "reactjs": "react"}


def _evidence(ids: list[str], kb: KbData) -> list[dict]:
    projects = {p.id: p for p in kb.projects}
    experience = {e.id: e for e in kb.experience}
    out = []
    for i in ids:
        if i in projects:
            out.append({"id": i, "kind": "project", "name": projects[i].name, "status": projects[i].status})
        elif i in experience:
            out.append({"id": i, "kind": "experience", "name": experience[i].organization, "role": experience[i].role})
    return out


def get_skills(args: GetSkillsArgs, kb: KbData) -> tuple[dict, list[dict]]:
    if args.skill is None:
        return {"skills": [{"skill": s.skill, "category": s.category} for s in kb.skills]}, []

    wanted = ALIASES.get(norm(args.skill), norm(args.skill))
    matched = [s for s in kb.skills if norm(s.skill) == wanted] or [s for s in kb.skills if has_word(wanted, s.skill)]
    if matched:
        return {
            "found": True,
            "skills": [{"skill": s.skill, "category": s.category, "evidence": _evidence(s.evidence, kb)} for s in matched],
        }, []

    used_in = [{"id": p.id, "name": p.name, "status": p.status} for p in kb.projects if any(has_word(wanted, t) for t in p.tech)]
    return {"found": False, "skill": args.skill, "used_in_projects": used_in}, []
