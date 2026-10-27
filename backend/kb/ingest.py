"""S4: build the searchable knowledge-base index.

Run from the repository root:
    python -m backend.kb.ingest knowledge_base --out data/kb_index.json

Pipeline:
    validate -> chunk -> embed -> validate vectors -> write JSON list

Note: writing directly to the final file is simple, but a disk/write failure
can leave the previous index incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .loaders import read_text, split_front_matter
from .validate import (
    HEADING,
    Experience,
    Project,
    Skill,
    parse_list,
    validate,
)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
CHUNKER_VERSION = 2
MAX_CHUNK_TOKENS = 400

DEFAULT_OUT = (
    Path(__file__).resolve().parents[2] / "data" / "kb_index.json"
)

OTHER_DOCS = {
    "bio.md": ("bio", "Bio"),
    "faq.md": ("faq", "FAQ"),
    "boundaries.md": ("boundary", "Boundaries"),
}

ENTRIES_ONLY = {"faq.md", "boundaries.md"}

Embedder = Callable[[list[str]], list[list[float]]]
_embedding_model: Any = None


class IngestError(Exception):
    """Raised when the KB cannot be turned into a valid index."""


@dataclass
class Chunk:
    id: str
    type: str
    title: str
    content: str
    source: str
    section: str
    project_id: str | None
    status: str | None
    kb_version: str = ""


# ---------------------------------------------------------------------
# Markdown chunking
# ---------------------------------------------------------------------

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def est_tokens(text: str) -> int:
    """Rough estimate only; this is not the model's real tokenizer."""
    return (len(text) + 3) // 4


def split_sections(body: str) -> list[tuple[list[str], str]]:
    """Split Markdown into heading paths and section text."""
    sections: list[tuple[list[str], list[str]]] = [([], [])]
    path: list[str] = []
    h2: str | None = None
    in_fence = False

    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence

        match = None if in_fence else HEADING.match(line)

        if match and len(match.group(1)) <= 3:
            level = len(match.group(1))
            heading = match.group(2).strip()

            if level == 1:
                h2, path = None, []
            elif level == 2:
                h2, path = heading, [heading]
            else:
                path = [h2, heading] if h2 else [heading]

            sections.append((list(path), []))
        else:
            sections[-1][1].append(line)

    return [
        (heading_path, "\n".join(lines).strip())
        for heading_path, lines in sections
    ]


def _split_oversized_paragraph(text: str) -> list[str]:
    """Split oversized text at sentence boundaries, then whitespace."""
    if est_tokens(text) <= MAX_CHUNK_TOKENS:
        return [text]

    max_chars = MAX_CHUNK_TOKENS * 4
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
        if part.strip()
    ]

    if not sentences:
        sentences = [text.strip()]

    pieces: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            pieces.append(current)
            current = ""

    for sentence in sentences:
        if est_tokens(sentence) > MAX_CHUNK_TOKENS:
            flush()
            remaining = sentence

            while len(remaining) > max_chars:
                cut = remaining.rfind(" ", 0, max_chars + 1)
                if cut <= 0:
                    cut = remaining.rfind("\n", 0, max_chars + 1)
                if cut <= 0:
                    cut = max_chars

                part = remaining[:cut].strip()
                if part:
                    pieces.append(part)
                remaining = remaining[cut:].strip()

            if remaining:
                current = remaining
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence

        if current and est_tokens(candidate) > MAX_CHUNK_TOKENS:
            flush()
            current = sentence
        else:
            current = candidate

    flush()
    return pieces or [text.strip()]


def split_long(text: str) -> list[str]:
    """Pack paragraphs into chunks of approximately 400 estimated tokens."""
    parts: list[str] = []
    current: list[str] = []

    for paragraph in re.split(r"\n\s*\n", text):
        if not paragraph.strip():
            continue

        for subparagraph in _split_oversized_paragraph(paragraph):
            candidate = "\n\n".join(current + [subparagraph])

            if current and est_tokens(candidate) > MAX_CHUNK_TOKENS:
                parts.append("\n\n".join(current))
                current = [subparagraph]
            else:
                current.append(subparagraph)

    if current:
        parts.append("\n\n".join(current))

    return parts


