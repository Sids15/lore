"""Function-level blame via `git blame` on the current files.

For each function/method/class (whose line range we already know from the AST
chunker), find the most-recent commit touching any of its lines. This answers
"who last changed the auth function?" without diff-hunk archaeology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import git

from app.history.git_walker import open_repo
from app.ingest.ast_chunker import CodeChunk

_ENTITY_KINDS = {"function", "method", "class"}


@dataclass
class BlameEntry:
    file_path: str
    function_name: str
    last_sha: str
    last_author: str
    last_modified_at: str  # ISO-8601


def _line_map(repo: git.Repo, file_path: str) -> dict[int, tuple[str, str, object]]:
    """Map each 1-based line of a file to (sha, author, committed_datetime)."""
    try:
        blocks = repo.blame("HEAD", file_path)
    except git.GitError:
        return {}
    line_map: dict[int, tuple[str, str, object]] = {}
    line_no = 1
    for commit, lines in blocks or []:
        for _ in lines:
            line_map[line_no] = (commit.hexsha, commit.author.name or "", commit.committed_datetime)
            line_no += 1
    return line_map


def blame_functions(repo_path: Path, chunks: list[CodeChunk]) -> list[BlameEntry]:
    """Attribute each entity chunk to the latest commit touching its lines."""
    repo = open_repo(repo_path)
    if repo is None:
        return []

    by_file: dict[str, list[CodeChunk]] = {}
    for chunk in chunks:
        if chunk.kind in _ENTITY_KINDS:
            by_file.setdefault(chunk.file_path, []).append(chunk)

    entries: list[BlameEntry] = []
    for file_path, file_chunks in by_file.items():
        line_map = _line_map(repo, file_path)
        if not line_map:
            continue
        for chunk in file_chunks:
            best: tuple[str, str, object] | None = None
            for line in range(chunk.start_line, chunk.end_line + 1):
                info = line_map.get(line)
                if info and (best is None or info[2] > best[2]):
                    best = info
            if best is not None:
                entries.append(
                    BlameEntry(
                        file_path=file_path,
                        function_name=chunk.symbol,
                        last_sha=best[0],
                        last_author=best[1],
                        last_modified_at=best[2].isoformat(),
                    )
                )
    return entries
