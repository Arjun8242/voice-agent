"""S3: validate the knowledge files before anything is indexed.

S4 (ingest) calls validate() first and stops if it returns errors.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .loaders import load_yaml, read_text, split_front_matter

# ---------------------------------------------------------------------------
# Rules you may want to edit
# ---------------------------------------------------------------------------

# shipped = built and deployed; runnable_not_deployed = built, runs locally only
Status = Literal["shipped", "runnable_not_deployed", "in_progress", "idea"]

# Project docs need these sections (error if missing). Each name lists accepted
# headings, because the three docs are not written with identical headings.
REQUIRED_SECTIONS = {
    "Overview": ["Overview"],
    "Architecture": ["Architecture"],
    "Limitations": [
        "Limitations and not yet done",
        "Limitations and Future Work",
        "Scope and Limitations",
    ],
}
# Missing these gives a warning only.
RECOMMENDED_SECTIONS = {
    "Key decisions": [
        "Key decisions",
        "Key Engineering Decisions",
        "Design Decisions and Trade-offs",
    ],
    "Testing / status": [
        "Status and what is tested",
        "Testing and Verification",
        "Test Coverage",
    ],
}
DOC_TYPES = {
    "bio.md": "candidate_bio",
    "faq.md": "candidate_faq",
    "boundaries.md": "candidate_boundaries",
}
WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

PLACEHOLDER = re.compile(
    r"<[A-Za-z][A-Za-z0-9 _/-]{0,40}>|\b(?:TODO|TBD|FIXME)\b|\bYOUR_[A-Z0-9_]+\b"
)
FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'd|my|me|mine)\b")
INSTRUCTION = re.compile(r"(?:^|[.;:]\s+)(do not|don't|never)\b", re.I)
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

# ---------------------------------------------------------------------------
# Schemas (extra="forbid" catches misspelled keys)
# ---------------------------------------------------------------------------


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectLinks(Strict):
    repo: NonEmpty
    live: str | None = None
    video: str | None = None


class ProjectMeasured(Strict):
    claim: NonEmpty
    how: NonEmpty


class Project(Strict):
    id: Slug
    name: NonEmpty
    one_line: NonEmpty
    status: Status
    featured: bool = False
    tech: list[NonEmpty] = Field(min_length=1)
    role: NonEmpty
    links: ProjectLinks
    assets: dict[str, str | None] = {}
    highlights: list[NonEmpty] = Field(min_length=1)
    measured: list[ProjectMeasured] = []
    updated: dt.date


class ExperienceMeasured(Strict):
    before_seconds: float
    after_seconds: float
    improvement_percent: float
    how: str | None = None


class ExperienceHighlight(Strict):
    id: Slug
    description: NonEmpty
    measured: ExperienceMeasured | None = None


class Experience(Strict):
    id: Slug
    organization: NonEmpty
    role: NonEmpty
    type: Literal["internship", "full_time", "part_time", "contract", "freelance"]
    start_date: YearMonth
    end_date: YearMonth | None = None
    current: bool
    location: NonEmpty
    tech: list[NonEmpty] = Field(min_length=1)
    one_line: NonEmpty
    highlights: list[ExperienceHighlight] = Field(min_length=1)
    updated: dt.date


class Skill(Strict):
    id: Slug
    skill: NonEmpty
    category: NonEmpty
    evidence: list[NonEmpty] = Field(min_length=1)


class Link(Strict):
    id: Slug
    label: NonEmpty
    type: NonEmpty
    url: NonEmpty
    description: NonEmpty


class Calendar(Strict):
    provider: NonEmpty
    calendar_id: NonEmpty
    timezone: NonEmpty


class MeetingType(Strict):
    id: Slug
    title: NonEmpty
    duration_minutes: int = Field(gt=0)
    description: NonEmpty


class Availability(Strict):
    working_days: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    booking_horizon_days: int = Field(gt=0)
    min_notice_hours: int | None = Field(default=None, ge=0)
    buffer_minutes: int | None = Field(default=None, ge=0)


class BookingRules(Strict):
    require_name: bool
    require_email: bool
    require_explicit_confirmation: bool
    recheck_availability: bool
    prevent_duplicate_bookings: bool


class SchedulingUI(Strict):
    show_meeting_types: bool
    show_timezone: bool
    show_confirmation: bool


class Scheduling(Strict):
    enabled: bool
    calendar: Calendar
    meeting_types: list[MeetingType] = Field(min_length=1)
    availability: Availability
    booking: BookingRules
    ui: SchedulingUI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_list(path: Path, model, errors: list[str]):
    """Validate every entry of a YAML list. Returns (valid_models, raw_data)."""
    data = load_yaml(path, errors)
    if data is None:
        return [], None
    if not isinstance(data, list):
        errors.append(f"{path.name}: top level must be a list of entries")
        return [], data
    valid = []
    for i, item in enumerate(data):
        label = f"{path.name}[{i}]"
        if isinstance(item, dict) and item.get("id"):
            label += f" ({item['id']})"
        try:
            valid.append(model.model_validate(item))
        except ValidationError as exc:
            missing = []
            for err in exc.errors():
                loc = ".".join(str(x) for x in err["loc"])
                if err["type"] == "missing" and len(err["loc"]) == 1:
                    missing.append(loc)
                else:
                    errors.append(f"{label}{'.' + loc if loc else ''}: {err['msg']}")
            if missing:
                errors.append(f"{label}: missing required field(s): {', '.join(missing)}")
    return valid, data


def parse_object(path: Path, model, errors: list[str]):
    data = load_yaml(path, errors)
    if data is None:
        return None, None
    try:
        return model.model_validate(data), data
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(f"{path.name}.{loc}: {err['msg']}")
        return None, data


def walk_strings(obj, path: str):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk_strings(value, f"{path}[{i}]")


def scan_yaml_text(raw, name: str, errors: list[str], warnings: list[str]) -> None:
    for where, text in walk_strings(raw, name):
        found = PLACEHOLDER.search(text)
        if found:
            errors.append(f"{where}: leftover placeholder '{found.group(0)}'")
        if FIRST_PERSON.search(text) and not text.startswith("http"):
            warnings.append(f"{where}: first-person wording; the agent describes Arjun in third person")


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and "." in parsed.netloc


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def norm(heading: str) -> str:
    return re.sub(r"\s+", " ", heading).strip().lower()


# ---------------------------------------------------------------------------
# Structured checks
# ---------------------------------------------------------------------------


def check_projects(projects: list[Project], kdir: Path, errors: list[str]) -> None:
    featured = [p.id for p in projects if p.featured]
    if projects and len(featured) != 1:
        errors.append(
            f"projects.yaml: exactly one project must have 'featured: true', found {len(featured)} {featured}"
        )
    for p in projects:
        where = f"projects.yaml ({p.id})"
        if not is_http_url(p.links.repo):
            errors.append(f"{where}.links.repo: '{p.links.repo}' is not a valid http(s) URL")
        for key in ("live", "video"):
            value = getattr(p.links, key)
            if value is not None and not is_http_url(value):
                errors.append(f"{where}.links.{key}: '{value}' is not a valid http(s) URL (use null if none)")
        if p.links.live is not None and p.links.live == p.links.repo:
            errors.append(f"{where}.links.live: same as repo; use null unless there is a deployed app")
        if p.status in ("runnable_not_deployed", "in_progress", "idea") and p.links.live:
            if p.links.live != p.links.repo:
                errors.append(f"{where}: status is '{p.status}' but links.live is set")
        for key, value in p.assets.items():
            if value is not None and not (kdir / value).exists():
                errors.append(
                    f"{where}.assets.{key}: file '{value}' not found under {kdir}/ (use null until the file exists)"
                )


def check_experience(experience: list[Experience], errors: list[str], warnings: list[str]) -> None:
    for e in experience:
        where = f"experience.yaml ({e.id})"
        if e.current and e.end_date is not None:
            errors.append(f"{where}: current is true but end_date is set")
        if not e.current and e.end_date is None:
            errors.append(f"{where}: current is false but end_date is missing")
        if e.end_date is not None and e.end_date < e.start_date:
            errors.append(f"{where}: end_date {e.end_date} is before start_date {e.start_date}")
        seen: set[str] = set()
        for h in e.highlights:
            if h.id in seen:
                errors.append(f"{where}: highlight id '{h.id}' is used twice")
            seen.add(h.id)
            m = h.measured
            if m is None:
                continue
            if m.before_seconds <= 0:
                errors.append(f"{where}.highlights.{h.id}.measured: before_seconds must be positive")
                continue
            expected = (m.before_seconds - m.after_seconds) / m.before_seconds * 100
            if abs(expected - m.improvement_percent) > 0.5:
                errors.append(
                    f"{where}.highlights.{h.id}.measured: improvement_percent is {m.improvement_percent} "
                    f"but before/after give {expected:.1f}"
                )
            if not m.how:
                warnings.append(
                    f"{where}.highlights.{h.id}.measured: no 'how' (how was it measured?); "
                    "numbers should say how they were measured"
                )


def check_links(links: list[Link], errors: list[str]) -> None:
    for link in links:
        if not is_http_url(link.url):
            errors.append(f"links.yaml ({link.id}).url: '{link.url}' is not a valid http(s) URL")


def check_skills(
    skills: list[Skill],
    project_status: dict[str, str],
    experience_ids: set[str],
    extra_known_ids: set[str],
    errors: list[str],
) -> None:
    seen_names: set[str] = set()
    for s in skills:
        key = s.skill.lower()
        if key in seen_names:
            errors.append(f"skills.yaml ({s.id}): skill '{s.skill}' is listed twice")
        seen_names.add(key)
        unknown = [
            e for e in s.evidence
            if e not in project_status and e not in experience_ids and e not in extra_known_ids
        ]
        for e in unknown:
            errors.append(f"skills.yaml ({s.id}): evidence id '{e}' is not a project or experience id")
        known = [e for e in s.evidence if e not in unknown]
        if known and all(project_status.get(e) == "idea" for e in known):
            errors.append(f"skills.yaml ({s.id}): evidence comes only from projects with status 'idea'")


def check_scheduling(kdir: Path, errors: list[str], warnings: list[str]) -> None:
    path = kdir / "structured" / "scheduling.yaml"
    sched, raw = parse_object(path, Scheduling, errors)
    if raw is not None:
        scan_yaml_text(raw, path.name, errors, warnings)
    if sched is None:
        return
    try:
        ZoneInfo(sched.calendar.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"scheduling.yaml.calendar.timezone: '{sched.calendar.timezone}' is not a valid IANA timezone")
    ids = [m.id for m in sched.meeting_types]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"scheduling.yaml: meeting type id '{dup}' is used twice")
    for rule in ("require_explicit_confirmation", "recheck_availability", "prevent_duplicate_bookings"):
        if not getattr(sched.booking, rule):
            errors.append(f"scheduling.yaml.booking.{rule}: must be true (booking safety rule)")

    a = sched.availability
    problems: list[str] = []
    bad_days = [d for d in a.working_days if d not in WEEKDAYS]
    if bad_days:
        errors.append(f"scheduling.yaml.availability.working_days: unknown day(s) {bad_days}; use mon..sun")
    if not a.working_days:
        problems.append("working_days is empty")
    for key in ("start_time", "end_time"):
        value = getattr(a, key)
        if value is None:
            problems.append(f"{key} is not set")
        elif not HHMM.match(value):
            errors.append(f"scheduling.yaml.availability.{key}: '{value}' must look like 'HH:MM'")
    if a.start_time and a.end_time and HHMM.match(a.start_time) and HHMM.match(a.end_time):
        if a.start_time >= a.end_time:
            errors.append("scheduling.yaml.availability: start_time must be before end_time")
    if a.min_notice_hours is None:
        problems.append("min_notice_hours is not set")
    if a.buffer_minutes is None:
        problems.append("buffer_minutes is not set")

    if sched.enabled:
        for p in problems:
            errors.append(f"scheduling.yaml.availability: booking is enabled but {p}")
    elif problems:
        warnings.append(
            "scheduling.yaml: booking is disabled and availability is incomplete "
            f"({'; '.join(problems)}); fill these in before the booking phase"
        )


# ---------------------------------------------------------------------------
# Document checks
# ---------------------------------------------------------------------------


def check_headings(rel: str, prose: str, errors: list[str]) -> list[str]:
    """Return level-2 headings; report headings that wrap onto the next line."""
    lines = prose.split("\n")
    h2: list[str] = []
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        if len(m.group(1)) == 2:
            h2.append(m.group(2))
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (
            nxt.strip()
            and not HEADING.match(nxt)
            and not re.match(r"\s*([-*+>|]|\d+\.)", nxt)
            and nxt.lstrip()[0].islower()
        ):
            errors.append(
                f"{rel}: heading '{m.group(2)}' continues on the next line "
                f"('{nxt.strip()[:40]}'); keep the whole heading on one line"
            )
    return h2


def check_project_docs(
    kdir: Path,
    projects: list[Project],
    unparsed_ids: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    by_id = {p.id: p for p in projects}
    docs_dir = kdir / "docs" / "projects"
    files = {f.stem: f for f in sorted(docs_dir.glob("*.md"))}
    for pid in by_id:
        if pid not in files:
            errors.append(f"projects.yaml ({pid}): no docs/projects/{pid}.md")
    for stem, f in files.items():
        rel = f"docs/projects/{f.name}"
        if stem not in by_id:
            if stem not in unparsed_ids:  # unparsed ones are already reported
                errors.append(f"{rel}: no project with id '{stem}' in projects.yaml")
            continue
        project = by_id[stem]
        fm, body = split_front_matter(read_text(f))
        if fm is None:
            errors.append(f"{rel}: missing or invalid front matter (needs project_id and status)")
            continue
        if fm.get("project_id") != stem:
            errors.append(f"{rel}: front-matter project_id is '{fm.get('project_id')}', expected '{stem}'")
        if fm.get("status") != project.status:
            errors.append(
                f"{rel}: front-matter status '{fm.get('status')}' disagrees with projects.yaml '{project.status}'"
            )

        prose = strip_code(body)
        h2 = {norm(h) for h in check_headings(rel, prose, errors)}
        for name, accepted in REQUIRED_SECTIONS.items():
            if not any(norm(a) in h2 for a in accepted):
                errors.append(f"{rel}: missing '{name}' section (accepted headings: {', '.join(accepted)})")
        for name, accepted in RECOMMENDED_SECTIONS.items():
            if not any(norm(a) in h2 for a in accepted):
                warnings.append(f"{rel}: no '{name}' section (accepted headings: {', '.join(accepted)})")

        found = PLACEHOLDER.search(prose)
        if found:
            errors.append(f"{rel}: leftover placeholder '{found.group(0)}'")
        if FIRST_PERSON.search(prose):
            warnings.append(f"{rel}: first-person wording; docs should say 'Arjun'")
        flat = re.sub(r"\s+", " ", prose)
        for m in INSTRUCTION.finditer(flat):
            snippet = flat[m.start(1): m.start(1) + 60]
            warnings.append(
                f"{rel}: instruction-style sentence ('{snippet}...'); state it as a fact "
                "or move it to boundaries.md"
            )
        if project.status in ("in_progress", "idea") and re.search(
            r"\b(built|completed|deployed|launched)\b", prose, re.I
        ):
            warnings.append(f"{rel}: status is '{project.status}' but the text says built/completed/deployed; check wording")


def check_other_docs(kdir: Path, errors: list[str], warnings: list[str]) -> None:
    for name, content_type in DOC_TYPES.items():
        path = kdir / "docs" / name
        rel = f"docs/{name}"
        if not path.exists():
            errors.append(f"{rel}: file is missing")
            continue
        fm, body = split_front_matter(read_text(path))
        if fm is None or fm.get("content_type") != content_type:
            errors.append(f"{rel}: front matter must contain 'content_type: {content_type}'")
        prose = strip_code(body)
        if not prose.strip():
            errors.append(f"{rel}: file has no content")
            continue
        check_headings(rel, prose, errors)
        found = PLACEHOLDER.search(prose)
        if found:
            errors.append(f"{rel}: leftover placeholder '{found.group(0)}'")
        if FIRST_PERSON.search(prose):
            warnings.append(f"{rel}: first-person wording; docs should say 'Arjun' or 'he'")
        if name == "faq.md":
            parts = re.split(r"^###\s+(.+)$", prose, flags=re.M)
            for question, answer in zip(parts[1::2], parts[2::2]):
                if not answer.strip():
                    errors.append(f"{rel}: question '{question.strip()}' has no answer")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate(kdir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    s = kdir / "structured"

    projects, raw_projects = parse_list(s / "projects.yaml", Project, errors)
    experience, raw_experience = parse_list(s / "experience.yaml", Experience, errors)
    skills, raw_skills = parse_list(s / "skills.yaml", Skill, errors)
    links, raw_links = parse_list(s / "links.yaml", Link, errors)

    for name, raw in (
        ("projects.yaml", raw_projects),
        ("experience.yaml", raw_experience),
        ("skills.yaml", raw_skills),
        ("links.yaml", raw_links),
    ):
        if raw is not None:
            scan_yaml_text(raw, name, errors, warnings)

    all_ids = [p.id for p in projects] + [e.id for e in experience]
    for dup in sorted({i for i in all_ids if all_ids.count(i) > 1}):
        errors.append(f"id '{dup}' is used more than once across projects.yaml and experience.yaml")
    for label, items in (("skills.yaml", skills), ("links.yaml", links)):
        ids = [i.id for i in items]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            errors.append(f"{label}: id '{dup}' is used twice")

    def raw_ids(raw) -> set[str]:
        return {i["id"] for i in (raw or []) if isinstance(i, dict) and isinstance(i.get("id"), str)}

    unparsed_projects = raw_ids(raw_projects) - {p.id for p in projects}
    unparsed_experience = raw_ids(raw_experience) - {e.id for e in experience}

    check_projects(projects, kdir, errors)
    check_experience(experience, errors, warnings)
    check_links(links, errors)
    check_skills(
        skills,
        {p.id: p.status for p in projects},
        {e.id for e in experience},
        unparsed_projects | unparsed_experience,
        errors,
    )
    check_scheduling(kdir, errors, warnings)
    check_project_docs(kdir, projects, unparsed_projects, errors, warnings)
    check_other_docs(kdir, errors, warnings)

    # same message can be reported by two checks (e.g. a placeholder URL); show once
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


FILE_PREFIX = re.compile(r"^[\w/.-]+?\.(?:yaml|md)")


def by_file(messages: list[str]) -> list[str]:
    def key(msg: str) -> str:
        m = FILE_PREFIX.match(msg)
        return m.group(0) if m else "~"

    return sorted(messages, key=key)  # stable: keeps check order inside a file


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]
    kdir = Path(args[0]) if args else Path("knowledge")
    errors, warnings = validate(kdir)
    for w in by_file(warnings):
        print(f"WARN   {w}")
    for e in by_file(errors):
        print(f"ERROR  {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))