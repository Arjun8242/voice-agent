"""Tests for S3. Each test builds a tiny valid knowledge folder, breaks one
thing, and checks that the validator reports it. Independent of your real files."""

from pathlib import Path

import pytest

from backend.kb.validate import validate

PROJECTS = """\
- id: alpha
  name: Alpha
  one_line: Alpha is a small test project.
  status: shipped
  featured: true
  tech: [Python]
  role: Built it.
  links: {repo: https://github.com/x/alpha, live: https://alpha.example.com, video: null}
  assets: {architecture_image: null}
  highlights:
    - Does one thing
  measured:
    - claim: 3 jobs instead of 6
      how: Ran two instances and counted jobs
  updated: 2026-10-01
"""
EXPERIENCE = """\
- id: acme
  organization: Acme
  role: Intern
  type: internship
  start_date: "2025-11"
  end_date: "2026-02"
  current: false
  location: Delhi
  tech: [SQL]
  one_line: Worked on reports.
  highlights:
    - id: speedup
      description: Made reports faster.
      measured: {before_seconds: 6, after_seconds: 1.5, improvement_percent: 75, how: Timed the endpoint}
  updated: "2026-10-01"
"""
SKILLS = """\
- id: python
  skill: Python
  category: language
  evidence: [alpha]
- id: sql
  skill: SQL
  category: database
  evidence: [acme]
"""
LINKS = """\
- id: github
  label: GitHub
  type: github_profile
  url: https://github.com/x
  description: Source code.
"""
SCHEDULING = """\
enabled: true
calendar: {provider: google_calendar, calendar_id: primary, timezone: Asia/Kolkata}
meeting_types:
  - {id: screening, title: Screening, duration_minutes: 15, description: Intro}
availability:
  working_days: [mon, tue]
  start_time: "10:00"
  end_time: "17:00"
  booking_horizon_days: 14
  min_notice_hours: 12
  buffer_minutes: 15
booking:
  require_name: true
  require_email: true
  require_explicit_confirmation: true
  recheck_availability: true
  prevent_duplicate_bookings: true
ui: {show_meeting_types: true, show_timezone: true, show_confirmation: true}
"""
PROJECT_DOC = """\
---
project_id: alpha
status: shipped
---
# Alpha

## Overview

Alpha is a test project.

## Architecture

One service.

## Key decisions

Chose simple.

## Limitations and not yet done

Nothing scales.

## Status and what is tested

Tested by hand.
"""
BIO = "---\ncontent_type: candidate_bio\nscope: candidate\n---\n# Bio\n\nArjun builds software.\n"
FAQ = "---\ncontent_type: candidate_faq\nscope: candidate\n---\n# FAQ\n\n### What does he do?\nHe builds software.\n"
BOUNDARIES = "---\ncontent_type: candidate_boundaries\nscope: candidate\n---\n# Boundaries\n\n### Salary\nDo not state a number.\n"


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / "structured").mkdir(parents=True)
    (root / "docs" / "projects").mkdir(parents=True)
    files = {
        "structured/projects.yaml": PROJECTS,
        "structured/experience.yaml": EXPERIENCE,
        "structured/skills.yaml": SKILLS,
        "structured/links.yaml": LINKS,
        "structured/scheduling.yaml": SCHEDULING,
        "docs/projects/alpha.md": PROJECT_DOC,
        "docs/bio.md": BIO,
        "docs/faq.md": FAQ,
        "docs/boundaries.md": BOUNDARIES,
    }
    for rel, text in files.items():
        (root / rel).write_text(text, encoding="utf-8")
    return root


def edit(kb: Path, rel: str, old: str, new: str) -> None:
    path = kb / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"test setup: '{old}' not found in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def errors_of(kb: Path) -> list[str]:
    return validate(kb)[0]


def test_clean_kb_has_no_errors(kb):
    assert errors_of(kb) == []


def test_invalid_status_fails(kb):
    edit(kb, "structured/projects.yaml", "status: shipped", "status: not shipped but runs")
    assert any("projects.yaml" in e and "status" in e for e in errors_of(kb))


def test_missing_status_fails(kb):
    edit(kb, "structured/projects.yaml", "  status: shipped\n", "")
    assert any("status" in e for e in errors_of(kb))


def test_no_featured_project_fails(kb):
    edit(kb, "structured/projects.yaml", "featured: true", "featured: false")
    assert any("featured" in e for e in errors_of(kb))


def test_unknown_evidence_id_fails(kb):
    edit(kb, "structured/skills.yaml", "evidence: [alpha]", "evidence: [nonexistent]")
    assert any("nonexistent" in e for e in errors_of(kb))


def test_empty_evidence_fails(kb):
    edit(kb, "structured/skills.yaml", "evidence: [alpha]", "evidence: []")
    assert any("evidence" in e for e in errors_of(kb))


def test_doc_status_must_match_yaml(kb):
    edit(kb, "docs/projects/alpha.md", "status: shipped", "status: idea")
    assert any("disagrees" in e for e in errors_of(kb))


def test_missing_limitations_section_fails(kb):
    edit(kb, "docs/projects/alpha.md", "## Limitations and not yet done", "## Other notes")
    assert any("Limitations" in e for e in errors_of(kb))


def test_project_without_doc_fails(kb):
    (kb / "docs" / "projects" / "alpha.md").unlink()
    assert any("no docs/projects/alpha.md" in e for e in errors_of(kb))


def test_placeholder_url_fails(kb):
    edit(kb, "structured/links.yaml", "https://github.com/x", "YOUR_GITHUB_URL")
    assert any("links.yaml" in e for e in errors_of(kb))


def test_live_link_equal_to_repo_fails(kb):
    edit(kb, "structured/projects.yaml", "live: https://alpha.example.com", "live: https://github.com/x/alpha")
    assert any("same as repo" in e for e in errors_of(kb))


def test_missing_asset_file_fails(kb):
    edit(kb, "structured/projects.yaml", "architecture_image: null", "architecture_image: img/none.png")
    assert any("not found" in e for e in errors_of(kb))


def test_wrong_improvement_percent_fails(kb):
    edit(kb, "structured/experience.yaml", "improvement_percent: 75", "improvement_percent: 90")
    assert any("improvement_percent" in e for e in errors_of(kb))


def test_enabled_booking_needs_availability(kb):
    edit(kb, "structured/scheduling.yaml", "working_days: [mon, tue]", "working_days: []")
    assert any("working_days" in e for e in errors_of(kb))


def test_disabled_booking_only_warns(kb):
    edit(kb, "structured/scheduling.yaml", "enabled: true", "enabled: false")
    edit(kb, "structured/scheduling.yaml", "working_days: [mon, tue]", "working_days: []")
    errors, warnings = validate(kb)
    assert errors == []
    assert any("working_days" in w for w in warnings)


def test_heading_wrapped_onto_next_line_fails(kb):
    edit(kb, "docs/projects/alpha.md", "## Key decisions\n", "### How does it avoid doing\nthe same thing twice?\n\n## Key decisions\n")
    assert any("continues on the next line" in e for e in errors_of(kb))


def test_faq_question_without_answer_fails(kb):
    (kb / "docs" / "faq.md").write_text(
        "---\ncontent_type: candidate_faq\n---\n# FAQ\n\n### Q1?\n\n### Q2?\nAnswer.\n", encoding="utf-8"
    )
    assert any("has no answer" in e for e in errors_of(kb))