"""resume.py: the resume and job-description text an interview is planned from. No LLM.

PDF -> text, the input checks that run before any LLM call, and contact stripping
(v2 design, "Analysis call", steps 1-3).

Rules a reader would not guess:
- A PDF with almost no text is rejected, not guessed at: it is a scan or an empty file (W6).
- Contact details (emails, phones, links, postal addresses) are removed before the text reaches any
  prompt or log. Only the stripped text is kept, so claims are verified against it too.
- A number counts as a phone only with 10 or more digits: "2019 - 2023" and "500000 users" stay.
- Long inputs are cut, not rejected: a whole job page pasted as the JD is normal.
"""

from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MIN_RESUME_CHARS = 300
MAX_RESUME_CHARS = 12_000
MAX_JD_CHARS = 8_000
MIN_PHONE_DIGITS = 10

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINK = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com|gitlab\.com)/\S*", re.I)
PHONE_LIKE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
# shortcut: an address line needs an address word and a postal code; upgrade if real resumes slip through
ADDRESS_LINE = re.compile(
    r"^(?=.*\b(?:road|rd|street|nagar|sector|colony|lane|marg|apartment|apt|flat|block|district|india)\b)"
    r"(?=.*\b(?:\d{3}\s?\d{3}|\d{5})\b).*$", re.I | re.M)


class ResumeError(Exception):
    """An input the interview cannot be planned from. code is for the client; the message is shown."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def pdf_text(pdf: bytes) -> str:
    """The text of every page, in order. Raises ResumeError for a file that is not a readable PDF."""
    try:
        pages = PdfReader(BytesIO(pdf)).pages
        return "\n".join(page.extract_text() or "" for page in pages)
    except (PdfReadError, ValueError, KeyError) as err:
        raise ResumeError("not_a_pdf", "That file could not be read as a PDF.") from err


def drop_phone(match: re.Match) -> str:
    digits = sum(char.isdigit() for char in match.group())
    return "" if digits >= MIN_PHONE_DIGITS else match.group()


def strip_contacts(text: str) -> str:
    """The text without emails, phone numbers, links or address lines."""
    text = ADDRESS_LINE.sub("", text)
    text = LINK.sub("", EMAIL.sub("", text))
    text = PHONE_LIKE.sub(drop_phone, text)
    return re.sub(r"[ \t]+\n", "\n", text)


def clean_resume(pdf: bytes) -> str:
    """The resume text a plan may be built from: contacts stripped, length capped."""
    text = strip_contacts(pdf_text(pdf)).strip()
    if len(text) < MIN_RESUME_CHARS:
        raise ResumeError("too_little_text", "The PDF has almost no text. Upload a text PDF, not a scan or photo.")
    return text[:MAX_RESUME_CHARS]


def clean_job_description(text: str) -> str:
    return strip_contacts(text).strip()[:MAX_JD_CHARS]
