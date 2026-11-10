"""Shared readers for the knowledge files.

validate.py uses these now; ingest.py (S4) will reuse them.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def read_text(path: Path) -> str:
    # utf-8-sig drops a BOM if a Windows editor added one; CRLF becomes LF
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def load_yaml(path: Path, errors: list[str]):
    """Return parsed YAML, or None after appending a readable error."""
    try:
        return yaml.safe_load(read_text(path))
    except FileNotFoundError:
        errors.append(f"{path.name}: file is missing")
    except yaml.YAMLError as err:
        errors.append(f"{path.name}: invalid YAML: {err}")
    return None


def split_front_matter(text: str) -> tuple[dict | None, str]:
    """Split '---\\nkey: value\\n---\\nbody'. Returns (None, text) if absent or invalid."""
    match = _FRONT_MATTER.match(text)
    if not match:
        return None, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    return data, text[match.end():]