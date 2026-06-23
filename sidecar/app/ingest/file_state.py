"""Per-file content hashing for incremental (change-aware) indexing.

Each pipeline records a SHA-256 of every file it indexes in the ``file_index``
table. On the next run it re-hashes the repo's files and asks :func:`diff_files`
which are new, changed, unchanged, or deleted — so only changed files are
re-chunked / re-embedded, and deleted files are pruned. This is pure bookkeeping:
no LLM, no embeddings, no network.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_HASH_CHUNK = 65536  # bytes read per iteration when hashing a file


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes (streamed, memory-bounded)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_files(repo_root: Path, paths: list[Path]) -> dict[str, str]:
    """Hash a list of files, keyed by their POSIX path relative to the repo root."""
    return {
        path.relative_to(repo_root).as_posix(): hash_file(path) for path in paths
    }


@dataclass
class FileDiff:
    """Classification of a repo's files against the previously-indexed hashes."""

    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def to_index(self) -> list[str]:
        """Files that need (re-)indexing: new + changed."""
        return self.new + self.changed

    @property
    def to_delete(self) -> list[str]:
        """Files whose old rows must be cleared: changed (stale chunks) + deleted."""
        return self.changed + self.deleted


def _stored_hashes(conn: sqlite3.Connection, repo: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT file_path, content_hash FROM file_index WHERE repo = ?", (repo,)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def diff_files(
    conn: sqlite3.Connection, repo: str, current: dict[str, str]
) -> FileDiff:
    """Compare current file hashes to the stored ones and classify each path."""
    stored = _stored_hashes(conn, repo)
    diff = FileDiff()
    for path, content_hash in current.items():
        if path not in stored:
            diff.new.append(path)
        elif stored[path] != content_hash:
            diff.changed.append(path)
        else:
            diff.unchanged.append(path)
    diff.deleted = [path for path in stored if path not in current]
    return diff


def record_files(conn: sqlite3.Connection, repo: str, hashes: dict[str, str]) -> None:
    """Upsert the current hashes for a repo (after a successful index pass)."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO file_index (repo, file_path, content_hash, indexed_at) "
            "VALUES (?, ?, ?, ?)",
            [(repo, path, content_hash, now) for path, content_hash in hashes.items()],
        )


def prune(conn: sqlite3.Connection, repo: str, paths: list[str]) -> None:
    """Remove file_index rows for the given paths (deleted files)."""
    if not paths:
        return
    with conn:
        conn.executemany(
            "DELETE FROM file_index WHERE repo = ? AND file_path = ?",
            [(repo, path) for path in paths],
        )


def clear_repo(conn: sqlite3.Connection, repo: str) -> None:
    """Drop all file hashes for a repo (used by a forced full re-index)."""
    with conn:
        conn.execute("DELETE FROM file_index WHERE repo = ?", (repo,))
