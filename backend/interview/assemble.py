"""assemble.py: a verified analysis (interview/analyze.py) -> this session's interview plan. No LLM.

One topic per stage, in stage order. For each stage the analysis's own topic is used when code can
ground it; otherwise a default from the analysis (the first verified role, the first gap); otherwise
the stage is left out. (v2 design, "Analysis call", step 6, and "Stage rules".)

Rules a reader would not guess:
- A topic's text holds only verified claims and the JD requirement: it is all the interviewer may
  rely on. A deep-dive or achievement topic whose ref has no verified material is not used.
- The model's seed question is spoken by code, so it must be one short question or one "Tell me
  about..." prompt; otherwise a fixed template is spoken instead, and the model's framework (written
  for its own question) is dropped with it.
- A technical topic's notes are the verified claims that name it, so follow-ups stay on the
  candidate's own work; only when no claim names it do the notes fall back to the skills list.
- Behavioral always has material: with no soft skills in the JD it uses generic SDE ones (W7).
- If the analysis failed twice, fallback_plan asks about the resume as a whole: intro, one deep-dive
  grounded in the resume text, and a behavioral question.
"""

from __future__ import annotations

import re

from backend.interview.analyze import Analysis, PlannedTopic
from backend.interview.plan import InterviewPlan, Topic, intro_topic, make_topic, order_plan

MAX_SEED_CHARS = 200
MAX_SUMMARY_CHARS = 1500
GENERIC_SOFT_SKILLS = ["ownership", "working through a disagreement", "learning from a failure"]
TEMPLATE_SEEDS = {
    "deep_dive": "Tell me about {title}. What did you build, and what was your part?",
    "technical": "How would you explain {title}, and where have you used it?",
    "behavioral": "Tell me about a time you disagreed with a teammate. What happened?",
    "achievement": "Tell me about {title}. What exactly did you do?",
}
FALLBACK_SEED = "Pick the project or role on your resume you're proudest of. What did you build?"
PROMPT_OPENERS = ("tell me", "describe", "walk me", "explain", "talk me", "give me")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "topic"


def is_spoken_question(seed: str) -> bool:
    """One short question, or one "Tell me about..." style prompt: nothing else is spoken by code."""
    if len(seed) > MAX_SEED_CHARS or "\n" in seed:
        return False
    if seed.endswith("?"):
        return True
    one_sentence = seed.endswith(".") and not re.search(r"[.?!]\s", seed)
    return one_sentence and seed.lower().startswith(PROMPT_OPENERS)


def claim_lines(claims: list) -> list[str]:
    return [f"- {claim.text}" for claim in claims]


def claims_about(analysis: Analysis, term: str) -> list[str]:
    """Every verified claim that names term, so a technical topic is grounded in the candidate's own work."""
    term = term.lower()
    claims = [c for p in analysis.projects for c in p.claims] + [c for e in analysis.experience for c in e.claims]
    named = [f"- {c.text}" for c in claims if term in c.text.lower() or term in c.source_quote.lower()]
    projects = [f"- {p.name} ({p.one_line}) is built with it" for p in analysis.projects
                if term in (tech.lower() for tech in p.tech)]
    return projects + named


def deep_dive_material(analysis: Analysis, ref: str) -> tuple[str, str] | None:
    for project in analysis.projects:
        if project.id == ref:
            lines = [f"{project.name}: {project.one_line}", f"Tech: {', '.join(project.tech)}"]
            return project.name, "\n".join(lines + claim_lines(project.claims))
    for role in analysis.experience:
        if role.id == ref:
            text = "\n".join([f"{role.role} at {role.organization}"] + claim_lines(role.claims))
            return f"your work at {role.organization}", text
    return None


def technical_material(analysis: Analysis, ref: str) -> tuple[str, str]:
    lines = [f"Topic: {ref}"]
    if ref in analysis.jd_requirements.technical:
        lines.append(f"The job description asks for {ref}.")
    lines += [f"Resume evidence: {gap.resume_evidence or 'none'}" for gap in analysis.gaps if gap.requirement == ref]
    used = claims_about(analysis, ref)
    lines += ["Where the resume uses it:", *used] if used else [f"Skills on the resume: {', '.join(analysis.skills)}"]
    return ref, "\n".join(lines)


