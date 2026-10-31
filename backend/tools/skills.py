"""getSkills: list all skills, or look up a specific skill with evidence.

Source: skills.yaml (loaded at startup, passed in).
Name matching is case-insensitive with common alias support.
"""

from __future__ import annotations

from .schemas import GetSkillsArgs, GetSkillsResult, SkillInfo


# Common aliases: maps alternate name -> canonical skill name (lowercased)
_ALIASES: dict[str, str] = {
    "ts": "typescript",
    "js": "javascript",
    "node": "node.js",
    "express": "express.js",
    "pg": "postgresql",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "docker compose": "docker",
    "gemini": "gemini ai integration",
    "jwt auth": "jwt authentication",
    "rate limit": "rate limiting",
    "interpreter": "interpreter design",
    "react.js": "react",
    "reactjs": "react",
    "nextjs": "next.js",
    "bull": "bullmq",
}


def _normalize(name: str) -> str:
    return name.strip().lower()


def get_skills(
    args: GetSkillsArgs,
    *,
    skills: list[dict],
    project_names: dict[str, str],
) -> GetSkillsResult:
    """Return all skills, or the evidence for one skill, or explicit 'not found'."""

    if args.skill is None:
        # List all skills
        return GetSkillsResult(
            found=True,
            skills=[
                SkillInfo(
                    skill=s["skill"],
                    category=s["category"],
                    evidence=[project_names.get(e, e) for e in s["evidence"]],
                )
                for s in skills
            ],
        )

    # Look up a specific skill
    query = _normalize(args.skill)
    canonical = _ALIASES.get(query, query)

    for s in skills:
        if _normalize(s["skill"]) == canonical:
            return GetSkillsResult(
                found=True,
                skills=[
                    SkillInfo(
                        skill=s["skill"],
                        category=s["category"],
                        evidence=[
                            project_names.get(e, e) for e in s["evidence"]
                        ],
                    )
                ],
            )

    # Explicit not found
    return GetSkillsResult(
        found=False,
        skills=[],
        message=f"Arjun does not list '{args.skill}' among his skills.",
    )

