"""Tests for history ingestion (no network: summarise + embed mocked)."""

from __future__ import annotations

import asyncio

import git
from git import Actor

from app.config import Settings
from app.db import lancedb_client, sqlite_store
from app.history import history_index, summarize
from app.history import pipeline as history_pipeline
from app.history.history_index import _EMBEDDING_DIM


def _build_repo(repo_dir):
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)
    alice = Actor("Alice", "alice@example.com")
    f = repo_dir / "m.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    repo.index.add(["m.py"])
    repo.index.commit(
        "add foo", author=alice, committer=alice,
        author_date="2026-01-01T00:00:00", commit_date="2026-01-01T00:00:00",
    )
    return repo


def _commit(repo, repo_dir, name, message, when):
    """Add a file and commit it, returning nothing (helper for new-commit tests)."""
    from git import Actor

    author = Actor("Alice", "alice@example.com")
    (repo_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    repo.index.add([name])
    repo.index.commit(message, author=author, committer=author, author_date=when, commit_date=when)


def _patch(monkeypatch, settings, counter=None):
    monkeypatch.setattr(history_pipeline, "get_settings", lambda: settings)

    async def fake_generate(*args, **kwargs):
        return "Adds the foo function."

    monkeypatch.setattr(summarize.ollama_client, "generate", fake_generate)

    async def fake_embed_many(base_url, model, texts, **kwargs):
        if counter is not None:
            counter.append(len(texts))
        return [[0.1] * _EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(history_pipeline.ollama_client, "embed_many", fake_embed_many)


def test_index_history_stores_summaries(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    job = asyncio.run(history_pipeline.index_history(repo))
    assert job.state == "done"
    assert job.total == 1 and job.processed == 1

    db = lancedb_client.connect(data)
    assert history_index.count(db) == 1

    conn = sqlite_store.connect(data)
    try:
        summary = conn.execute("SELECT summary FROM commits WHERE repo = 'repo'").fetchone()[0]
    finally:
        conn.close()
    assert summary == "Adds the foo function."


def test_reindex_is_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    _patch(monkeypatch, Settings(data_dir=data))

    asyncio.run(history_pipeline.index_history(repo))
    asyncio.run(history_pipeline.index_history(repo))

    db = lancedb_client.connect(data)
    assert history_index.count(db) == 1  # no duplicate commit rows


def test_reindex_skips_already_summarized(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    counter: list[int] = []
    _patch(monkeypatch, Settings(data_dir=data), counter)

    first = asyncio.run(history_pipeline.index_history(repo))
    assert first.total == 1 and sum(counter) >= 1

    # Re-index with no new commits: nothing is summarised.
    counter.clear()
    second = asyncio.run(history_pipeline.index_history(repo))
    assert second.total == 0
    assert sum(counter) == 0
    assert "unchanged" in (second.message or "")


def test_new_commit_is_summarized(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo = _build_repo(repo_dir)
    data = tmp_path / "data"
    counter: list[int] = []
    _patch(monkeypatch, Settings(data_dir=data), counter)

    asyncio.run(history_pipeline.index_history(repo_dir))
    counter.clear()

    # Add a new commit, then re-index: only the new commit is summarised.
    _commit(repo, repo_dir, "n.py", "add n", "2026-02-01T00:00:00")
    job = asyncio.run(history_pipeline.index_history(repo_dir))
    assert job.total == 1
    assert sum(counter) >= 1
    assert job.message.startswith("1 new")


def test_force_resummarizes_all(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _build_repo(repo)
    data = tmp_path / "data"
    counter: list[int] = []
    _patch(monkeypatch, Settings(data_dir=data), counter)

    asyncio.run(history_pipeline.index_history(repo))
    counter.clear()

    job = asyncio.run(history_pipeline.index_history(repo, force=True))
    assert sum(counter) >= 1  # re-summarised despite no new commits
    assert job.total == 1


def test_non_git_repo_reports_error(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    _patch(monkeypatch, Settings(data_dir=tmp_path / "data"))

    job = asyncio.run(history_pipeline.index_history(plain))
    assert job.state == "error"
    assert "git" in (job.message or "").lower()