def behavioral_material(analysis: Analysis) -> tuple[str, str]:
    skills = analysis.jd_requirements.soft_skills or GENERIC_SOFT_SKILLS
    work = [p.name for p in analysis.projects] + [f"{e.role} at {e.organization}" for e in analysis.experience]
    lines = [f"Soft skills to ask about: {', '.join(skills)}"]
    if work:
        lines.append(f"Ask in the context of the candidate's own work: {', '.join(work)}")
    return "how you work with others", "\n".join(lines)


def achievement_material(analysis: Analysis, ref: str) -> tuple[str, str] | None:
    for item in analysis.oss_contributions:
        if item.id == ref:
            return "your open-source contribution", item.text
    for item in analysis.achievements:
        if item.id == ref:
            return "your achievement", item.text
    return None


def material(analysis: Analysis, kind: str, ref: str) -> tuple[str, str] | None:
    """(title, text) for a topic of this kind about ref, or None when code cannot ground it."""
    if kind == "deep_dive":
        return deep_dive_material(analysis, ref)
    if kind == "technical":
        return technical_material(analysis, ref) if ref.strip() else None
    if kind == "behavioral":
        return behavioral_material(analysis)
    return achievement_material(analysis, ref)


def default_topic(analysis: Analysis, kind: str) -> PlannedTopic | None:
    """The stage's topic when the analysis planned none code could use."""
    gaps, required = [g.requirement for g in analysis.gaps], analysis.jd_requirements.technical
    refs = {
        "deep_dive": [e.id for e in analysis.experience] + [p.id for p in analysis.projects],
        "technical": gaps + required + analysis.skills,
        "behavioral": ["teamwork"],
        "achievement": [i.id for i in analysis.oss_contributions] + [i.id for i in analysis.achievements],
    }[kind]
    if not refs:
        return None
    source = "resume"
    if refs[0] in gaps:
        source = "gap"
    elif refs[0] in required or (kind == "behavioral" and analysis.jd_requirements.soft_skills):
        source = "jd"
    return PlannedTopic(kind=kind, ref=refs[0], source=source, seed_question="")


def stage_topic(analysis: Analysis, kind: str) -> Topic | None:
    planned = [t for t in analysis.topics if t.kind == kind and material(analysis, kind, t.ref)]
    chosen = planned[0] if planned else default_topic(analysis, kind)
    if chosen is None:
        return None
    title, text = material(analysis, kind, chosen.ref)
    source = chosen.source if kind in ("technical", "behavioral") else "resume"
    seed = chosen.seed_question.strip()
    if not is_spoken_question(seed):  # the model's framework was written for its own question: drop both
        return make_topic(kind, slug(chosen.ref), title, text, TEMPLATE_SEEDS[kind].format(title=title), source=source)
    return make_topic(kind, slug(chosen.ref), title, text, seed, source=source, framework=chosen.framework.model_dump())


def assemble_plan(analysis: Analysis) -> InterviewPlan:
    topics = [intro_topic()]
    for kind in ("deep_dive", "technical", "behavioral", "achievement"):
        topic = stage_topic(analysis, kind)
        if topic is not None:
            topics.append(topic)
    project_tech = [tech for project in analysis.projects for tech in project.tech]
    glossary = list(dict.fromkeys(analysis.skills + project_tech + analysis.jd_requirements.technical))
    return InterviewPlan(topics=order_plan(topics), profile_summary=analysis.profile_summary[:MAX_SUMMARY_CHARS],
                         glossary=glossary)


def fallback_plan(resume: str) -> InterviewPlan:
    """The plan when the analysis failed: questions grounded in the resume text itself."""
    deep_dive = make_topic("deep_dive", "resume", "your resume", resume, FALLBACK_SEED)
    behavioral = make_topic("behavioral", "teamwork", "how you work with others",
                            f"Soft skills to ask about: {', '.join(GENERIC_SOFT_SKILLS)}", TEMPLATE_SEEDS["behavioral"])
    return InterviewPlan(topics=[intro_topic(), deep_dive, behavioral], profile_summary="", glossary=[])
