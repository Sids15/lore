"""SQLite persistence for the git-history index (per repository)."""

from __future__ import annotations

import sqlite3
from collections import Counter

from app.history.blame import BlameEntry
from app.history.git_walker import WalkedCommit


def replace_repo_history(
    conn: sqlite3.Connection,
    repo: str,
    commits: list[WalkedCommit],
    blame_entries: list[BlameEntry],
) -> None:
    """Rebuild this repo's commit/file/authorship/blame tables. Idempotent."""
    with conn:
        conn.execute(
            "DELETE FROM commit_files WHERE sha IN (SELECT sha FROM commits WHERE repo = ?)",
            (repo,),
        )
        conn.execute("DELETE FROM commits WHERE repo = ?", (repo,))
        conn.execute("DELETE FROM blame WHERE repo = ?", (repo,))
        conn.execute("DELETE FROM authorship WHERE repo = ?", (repo,))

        conn.executemany(
            "INSERT OR REPLACE INTO commits "
            "(sha, author, author_email, committed_at, message, summary, raw_diff, repo) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            [
                (c.sha, c.author, c.author_email, c.committed_at, c.message, c.diff, repo)
                for c in commits
            ],
        )

        file_rows = [(c.sha, path, change) for c in commits for path, change in c.files]
        conn.executemany(
            "INSERT OR IGNORE INTO commit_files (sha, file_path, change_type) VALUES (?, ?, ?)",
            file_rows,
        )

        counts: Counter[tuple[str, str]] = Counter()
        for c in commits:
            for path, _ in c.files:
                counts[(c.author, path)] += 1
        conn.executemany(
            "INSERT OR REPLACE INTO authorship (repo, author, file_path, commit_count) "
            "VALUES (?, ?, ?, ?)",
            [(repo, author, path, n) for (author, path), n in counts.items()],
        )

        conn.executemany(
            "INSERT OR REPLACE INTO blame "
            "(repo, file_path, function_name, last_sha, last_author, last_modified_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (repo, b.file_path, b.function_name, b.last_sha, b.last_author, b.last_modified_at)
                for b in blame_entries
            ],
        )


def set_summary(conn: sqlite3.Connection, sha: str, summary: str) -> None:
    """Store the LLM summary for a commit (used by the summarisation stage)."""
    with conn:
        conn.execute("UPDATE commits SET summary = ? WHERE sha = ?", (summary, sha))


def existing_summaries(conn: sqlite3.Connection, repo: str) -> dict[str, str]:
    """Return already-summarised commits as ``{sha: summary}`` for this repo.

    Used by incremental indexing to skip commits already summarised (commits are
    immutable, so a stored summary never goes stale).
    """
    rows = conn.execute(
        "SELECT sha, summary FROM commits WHERE repo = ? AND summary IS NOT NULL",
        (repo,),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def commit_count(conn: sqlite3.Connection, repo: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM commits WHERE repo = ?", (repo,)).fetchone()
    return int(row[0]) if row else 0


def last_author_of_file(conn: sqlite3.Connection, repo: str, file_path: str) -> dict | None:
    """Most-recent commit touching a file (file-level 'who last changed it')."""
    row = conn.execute(
        """
        SELECT c.sha, c.author, c.committed_at, c.message
        FROM commit_files f
        JOIN commits c ON c.sha = f.sha
        WHERE c.repo = ? AND f.file_path = ?
        ORDER BY c.committed_at DESC
        LIMIT 1
        """,
        (repo, file_path),
    ).fetchone()
    if row is None:
        return None
    return {"sha": row[0], "author": row[1], "committed_at": row[2], "message": row[3]}
