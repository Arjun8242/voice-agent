"""The resume and JD before any LLM call (v2 design, W6 and contact stripping): bad files are rejected,
contact details never reach a prompt, and long inputs are cut."""

from __future__ import annotations

import pytest

from backend.interview.resume import (
    MAX_JD_CHARS,
    MAX_RESUME_CHARS,
    ResumeError,
    clean_job_description,
    clean_resume,
)
from backend.tests.interview.fixtures import RESUME, scanned_pdf, text_pdf


def test_a_scanned_pdf_or_a_file_that_is_not_a_pdf_is_rejected():
    with pytest.raises(ResumeError) as scanned:
        clean_resume(scanned_pdf())
    with pytest.raises(ResumeError) as not_pdf:
        clean_resume(b"just some bytes")
    assert (scanned.value.code, not_pdf.value.code) == ("too_little_text", "not_a_pdf")


def test_contact_details_are_stripped_but_dates_and_numbers_stay():
    text = clean_resume(text_pdf(RESUME))
    for contact in ("priya.sharma@example.com", "98765", "github.com", "MG Road"):
        assert contact not in text, contact
    for kept in ("Priya Sharma", "May 2024 - Aug 2024", "40,000 refunds", "900 ms to 300 ms"):
        assert kept in text, kept


def test_long_inputs_are_cut_not_rejected():
    long_resume = RESUME + "\n".join(f"- Shipped feature number {i} to production." for i in range(600))
    assert len(clean_resume(text_pdf(long_resume))) == MAX_RESUME_CHARS
    assert len(clean_job_description("Kafka. " * 5000)) == MAX_JD_CHARS
