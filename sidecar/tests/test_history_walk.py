"""Tests for the git walk, function-level blame, and history persistence."""

from __future__ import annotations

import git
from git import Actor

from app.db import sqlite_store
from app.history import blame, git_walker, history_store
from app.ingest.ast_chunker import chunk_repo


def _build_repo(repo_dir):
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)
    alice = Actor("Alice", "alice@example.com")
    bob = Actor("Bob", "bob@example.com")
    f = repo_dir / "m.py"

    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    repo.index.add(["m.py"])
    repo.index.commit(
        "add foo", author=alice, committer=alice,
        author_date="2026-01-01T00:00:00", commit_date="2026-01-01T00:00:00",
    )

    f.write_text("def foo():\n    return 1\n\n\ndef bar():\n    return 2\n", encoding="utf-8")
    repo.index.add(["m.py"])
    repo.index.commit(
        "add bar", author=bob, committer=bob,
        author_date="2026-02-02T00:00:00", commit_date="2026-02-02T00:00:00",
    )
    return repo


def test_walk_returns_commits_newest_first(tmp_path):
    repo_dir = tmp_path / "repo"
    _build_repo(repo_dir)

    commits = git_walker.walk(repo_dir, max_commits=50)
    assert commits is not None and len(commits) == 2
    assert commits[0].message == "add bar"
    assert commits[0].author == "Bob"
    assert "m.py" in [path for path, _ in commits[0].files]


def test_walk_returns_none_for_non_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_walker.walk(plain, max_commits=10) is None


def test_function_level_blame(tmp_path):
    repo_dir = tmp_path / "repo"
    _build_repo(repo_dir)

    chunks = chunk_repo(repo_dir)
    entries = {e.function_name: e for e in blame.blame_functions(repo_dir, chunks)}
    assert entries["foo"].last_author == "Alice"  # foo untouched since first commit
    assert entries["bar"].last_author == "Bob"  # bar added in the second commit


def test_history_persistence(tmp_path):
    repo_dir = tmp_path / "repo"
    _build_repo(repo_dir)
    commits = git_walker.walk(repo_dir, 50)
    entries = blame.blame_functions(repo_dir, chunk_repo(repo_dir))

    data = tmp_path / "data"
    sqlite_store.init_schema(data)
    conn = sqlite_store.connect(data)
    try:
        history_store.replace_repo_history(conn, "repo", commits, entries)
        # Idempotent re-run.
        history_store.replace_repo_history(conn, "repo", commits, entries)

        assert history_store.commit_count(conn, "repo") == 2
        authors = {
            row[0]
            for row in conn.execute("SELECT author FROM authorship WHERE repo = 'repo'")
        }
        assert authors == {"Alice", "Bob"}
        assert history_store.last_author_of_file(conn, "repo", "m.py")["author"] == "Bob"
        blame_rows = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT function_name, last_author FROM blame WHERE repo = 'repo'"
            )
        }
        assert ("foo", "Alice") in blame_rows
    finally:
        conn.close()