def chunk_markdown(
    body: str,
    *,
    rel: str,
    chunk_type: str,
    root: str,
    project_id: str | None,
    status: str | None,
    entries_only: bool = False,
    split_oversize: bool = False,
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for heading_path, section_text in split_sections(body):
        if not section_text:
            continue
        if entries_only and not heading_path:
            continue

        pieces = split_long(section_text) if split_oversize else [section_text]

        for number, piece in enumerate(pieces, start=1):
            suffix = "" if number == 1 else f"-p{number}"
            anchor = "/".join(slug(part) for part in heading_path) or "_intro"
            title = " > ".join([root, *heading_path])

            if number > 1:
                title += f" (part {number})"

            chunks.append(
                Chunk(
                    id=f"{rel}#{anchor}{suffix}",
                    type=chunk_type,
                    title=title,
                    content=piece,
                    source=rel,
                    section=heading_path[-1] if heading_path else root,
                    project_id=project_id,
                    status=status,
                )
            )

    return chunks


# ---------------------------------------------------------------------
# YAML data -> searchable chunks
# ---------------------------------------------------------------------

def _fmt_measured(measurement: Any) -> str:
    bits = [
        f"before {measurement.before_seconds}s",
        f"after {measurement.after_seconds}s",
    ]

    if measurement.improvement_percent is not None:
        bits.append(f"{measurement.improvement_percent}% improvement")

    result = "Measured: " + ", ".join(bits)

    if measurement.how:
        result += f". How: {measurement.how}"

    return result


def chunk_skills(
    skills: list[Skill],
    names: dict[str, str],
    statuses: dict[str, str],
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for skill in skills:
        evidence = ", ".join(
            f"{names.get(item, item)} ({statuses[item]})"
            if item in statuses
            else names.get(item, item)
            for item in skill.evidence
        )

        chunks.append(
            Chunk(
                id=f"skills.yaml#{skill.id}",
                type="skill",
                title=f"Skills > {skill.skill}",
                content=(
                    f"{skill.skill} is a {skill.category} skill. "
                    f"Evidence: {evidence}."
                ),
                source="structured/skills.yaml",
                section=skill.skill,
                project_id=None,
                status=None,
            )
        )

    return chunks


def chunk_experience(entries: list[Experience]) -> list[Chunk]:
    chunks: list[Chunk] = []

    for entry in entries:
        end = (
            "present"
            if entry.current or not entry.end_date
            else entry.end_date
        )

        lines = [
            (
                f"{entry.role} at {entry.organization} "
                f"({entry.type.replace('_', ' ')}), "
                f"{entry.start_date} to {end}, {entry.location}."
            ),
            entry.one_line,
            "Tech: " + ", ".join(entry.tech) + ".",
            "Highlights:",
        ]

        for highlight in entry.highlights:
            line = f"- {highlight.description}"

            if highlight.measured:
                line += " " + _fmt_measured(highlight.measured)

            lines.append(line)

        chunks.append(
            Chunk(
                id=f"experience.yaml#{entry.id}",
                type="experience",
                title=f"Experience > {entry.organization} > {entry.role}",
                content="\n".join(lines),
                source="structured/experience.yaml",
                section=entry.role,
                project_id=None,
                status=None,
            )
        )

    return chunks


def build_chunks(kdir: Path) -> list[Chunk]:
    """Chunk a KB directory. Validation is performed by build_index first."""
    errors: list[str] = []
    structured = kdir / "structured"

    projects, _ = parse_list(
        structured / "projects.yaml", Project, errors
    )
    skills, _ = parse_list(
        structured / "skills.yaml", Skill, errors
    )
    experience, _ = parse_list(
        structured / "experience.yaml", Experience, errors
    )

    if errors:
        raise IngestError("; ".join(errors))

    names = {
        project.id: project.name for project in projects
    } | {
        entry.id: entry.organization for entry in experience
    }
    statuses = {project.id: project.status for project in projects}

    chunks: list[Chunk] = []

    for project in projects:
        path = kdir / "docs" / "projects" / f"{project.id}.md"
        front_matter, body = split_front_matter(read_text(path))

        chunks.extend(
            chunk_markdown(
                body,
                rel=f"docs/projects/{project.id}.md",
                chunk_type="project_doc",
                root=project.name,
                project_id=project.id,
                status=(front_matter or {}).get("status", project.status),
                split_oversize=True,
            )
        )

    for filename, (chunk_type, root) in OTHER_DOCS.items():
        _, body = split_front_matter(read_text(kdir / "docs" / filename))

        chunks.extend(
            chunk_markdown(
                body,
                rel=f"docs/{filename}",
                chunk_type=chunk_type,
                root=root,
                project_id=None,
                status=None,
                entries_only=filename in ENTRIES_ONLY,
            )
        )

    chunks.extend(chunk_skills(skills, names, statuses))
    chunks.extend(chunk_experience(experience))

    seen: dict[str, int] = {}
    for chunk in chunks:
        seen[chunk.id] = seen.get(chunk.id, 0) + 1

    duplicates = sorted(
        chunk_id for chunk_id, count in seen.items() if count > 1
    )

    if duplicates:
        raise IngestError(
            "duplicate chunk IDs (possibly repeated headings): "
            + ", ".join(duplicates)
        )

    return sorted(chunks, key=lambda chunk: chunk.id)


# ---------------------------------------------------------------------
# Embedding and index writing
# ---------------------------------------------------------------------

def compute_kb_version(chunks: list[Chunk]) -> str:
    """Hash chunk text and metadata, excluding vector values."""
    payload = {
        "chunker": CHUNKER_VERSION,
        "model": EMBEDDING_MODEL,
        "chunks": [
            {**asdict(chunk), "kb_version": ""}
            for chunk in chunks
        ],
    }

    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def default_embedder(texts: list[str]) -> list[list[float]]:
    """Load the embedding model lazily and reuse it within this process."""
    global _embedding_model

    if not texts:
        return []

    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    vectors = _embedding_model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
    )

    return [
        [round(float(value), 6) for value in vector]
        for vector in vectors
    ]


def validate_vectors(
    vectors: list[list[float]],
    expected_count: int,
) -> list[list[float]]:
    """Validate count, dimensions, finite values, and unit vector norms."""
    if len(vectors) != expected_count:
        raise IngestError(
            f"embedder returned {len(vectors)} vectors "
            f"for {expected_count} chunks"
        )

    validated: list[list[float]] = []

    for index, vector in enumerate(vectors):
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise IngestError(
                f"vector {index} contains non-numeric values"
            ) from exc

        if len(values) != EMBEDDING_DIM:
            raise IngestError(
                f"vector {index} has dimension {len(values)}; "
                f"expected {EMBEDDING_DIM}"
            )

        if not all(math.isfinite(value) for value in values):
            raise IngestError(
                f"vector {index} contains NaN or infinity"
            )

        norm = math.sqrt(math.fsum(value * value for value in values))

        if not math.isfinite(norm) or abs(norm - 1.0) > 1e-3:
            raise IngestError(
                f"vector {index} is not normalized "
                f"(L2 norm={norm:.6f}; expected approximately 1.0)"
            )

        validated.append(values)

    return validated


def write_index(path: Path, records: list[dict]) -> None:
    """Write a JSON-list index directly to its final path.

    Simpler than atomic replacement, but a crash or disk error during writing
    can leave the existing file truncated or incomplete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            records,
            file,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )


def build_index(
    kdir: Path,
    out: Path,
    *,
    embedder: Embedder = default_embedder,
    strict: bool = False,
) -> dict:
    """Validate, chunk, embed, and write the JSON-list index."""
    errors, warnings = validate(kdir)

    if strict:
        errors = errors + warnings

    if errors:
        raise IngestError(
            f"{len(errors)} validation problem(s):\n  "
            + "\n  ".join(errors)
        )

    chunks = build_chunks(kdir)
    version = compute_kb_version(chunks)
    texts = [f"{chunk.title}\n{chunk.content}" for chunk in chunks]

    vectors = validate_vectors(embedder(texts), len(chunks))

    records = [
        {
            **asdict(chunk),
            "kb_version": version,
            "embedding_model": EMBEDDING_MODEL,
            "dim": EMBEDDING_DIM,
            "vec": vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    # Validation and embedding complete before the output is opened.
    write_index(out, records)

    return {
        "kb_version": version,
        "embedding_model": EMBEDDING_MODEL,
        "dim": EMBEDDING_DIM if records else 0,
        "chunks": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the searchable knowledge-base index."
    )
    parser.add_argument(
        "kdir",
        nargs="?",
        type=Path,
        default=Path("knowledge_base"),
        help="knowledge-base directory (default: knowledge_base)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat validation warnings as errors",
    )

    args = parser.parse_args(argv)

    try:
        index = build_index(
            args.kdir,
            args.out,
            strict=args.strict,
        )
    except IngestError as exc:
        print(f"ERROR: {exc}\nNo index written.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: could not read/write files: {exc}", file=sys.stderr)
        return 1

    print(
        f"kb_version {index['kb_version']}  "
        f"chunks {len(index['chunks'])}  -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())