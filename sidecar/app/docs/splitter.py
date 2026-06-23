"""Recursive text splitter for documentation (Index C).

Splits markdown/text docs into overlapping, embeddable chunks along natural
boundaries — markdown headings first, then blank-line-separated paragraphs — so
each chunk is a semantically whole passage. Every chunk carries a heading
breadcrumb (the nearest enclosing `#`/`##` trail) and a 1-based line range so it
can be cited precisely on retrieval. Fully deterministic: no LLM, no network.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel

from app.config import Settings, get_settings

# A markdown ATX heading: one-to-six leading '#', a space, then the title.
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


class DocChunk(BaseModel):
    """A single passage of documentation with its provenance metadata."""

    chunk_id: str
    repo: str
    file_path: str  # POSIX, relative to the repo root
    heading: str  # nearest heading breadcrumb, e.g. "Setup > Installing"
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    text: str


def _make_chunk_id(repo: str, file_path: str, start_line: int, end_line: int) -> str:
    """Stable id so re-indexing the same doc is idempotent."""
    raw = f"{repo}|{file_path}|{start_line}|{end_line}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _iter_segments(lines: list[str]):
    """Yield (start, end, text) blocks split on blank lines.

    ``start`` is the 0-based index of the first line and ``end`` is the 0-based
    index just past the last line. Fenced code blocks (```) are kept intact so a
    blank line inside a code sample does not split it.
    """
    buf: list[str] = []
    start = 0
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not stripped and not in_fence:
            if buf:
                yield start, i, "\n".join(buf)
                buf = []
            continue
        if not buf:
            start = i
        buf.append(line)
    if buf:
        yield start, len(lines), "\n".join(buf)


def _heading_of(segment_text: str) -> tuple[int, str] | None:
    """If a segment's first line is a markdown heading, return (level, title)."""
    match = _HEADING.match(segment_text.splitlines()[0]) if segment_text else None
    if match is None:
        return None
    return len(match.group(1)), match.group(2).strip()


def _window(text: str, size: int, overlap: int):
    """Hard-split an oversized segment into character windows with overlap."""
    step = max(1, size - overlap)
    for i in range(0, len(text), step):
        yield text[i : i + size]
        if i + size >= len(text):
            break


def split_text(
    text: str,
    *,
    repo: str,
    file_path: str,
    settings: Settings | None = None,
) -> list[DocChunk]:
    """Split one document's text into overlapping, heading-aware chunks."""
    settings = settings or get_settings()
    size = settings.doc_chunk_chars
    overlap = settings.doc_chunk_overlap

    lines = text.splitlines()
    chunks: list[DocChunk] = []
    stack: dict[int, str] = {}  # heading level -> title, for the breadcrumb

    # The current (in-progress) chunk: its segments, char count, and the heading
    # breadcrumb captured when its first segment was added.
    cur: list[tuple[int, int, str]] = []
    cur_chars = 0
    cur_heading = ""

    def breadcrumb() -> str:
        return " > ".join(stack[level] for level in sorted(stack))

    def emit(segments: list[tuple[int, int, str]], heading: str) -> None:
        body = "\n\n".join(s[2] for s in segments).strip()
        if not body:
            return
        start_line = segments[0][0] + 1
        end_line = segments[-1][1]
        chunks.append(
            DocChunk(
                chunk_id=_make_chunk_id(repo, file_path, start_line, end_line),
                repo=repo,
                file_path=file_path,
                heading=heading,
                start_line=start_line,
                end_line=end_line,
                text=body,
            )
        )

    def flush() -> None:
        nonlocal cur, cur_chars
        if cur:
            emit(cur, cur_heading)
        # Seed the next chunk with the trailing segments (up to ``overlap``
        # chars) so context is not lost across a chunk boundary.
        carried: list[tuple[int, int, str]] = []
        carried_chars = 0
        for seg in reversed(cur):
            if carried_chars >= overlap:
                break
            carried.insert(0, seg)
            carried_chars += len(seg[2]) + 2
        cur = carried
        cur_chars = carried_chars

    for seg_start, seg_end, seg_text in _iter_segments(lines):
        heading = _heading_of(seg_text)
        if heading is not None:
            level, title = heading
            # A new heading replaces its level and clears any deeper levels.
            stack[level] = title
            for deeper in [lvl for lvl in stack if lvl > level]:
                del stack[deeper]

        seg_len = len(seg_text) + 2

        # An oversized single segment (e.g. a long code block) is windowed on its
        # own so no chunk blows past the embedding model's context budget.
        if seg_len > size and not cur:
            for piece in _window(seg_text, size, overlap):
                emit([(seg_start, seg_end, piece)], breadcrumb())
            continue

        # Flush before the segment if it would overflow the current chunk.
        if cur and cur_chars + seg_len > size:
            flush()

        if not cur:
            cur_heading = breadcrumb()
        cur.append((seg_start, seg_end, seg_text))
        cur_chars += seg_len

    if cur:
        emit(cur, cur_heading)

    return chunks


def iter_doc_files(repo_root: Path) -> list[Path]:
    """List documentation files under a repo, skipping excluded directories."""
    settings = get_settings()
    exclude = set(settings.index_exclude_dirs)
    extensions = {ext.lower() for ext in settings.doc_extensions}
    results: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in exclude for part in path.relative_to(repo_root).parts[:-1]):
            continue
        if path.suffix.lower() in extensions:
            results.append(path)
    return results


def chunk_docs_repo(repo_root: Path) -> list[DocChunk]:
    """Chunk every documentation file in a repository."""
    settings = get_settings()
    repo = repo_root.name
    chunks: list[DocChunk] = []
    for path in iter_doc_files(repo_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        file_path = path.relative_to(repo_root).as_posix()
        chunks.extend(split_text(text, repo=repo, file_path=file_path, settings=settings))
    return chunks
